"""
STEP 4 — ADB Appennino Occidentale / Valle d'Aosta: H > M > L overlay (Tiranti method)

USAGE:
  conda activate ccpy4
  python 04_adb_ao_overlay.py

INPUTS (server paths — Tiranti premerge files):
  <SERVER>/data/ADB/adb_ao/Tiranti_TR30_HPH_premerge/Tiranti_TR30_HPH_premerge.shp   → H (RP=30)
  <SERVER>/data/ADB/adb_ao/Tiranti_TR100_MPH_premerge/Tiranti_TR100_MPH_premerge.shp → M (RP=100)
  <SERVER>/data/ADB/adb_ao/Tiranti_TR300_LPH_premerge/Tiranti_TR300_LPH_premerge.shp → L (RP=300)

  NOTE: these raw Tiranti shapefiles are only available on the server.
  The processed output ADB_AO_Tiranti.shp already exists locally:
    D:\data\HZRD_Flood\adb_2026\ADB_AO_Tiranti\ADB_AO_Tiranti.shp
  Skip this script if you don't need to reprocess from raw.

OUTPUT:
  <DATA_ROOT>/ADB_AO_Tiranti/ADB_AO_Tiranti.shp
  Columns: RP (int), geometry

NEXT STEP: run 07_merge_all.py (or run all steps 01–06 first)
"""

import logging
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd

from utils import filter_valid_geoms, hierarchical_overlay

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

# ── Paths ─────────────────────────────────────────────────────────────────────
# Server-side Linux paths for the raw Tiranti premerge files
SERVER_ROOT = Path("/home/admin_climatecharted_com/data/flood_Adb_ispra/ADB/adb_ao")

INPUTS = {
    "H": SERVER_ROOT / "Tiranti_TR30_HPH_premerge" / "Tiranti_TR30_HPH_premerge.shp",
    "M": SERVER_ROOT / "Tiranti_TR100_MPH_premerge" / "Tiranti_TR100_MPH_premerge.shp",
    "L": SERVER_ROOT / "Tiranti_TR300_LPH_premerge" / "Tiranti_TR300_LPH_premerge.shp",
}

# Return periods corresponding to the Tiranti scenarios
RP_MAP = {"H": 30, "M": 100, "L": 300}

OUTPUT_DIR = Path("/home/admin_climatecharted_com/data/ADB/adb_ao/ADB_AO_Tiranti")

# ── 1. LOAD & ASSIGN RP ──────────────────────────────────────────────────────
# The Tiranti shapefiles don't carry a return-period attribute; the RP is
# implicit in the scenario name (TR30 = 30-year return period, etc.).
# We assign RP manually so the schema is consistent with other ADB layers.
logging.info("Loading ADB AO Tiranti layers")
gdfs = {}
for level, path in INPUTS.items():
    gdf = gpd.read_file(path)
    gdf["geometry"] = gdf.geometry.buffer(0)
    gdf["RP"] = RP_MAP[level]
    gdfs[level] = gdf
    logging.info(f"  {level}: {len(gdf)} polygons (RP={RP_MAP[level]})")

# Reproject all to EPSG:3035 (ETRS89 LAEA — standard Italian CRS for area-accurate ops)
# to_crs() reprojects coordinates from the source CRS to the target.
# We use EPSG:3035 because it is equal-area and metric, making area-based
# filtering (filter_valid_geoms) meaningful in m².
target_crs = "EPSG:3035"
gdfs = {k: v.to_crs(target_crs) for k, v in gdfs.items()}

# ── 2. HIERARCHICAL OVERLAY ───────────────────────────────────────────────────
# Tiranti data is already clean (pre-dissolved), so no dissolve step needed.
# We go directly to the H > M > L overlay.
logging.info("Running H > M > L hierarchical overlay for ADB AO")
final = hierarchical_overlay(
    gdfs["H"],
    gdfs["M"],
    gdfs["L"],
    schema_cols=["RP"],
)
logging.info(f"Overlay done: {len(final)} polygons")

# ── 3. SAVE ───────────────────────────────────────────────────────────────────
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
out_path = OUTPUT_DIR / "ADB_AO_Tiranti.shp"
final[["RP", "geometry"]].to_file(out_path)
logging.info(f"Saved → {out_path}")
