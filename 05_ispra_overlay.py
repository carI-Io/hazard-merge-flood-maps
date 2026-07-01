"""
STEP 5 — ISPRA national mosaic: fast H > M > L overlay

USAGE (server only — ISPRA premerge files are large and only on the server):
  conda activate ccpy4
  python 05_ispra_overlay.py

INPUTS (server paths):
  <SERVER>/data/ISPRA/HPH_Mosaicatura_ISPRA_2020_premerge/HPH_Mosaicatura_ISPRA_2020_premerge.shp
  <SERVER>/data/ISPRA/MPH_Mosaicatura_ISPRA_2020_premerge/MPH_Mosaicatura_ISPRA_2020_premerge.shp
  <SERVER>/data/ISPRA/LPH_Mosaicatura_ISPRA_2020_premerge/LPH_Mosaicatura_ISPRA_2020_premerge.shp

  These are the ISPRA 2020 national flood hazard mosaics (PGRA). Each file
  covers all of Italy for one hazard class:
    H (HPH) = high probability, ~20–50 yr RP
    M (MPH) = medium probability, ~100–200 yr RP
    L (LPH) = low probability, ~200–500 yr RP

OUTPUT (server):
  <SERVER>/data/ISPRA/HPH_Mosaicatura_ISPRA_2020_H_M_L/
  Used as input to 06_ispra_adb_si_sa_ac.py.

NOTE: The ISPRA layers are large (millions of polygons). This script uses a
spatial-index-accelerated difference function (fast_difference) instead of
gpd.overlay which would be too slow at this scale.

NEXT STEP: run 06_ispra_adb_si_sa_ac.py
"""

import logging
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
from tqdm import tqdm

from utils import filter_valid_geoms

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

# ── Paths ─────────────────────────────────────────────────────────────────────
SERVER_ROOT = Path("/home/admin_climatecharted_com/data/flood_Adb_ispra/ISPRA")

INPUTS = {
    "H": SERVER_ROOT / "HPH_Mosaicatura_ISPRA_2020_premerge" / "HPH_Mosaicatura_ISPRA_2020_premerge.shp",
    "M": SERVER_ROOT / "MPH_Mosaicatura_ISPRA_2020_premerge" / "MPH_Mosaicatura_ISPRA_2020_premerge.shp",
    "L": SERVER_ROOT / "LPH_Mosaicatura_ISPRA_2020_premerge" / "LPH_Mosaicatura_ISPRA_2020_premerge.shp",
}

OUTPUT_DIR = SERVER_ROOT / "HPH_Mosaicatura_ISPRA_2020_H_M_L"


def fast_difference(A, B):
    """
    Spatial-index-accelerated polygon difference: A minus B.

    gpd.overlay(how='difference') iterates all pairs in A × B, which is O(n·m).
    For the ISPRA mosaic with millions of polygons this is too slow.

    This function uses the R-tree spatial index of B (B.sindex) to limit the
    search: for each polygon in A we only retrieve the small subset of B whose
    bounding box (bounds) overlaps, then compute the Shapely difference only
    for those candidates. This reduces the effective number of expensive
    geometry operations by 2–3 orders of magnitude.

    Returns a GeoDataFrame of the remaining (non-empty) A geometries.
    """
    sindex = B.sindex
    result = []

    for idx, geom in tqdm(A.geometry.items(), total=len(A), desc="fast_difference"):
        # Bounding-box candidates in B
        candidates = list(sindex.intersection(geom.bounds))
        if not candidates:
            result.append(geom)
            continue

        # Subtract candidate geometries one by one
        diff_geom = geom
        for j in candidates:
            diff_geom = diff_geom.difference(B.geometry.iloc[j])
            if diff_geom.is_empty:
                break

        if not diff_geom.is_empty:
            result.append(diff_geom)

    return gpd.GeoDataFrame(geometry=result, crs=A.crs)


# ── 1. LOAD ───────────────────────────────────────────────────────────────────
logging.info("Loading ISPRA national mosaic H/M/L")
gdfs = {}
for level, path in INPUTS.items():
    gdf = gpd.read_file(path)
    # buffer(0): repair self-intersections introduced during mosaic assembly
    gdf["geometry"] = gdf.geometry.buffer(0)
    gdfs[level] = gdf
    logging.info(f"  {level}: {len(gdf)} polygons")

# ── 2. HIERARCHICAL OVERLAY (fast version) ────────────────────────────────────
# Same H > M > L precedence logic as the other ADB scripts but using the
# bounding-box-accelerated fast_difference because the ISPRA dataset is too
# large for the standard gpd.overlay approach.
logging.info("M minus H (fast_difference)")
gdf_M_clean = fast_difference(gdfs["M"], gdfs["H"])
gdf_M_clean = filter_valid_geoms(gdf_M_clean)
logging.info(f"  M_clean: {len(gdf_M_clean)} polygons")

# Combine H + trimmed M to use as the mask for L
gdf_HM = gpd.GeoDataFrame(
    pd.concat([gdfs["H"], gdf_M_clean], ignore_index=True),
    crs=gdfs["H"].crs,
)

logging.info("L minus (H union M) (fast_difference)")
gdf_L_clean = fast_difference(gdfs["L"], gdf_HM)
gdf_L_clean = filter_valid_geoms(gdf_L_clean)
logging.info(f"  L_clean: {len(gdf_L_clean)} polygons")

# ── 3. MERGE & SAVE ──────────────────────────────────────────────────────────
final = gpd.GeoDataFrame(
    pd.concat([gdfs["H"], gdf_M_clean, gdf_L_clean], ignore_index=True),
    crs=gdfs["H"].crs,
)

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
out_path = OUTPUT_DIR / "HPH_Mosaicatura_ISPRA_2020_H_M_L.shp"
final.to_file(out_path)
logging.info(f"Saved → {out_path} ({len(final)} polygons)")
