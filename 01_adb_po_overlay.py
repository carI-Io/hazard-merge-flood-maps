"""
STEP 1 — ADB Po basin: dissolve + hierarchical overlay (preserves sourceoffl)

USAGE:
  conda activate ccpy4
  python 01_adb_po_overlay.py

INPUTS (Windows local paths — adjust DATA_ROOT if running on Linux server):
  <DATA_ROOT>/adbpo_2026/adb_po_2026_H_sorted_cum_prob_RP_clean/adb_po_2026_H_sorted_cum_prob_RP_clean.shp
  <DATA_ROOT>/adbpo_2026/adb_po_2026_M_sorted_cum_prob_RP_clean/adb_po_2026_M_sorted_cum_prob_RP_clean.shp
  <DATA_ROOT>/adbpo_2026/adb_po_2026_L_sorted_cum_prob_RP_clean/adb_po_2026_L_sorted_cum_prob_RP_clean.shp

  Each file has columns: fid, competenta, nomeelidr, sourceoffl, returnnperi, legenda, RP, geometry
  RP is already a numeric return period (float).
  nomeelidr is the official name of the hydrographic element (river, lake, etc.) — populated
    directly from the EU Flood Directive reporting data, per polygon.
  sourceoffl encodes the flood source (fluvial, seaWater, pluvial, etc.); ~2–5 % of rows are filled.

OUTPUT:
  <DATA_ROOT>/adbpo_2026/adb_po_2026_overlay/adb_po_2026_overlay.shp
  Columns: RP (float), sourceoffl (str | None), nomeelidr (str | None), geometry

NEXT STEP: run 07_merge_all.py
"""

import logging
import sys
from pathlib import Path

import geopandas as gpd

from utils import dissolve_touching_by_rp, filter_valid_geoms, hierarchical_overlay

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

# ── Paths ─────────────────────────────────────────────────────────────────────
# Change DATA_ROOT to match the server path when running remotely.
# DATA_ROOT = Path(r"D:\data\HZRD_Flood\adb_2026\adbpo_2026")
DATA_ROOT = Path(r"/home/admin_climatecharted_com/data/flood_adb_ispra")

INPUTS = {
    "H": DATA_ROOT / "ADB/adb_po_2026/adb_po_2026_H_sorted_cum_prob_RP_clean" / "adb_po_2026_H_sorted_cum_prob_RP_clean.shp",
    "M": DATA_ROOT / "ADB/adb_po_2026/adb_po_2026_M_sorted_cum_prob_RP_clean" / "adb_po_2026_M_sorted_cum_prob_RP_clean.shp",
    "L": DATA_ROOT / "ADB/adb_po_2026/adb_po_2026_L_sorted_cum_prob_RP_clean" / "adb_po_2026_L_sorted_cum_prob_RP_clean.shp",
}

OUTPUT_DIR = DATA_ROOT / "ADB/adb_po_2026/adb_po_2026_overlay_20260702"

# ── 1. LOAD ───────────────────────────────────────────────────────────────────
# gpd.read_file reads a vector file into a GeoDataFrame (a pandas DataFrame
# with a geometry column). buffer(0) is applied immediately on load to repair
# any invalid ring winding orders flagged by pyogrio warnings.
logging.info("Loading PO H/M/L inputs")
gdfs = {}
for level, path in INPUTS.items():
    gdf = gpd.read_file(path)
    gdf["geometry"] = gdf.geometry.buffer(0)
    # Keep RP, the two attribute columns, and geometry.
    # nomeelidr (nome elemento idrografico) = the official river/lake name per polygon,
    # as reported under the EU Flood Directive. It is carried through dissolve and
    # overlay so the final output has per-polygon river attribution.
    gdf = gdf[["RP", "sourceoffl", "nomeelidr", "geometry"]].copy()
    gdfs[level] = gdf
    logging.info(f"  {level}: {len(gdf)} polygons, RP range {sorted(gdf['RP'].dropna().unique())}")

# ── 2. DISSOLVE ───────────────────────────────────────────────────────────────
# The source data tiles one shapefile per basin section (UoM), producing many
# small polygons that represent the same flood zone split at administrative
# boundaries. dissolve_touching_by_rp merges touching/overlapping polygons
# within the same RP class into single geometries. extra_cols=['sourceoffl']
# carries the flood-source attribute through: the first non-null value in each
# merged component is used (most tiles have NULL; filled values are kept).
logging.info("Dissolving PO H")
gdf_H_diss = dissolve_touching_by_rp(gdfs["H"], extra_cols=["sourceoffl", "nomeelidr"])
logging.info(f"  H dissolved: {len(gdf_H_diss)} polygons")

logging.info("Dissolving PO M")
gdf_M_diss = dissolve_touching_by_rp(gdfs["M"], extra_cols=["sourceoffl", "nomeelidr"])
logging.info(f"  M dissolved: {len(gdf_M_diss)} polygons")

logging.info("Dissolving PO L")
gdf_L_diss = dissolve_touching_by_rp(gdfs["L"], extra_cols=["sourceoffl", "nomeelidr"])
logging.info(f"  L dissolved: {len(gdf_L_diss)} polygons")

# ── 3. HIERARCHICAL OVERLAY ───────────────────────────────────────────────────
# gpd.overlay(M, H, how='difference') removes from M every part that spatially
# overlaps with H. This enforces the hazard hierarchy H > M > L: where areas
# are classified as high-probability (H), the medium/low labels are dropped to
# avoid double-counting flood exposure.
logging.info("Running H > M > L hierarchical overlay for PO")
final = hierarchical_overlay(
    gdf_H_diss,
    gdf_M_diss,
    gdf_L_diss,
    schema_cols=["RP", "sourceoffl", "nomeelidr"],
)
logging.info(f"Overlay done: {len(final)} polygons")

# ── 4. SAVE ───────────────────────────────────────────────────────────────────
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
out_path = OUTPUT_DIR / "adb_po_2026_overlay.shp"
final[["RP", "sourceoffl", "nomeelidr", "geometry"]].to_file(out_path)
logging.info(f"Saved → {out_path}")
