"""
Shared spatial utilities for the flood hazard pipeline.

Imported by 01–07 scripts. Contains geometry helpers and the two core
spatial algorithms: graph-based topological dissolve and H>M>L overlay,
plus watercourse name assignment from regional and national line datasets.
"""

import logging
import re
from pathlib import Path

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


def load_watercourses(corpi_idrici_root, target_crs="EPSG:3035"):
    """
    Load and merge all available watercourse line datasets from Corpi_Idrici.

    Returns a GeoDataFrame with columns ['name', 'geometry'] in target_crs,
    containing only named lines. Returns None if no datasets are found.

    Datasets used (all under corpi_idrici_root/):
      - Reticolo_Idrografico/Elementi_Idrici.shp  national network, Po basin
      - REGIONE PIEMONTE .../Tratti_idrici_Piemonte.shp  full Piemonte
      - REGIONE_LOMBARDIA/Corsi_acqua_AIPO.shp    main managed rivers
      - REGIONE_LOMBARDIA/Tratti_idrici_Lombardia.shp
      - REGIONE VENETO .../Tratti_idrici_Veneto.shp

    Not used: Tratti_Idrici/Tratti_Idrici.shp (641k lines but no river names,
    only a 'layer' source-label column), Corsi_acqua_RIB.shp (drainage canals).
    """
    root = Path(corpi_idrici_root)
    parts = []

    def _try_load(rel, name_col, transform=None):
        """Load one source, keep named lines, reproject, append to parts."""
        path = root / rel
        if not path.exists():
            logging.warning(f"  watercourse source not found: {path}")
            return
        gdf = gpd.read_file(path)
        if name_col not in gdf.columns:
            logging.warning(f"  column '{name_col}' not in {path.name}; skipping")
            return
        gdf = gdf[[name_col, "geometry"]].rename(columns={name_col: "name"})
        # Drop rows without a usable name
        gdf = gdf[gdf["name"].notna()]
        gdf = gdf[gdf["name"].astype(str).str.strip() != ""]
        # Drop placeholder "senza nome" tokens that carry no river identity
        _NO_NAME = {"s.n.", "senza nome", "n.d.", "nd", "-"}
        gdf = gdf[~gdf["name"].astype(str).str.strip().str.lower().isin(_NO_NAME)]
        if transform:
            gdf["name"] = gdf["name"].apply(transform)
        gdf = gdf[gdf.geometry.notna()].to_crs(target_crs)
        parts.append(gdf)
        logging.info(f"  {len(gdf):,} named lines from {path.name}")

    # National network (Po basin only). Names come as "Adda (Fiume)" —
    # strip the parenthetical type suffix to get a clean river name.
    _try_load(
        r"Reticolo_Idrografico/Elementi_Idrici.shp",
        "toponimo",
        transform=lambda n: re.sub(r"\s*\(.*\)\s*$", "", str(n)).strip(),
    )
    # Piemonte — already clean: "Fiume Tanaro", "S.N." (senza nome), etc.
    _try_load(
        r"REGIONE PIEMONTE DBPrior_elemidri/Tratti_idrici_Piemonte.shp",
        "NOMINU10",
    )
    # Lombardia managed rivers (AIPO concession list) — best quality names (all-caps)
    _try_load(
        r"REGIONE_LOMBARDIA/Corsi_acqua_AIPO.shp",
        "NOME",
        transform=lambda n: str(n).title(),
    )
    # Lombardia full regional network (all-caps names)
    _try_load(
        r"REGIONE_LOMBARDIA/Tratti_idrici_Lombardia.shp",
        "NOME",
        transform=lambda n: str(n).title(),
    )
    # Veneto — names are all-caps ("FIUME TIONE"), convert to title case
    _try_load(
        r"REGIONE VENETO Corpi_Idrici_Fiumi_DGR_3_2022/Tratti_idrici_Veneto.shp",
        "NOME_CI",
        transform=lambda n: str(n).title(),
    )

    if not parts:
        logging.warning("No watercourse datasets found; 'watercourse' column will be NULL.")
        return None

    merged = gpd.GeoDataFrame(
        pd.concat(parts, ignore_index=True),
        crs=target_crs,
    )
    logging.info(f"  total watercourse lines merged: {len(merged):,}")
    return merged


def assign_watercourse(gdf_flood, gdf_rivers, max_dist_m=2000):
    """
    Assign the nearest named watercourse to each flood polygon.

    Strategy:
      - Compute the centroid of each flood polygon (fast proxy for position).
      - Use sjoin_nearest (R-tree accelerated) to find the closest river line.
      - Only consider rivers within max_dist_m metres; assign NULL beyond that.

    Flood zones with a purely non-fluvial source are skipped because they
    have no associated river channel:
      - 'seaWater'  → coastal inundation (no river)
      - 'pluvial'   → diffuse surface runoff (no single channel)
    Zones with NULL source or any fluvial component are eligible.

    Returns gdf_flood with a new 'watercourse' column added.
    Note: when saved as shapefile the column truncates to 'watercours' (10-char
    shapefile limit); in GeoPackage the full name is preserved.
    """
    gdf_flood = gdf_flood.copy()
    gdf_flood["watercourse"] = None

    if gdf_rivers is None or len(gdf_rivers) == 0:
        logging.warning("No river data available; 'watercourse' will be NULL for all rows.")
        return gdf_flood

    def _is_eligible(sf):
        """Return True if the flood source type may involve a river."""
        if pd.isna(sf):
            return True  # unknown → assume could be fluvial (all non-PO ADBs)
        s = str(sf).lower()
        if s.startswith("seawater"):
            return False  # coastal
        # Skip purely pluvial; keep anything with a fluvial component
        # ("fluvia" handles the "fluvia;" typo variant too)
        if "pluvial" in s and "fluvia" not in s:
            return False
        return True

    eligible_mask = gdf_flood["sourceoffl"].apply(_is_eligible)
    eligible = gdf_flood[eligible_mask]

    if len(eligible) == 0:
        logging.info("  no eligible rows for watercourse assignment")
        return gdf_flood

    # Use centroids: much faster than polygon–line distance for 800k+ rows
    pts = eligible.copy()
    pts.geometry = eligible.geometry.centroid

    # sjoin_nearest uses an R-tree index on gdf_rivers, then measures
    # actual geometry distance for candidates — O(n log m) per row.
    joined = gpd.sjoin_nearest(
        pts[["geometry"]],
        gdf_rivers[["name", "geometry"]],
        how="left",
        max_distance=max_dist_m,
    )

    # sjoin_nearest can duplicate rows for exact-tie distances; keep first
    joined = joined[~joined.index.duplicated(keep="first")]

    # Reindex to align with eligible rows (fills missing matches with NaN)
    river_names = joined["name"].reindex(eligible.index)

    gdf_flood.loc[eligible.index, "watercourse"] = river_names.values

    n_assigned = gdf_flood["watercourse"].notna().sum()
    n_eligible = eligible_mask.sum()
    logging.info(
        f"  watercourse assigned: {n_assigned:,} / {n_eligible:,} eligible "
        f"({len(gdf_flood) - n_eligible:,} skipped as non-fluvial)"
    )
    return gdf_flood
