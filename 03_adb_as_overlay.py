"""
STEP 3 — ADB Alpi Settentrionali: topological dissolve

USAGE:
  conda activate ccpy4
  python 03_adb_as_overlay.py

INPUT:
  <DATA_ROOT>/adbas_2026/PIANIFICAZIONE_SIT_PGRA_ITC_FLUVIAL_cum_prob_RP/
    PIANIFICAZIONE_SIT_PGRA_ITC_FLUVIAL_cum_prob_RP.shp
  Single pre-merged shapefile with RP already computed.
  Like ADB AM, this does not need a hierarchical overlay — only dissolve.

OUTPUT:
  <DATA_ROOT>/ADB-AS_2026_merge_RP_overlay/ADB-AS_2026_merge_RP_overlay.shp
  Columns: RP (int/float), geometry

NEXT STEP: run 07_merge_all.py (or run all steps 01–06 first)
"""

import logging
import sys
from pathlib import Path

import geopandas as gpd

from utils import dissolve_touching_by_rp

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

# ── Paths ─────────────────────────────────────────────────────────────────────
SERVER_ROOT = Path("/home/admin_climatecharted_com/data/flood_Adb_ispra/ISPRA")

INPUT = (
    SERVER_ROOT
    / "adbas_2026"
    / "PIANIFICAZIONE_SIT_PGRA_ITC_FLUVIAL_cum_prob_RP"
    / "PIANIFICAZIONE_SIT_PGRA_ITC_FLUVIAL_cum_prob_RP.shp"
)
OUTPUT_DIR = SERVER_ROOT / "ADB-AS_2026_merge_RP_overlay"

# ── 1. LOAD ───────────────────────────────────────────────────────────────────
logging.info("Loading ADB AS")
gdf = gpd.read_file(INPUT)
gdf["geometry"] = gdf.geometry.buffer(0)
logging.info(f"  loaded {len(gdf)} polygons, RP range: {sorted(gdf['RP'].dropna().unique())}")

# ── 2. DISSOLVE ───────────────────────────────────────────────────────────────
# Same logic as ADB AM: the source is already a single merged file with
# cumulative-probability RP values. We dissolve touching polygons per RP
# to unify tile boundaries before the final merge step.
logging.info("Dissolving ADB AS by RP")
gdf_dissolved = dissolve_touching_by_rp(gdf)
logging.info(f"  dissolved: {len(gdf_dissolved)} polygons")

# ── 3. SAVE ───────────────────────────────────────────────────────────────────
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
out_path = OUTPUT_DIR / "ADB-AS_2026_merge_RP_overlay.shp"
gdf_dissolved[["RP", "geometry"]].to_file(out_path)
logging.info(f"Saved → {out_path}")
