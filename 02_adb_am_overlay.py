"""
STEP 2 — ADB Alto Adriatico / Alpi Marittime: topological dissolve

USAGE:
  conda activate ccpy4
  python 02_adb_am_overlay.py

INPUT:
  <DATA_ROOT>/adbam_2026/ADB-AM_2026_merge_cum_prob_RP/ADB-AM_2026_merge_cum_prob_RP.shp
  Columns include: RP (cumulative-probability return period, float), geometry.
  The source is already a single merged shapefile — no H/M/L split — so only
  the topological dissolve is needed (no hierarchical overlay step).

OUTPUT:
  <DATA_ROOT>/ADB-AM_2026_merge_RP_overlay/ADB-AM_2026_merge_RP_overlay.shp
  Columns: RP (float), geometry

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
DATA_ROOT = Path(r"D:\data\HZRD_Flood\adb_2026")

INPUT = (
    DATA_ROOT
    / "adbam_2026"
    / "ADB-AM_2026_merge_cum_prob_RP"
    / "ADB-AM_2026_merge_cum_prob_RP.shp"
)
OUTPUT_DIR = DATA_ROOT / "ADB-AM_2026_merge_RP_overlay"

# ── 1. LOAD ───────────────────────────────────────────────────────────────────
logging.info("Loading ADB AM")
gdf = gpd.read_file(INPUT)
# buffer(0): repair any degenerate ring orientations before spatial ops
gdf["geometry"] = gdf.geometry.buffer(0)
logging.info(f"  loaded {len(gdf)} polygons, RP range: {sorted(gdf['RP'].dropna().unique())}")

# ── 2. DISSOLVE ───────────────────────────────────────────────────────────────
# The AM dataset already encodes the return period in the RP column derived from
# cumulative-probability analysis. Adjacent flood polygons for the same RP that
# share a boundary are merged into a single geometry. This reduces feature count
# and removes tile artefacts before the final spatial merge.
logging.info("Dissolving ADB AM by RP")
gdf_dissolved = dissolve_touching_by_rp(gdf)
logging.info(f"  dissolved: {len(gdf_dissolved)} polygons")

# ── 3. SAVE ───────────────────────────────────────────────────────────────────
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
out_path = OUTPUT_DIR / "ADB-AM_2026_merge_RP_overlay.shp"
gdf_dissolved[["RP", "geometry"]].to_file(out_path)
logging.info(f"Saved → {out_path}")
