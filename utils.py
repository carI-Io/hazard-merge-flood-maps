"""
Shared spatial utilities for the flood hazard pipeline.

Imported by 01–07 scripts. Contains geometry helpers and the two core
spatial algorithms: graph-based topological dissolve and H>M>L overlay.
"""

import logging
import pandas as pd
import geopandas as gpd
import networkx as nx

# Minimum polygon area in CRS units (m² for EPSG:3035).
# Polygons smaller than this are topology artefacts created by overlay operations
# and are discarded to keep the output clean.
MIN_AREA = 0.25


def filter_valid_geoms(gdf):
    """
    Fix invalid geometries and discard slivers.

    buffer(0) is the standard Shapely trick to repair self-intersections:
    it forces the geometry through the JTS topology engine, which closes
    unclosed rings and removes degenerate edges, without changing the shape.
    Polygons below MIN_AREA are overlay artefacts (near-zero-area slivers
    at shared boundaries) and are safe to drop.
    """
    gdf = gdf.copy()
    gdf["geometry"] = gdf.geometry.buffer(0)
    gdf = gdf[~gdf.geometry.is_empty]
    gdf = gdf[gdf.geometry.area > MIN_AREA]
    return gdf


def dissolve_touching_by_rp(gdf, extra_cols=None):
    """
    Graph-based topological dissolve, grouped by RP.

    Many source shapefiles split flood zones into hundreds of small tiles
    per return period. This function merges tiles that touch or overlap
    within the same RP class into a single polygon.

    Algorithm:
      1. Build an R-tree spatial index (gdf.sindex) for fast bounding-box
         lookup — avoids the O(n²) cost of testing every pair.
      2. For each polygon, query the index for candidates whose bbox overlaps,
         then test the actual geometry relationship (touches or intersects).
      3. Represent the connectivity as a NetworkX undirected graph where
         nodes are polygon indices and edges connect adjacent polygons.
      4. Find connected components with nx.connected_components: each
         component is a set of polygons that form one contiguous flood zone.
      5. Merge each component into a single geometry with union_all().

    extra_cols: attribute columns to carry through the dissolve.
      For each component, the first non-null value across member polygons
      is used (e.g. sourceoffl may be filled for some tiles but not all).
    """
    gdf = gdf.copy()
    # Repair geometry before spatial operations
    gdf["geometry"] = gdf.geometry.buffer(0)
    result = []

    for rp_value, group in gdf.groupby("RP"):
        logging.info(f"  dissolving RP={rp_value} ({len(group)} polygons)")
        group = filter_valid_geoms(group).reset_index(drop=True)
        if len(group) == 0:
            continue

        # R-tree index for fast candidate lookup
        sindex = group.sindex
        G = nx.Graph()

        for i, geom in enumerate(group.geometry):
            G.add_node(i)
            # Bounding-box candidates — much cheaper than geometry intersection
            candidates = list(sindex.intersection(geom.bounds))
            for j in candidates:
                if i >= j:
                    continue
                if geom.touches(group.geometry.iloc[j]) or geom.intersects(group.geometry.iloc[j]):
                    G.add_edge(i, j)

        # Each connected component → one merged polygon
        for comp in nx.connected_components(G):
            subset = group.loc[list(comp)]
            # union_all() merges all geometries in the component into one
            merged_geom = subset.union_all()

            row = {"RP": rp_value, "geometry": merged_geom}

            # Carry through optional attribute columns
            if extra_cols:
                for col in extra_cols:
                    if col in subset.columns:
                        non_null = subset[col].dropna()
                        row[col] = non_null.iloc[0] if len(non_null) > 0 else None

            result.append(row)

    return gpd.GeoDataFrame(result, crs=gdf.crs)


def hierarchical_overlay(gdf_H, gdf_M, gdf_L, schema_cols):
    """
    Apply H > M > L precedence: higher-probability zones take priority.

    Flood hazard maps define three nested hazard classes:
      H = high probability (short return period, frequent floods)
      M = medium probability
      L = low probability (long return period, rare but severe floods)

    Where these classes overlap spatially, only the most frequent one is
    kept: H wins over M and L, M wins over L. This prevents double-counting
    areas that appear in multiple hazard layers.

    gpd.overlay(left, right, how='difference') returns the portion of `left`
    that does NOT intersect `right` — i.e. it erases from left everything
    covered by right.

    We pass only the geometry column of the mask layer to avoid column
    name conflicts in the overlay output.

    schema_cols: list of columns to keep in the final output (besides geometry).
    """
    # Use only geometry from H as the mask — avoids column conflicts
    H_mask = gdf_H[["geometry"]]
    M_mask = gdf_M[["geometry"]]

    # Trim M: keep only the parts of M not already covered by H
    gdf_M_clean = gpd.overlay(
        gdf_M[schema_cols + ["geometry"]],
        H_mask,
        how="difference",
        keep_geom_type=False,  # retains any geometry type; filter_valid_geoms keeps only polygons
    )
    gdf_M_clean = filter_valid_geoms(gdf_M_clean)
    logging.info("  M_clean overlay done")

    # Combined H + trimmed M used as the mask for L
    HM_mask = gpd.GeoDataFrame(
        pd.concat([H_mask, M_mask], ignore_index=True),
        crs=gdf_H.crs,
    )

    # Trim L: keep only the parts of L not covered by H or M
    gdf_L_clean = gpd.overlay(
        gdf_L[schema_cols + ["geometry"]],
        HM_mask,
        how="difference",
        keep_geom_type=False,
    )
    gdf_L_clean = filter_valid_geoms(gdf_L_clean)
    logging.info("  L_clean overlay done")

    # Stack the three non-overlapping layers into the final output
    final = gpd.GeoDataFrame(
        pd.concat(
            [gdf_H[schema_cols + ["geometry"]], gdf_M_clean, gdf_L_clean],
            ignore_index=True,
        ),
        crs=gdf_H.crs,
    )
    return final
