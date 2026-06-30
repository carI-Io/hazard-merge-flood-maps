"""
STEP 6 — Clip ISPRA national mosaic to ADB Sicilia, Sardegna, Appennino Centrale

USAGE (server only — requires ISPRA premerge files and district boundary files):
  conda activate ccpy4
  python 06_ispra_adb_si_sa_ac.py

INPUTS (server paths):
  ISPRA national H/M/L premerge shapefiles (same as step 05)
  District boundary shapefiles:
    <SERVER>/data/ADB/delimitazione_distretto_ADB_Sicilia/delimitazione_distretto_ADB_Sicilia.shp
    <SERVER>/data/ADB/delimitazione_distretto_ADB_Sardegna/delimitazione_distretto_ADB_Sardegna.shp
    <SERVER>/data/ADB/delimitazione_distretto_ADB_App_Centrale/delimitazione_distretto_ADB_App_Centrale.shp

WHY: Sicily (SI), Sardinia (SA), and the Central Apennines district (AC) do not
have their own PGRA hazard maps. The national ISPRA mosaic is used as a proxy,
clipped to each district's administrative boundary.

  H → RP = 20 (ISPRA H class corresponds roughly to a 20-yr return period)
  M → RP = 100
  L → RP = 200

OUTPUTS (server):
  <SERVER>/data/ADB/ispra_adbsi/
  <SERVER>/data/ADB/ispra_adbsa/
  <SERVER>/data/ADB/ispra_adbac/

  Locally pre-built outputs already exist at:
    D:\data\HZRD_Flood\adb_2026\ispra_adbsi\ispra_adbsi.shp
    D:\data\HZRD_Flood\adb_2026\ispra_adbsa\ispra_adbsa.shp
    D:\data\HZRD_Flood\adb_2026\ispra_adbac\ispra_adbac.shp
  Skip this script if you don't need to reprocess.

NEXT STEP: run 07_merge_all.py
"""

import logging
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd

from utils import filter_valid_geoms

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

# ── Paths ─────────────────────────────────────────────────────────────────────
SERVER_ROOT = Path("/home/admin_climatecharted_com/data")

ISPRA_INPUTS = {
    "H": SERVER_ROOT / "ISPRA/HPH_Mosaicatura_ISPRA_2020_premerge/HPH_Mosaicatura_ISPRA_2020_premerge.shp",
    "M": SERVER_ROOT / "ISPRA/MPH_Mosaicatura_ISPRA_2020_premerge/MPH_Mosaicatura_ISPRA_2020_premerge.shp",
    "L": SERVER_ROOT / "ISPRA/LPH_Mosaicatura_ISPRA_2020_premerge/LPH_Mosaicatura_ISPRA_2020_premerge.shp",
}

# Standard RP values assigned to ISPRA H/M/L classes for SI/SA/AC districts
RP_MAP = {"H": 20, "M": 100, "L": 200}

DISTRICTS = {
    "SI": SERVER_ROOT / "ADB/delimitazione_distretto_ADB_Sicilia/delimitazione_distretto_ADB_Sicilia.shp",
    "SA": SERVER_ROOT / "ADB/delimitazione_distretto_ADB_Sardegna/delimitazione_distretto_ADB_Sardegna.shp",
    "AC": SERVER_ROOT / "ADB/delimitazione_distretto_ADB_App_Centrale/delimitazione_distretto_ADB_App_Centrale.shp",
}

OUTPUT_ROOT = SERVER_ROOT / "ADB"


def process_district(delim_gdf, ispra_gdfs, adb_name):
    """
    Clip ISPRA H/M/L to the district boundary and apply H > M > L overlay.

    gpd.clip(gdf, mask) clips `gdf` to the bounding polygon `mask`:
    it keeps only the portions of each polygon that fall inside the mask
    and discards everything outside. This is equivalent to a spatial
    intersection restricted to the input geometry shape.

    After clipping, the H > M > L overlay ensures that within the
    district, high-probability zones take precedence over medium and low.
    """
    logging.info(f"Processing {adb_name}")

    # Clip each ISPRA hazard class to the district boundary
    target_crs = ispra_gdfs["H"].crs
    delim_reproj = delim_gdf.to_crs(target_crs)

    H = gpd.clip(ispra_gdfs["H"], delim_reproj)
    M = gpd.clip(ispra_gdfs["M"], delim_reproj)
    L = gpd.clip(ispra_gdfs["L"], delim_reproj)
    logging.info(f"  {adb_name} clipped")

    # Assign standardised RP and district code
    for gdf, level in [(H, "H"), (M, "M"), (L, "L")]:
        gdf["RP"] = RP_MAP[level]
        gdf["adb"] = adb_name

    # Keep only the columns needed for the output schema
    H = H[["RP", "adb", "geometry"]].copy()
    M = M[["RP", "adb", "geometry"]].copy()
    L = L[["RP", "adb", "geometry"]].copy()

    # H > M > L overlay: trim M against H, then L against H+M
    M_clean = gpd.overlay(M, H[["geometry"]], how="difference", keep_geom_type=False)
    M_clean = filter_valid_geoms(M_clean)
    logging.info(f"  {adb_name} M_clean overlayed")

    HM = gpd.GeoDataFrame(
        pd.concat([H, M_clean], ignore_index=True),
        crs=H.crs,
    )

    L_clean = gpd.overlay(L, HM[["geometry"]], how="difference", keep_geom_type=False)
    L_clean = filter_valid_geoms(L_clean)
    logging.info(f"  {adb_name} L_clean overlayed")

    final = gpd.GeoDataFrame(
        pd.concat([H, M_clean, L_clean], ignore_index=True),
        crs=H.crs,
    )
    # Re-enforce the adb column after overlay (overlay can drop non-geometry cols)
    final["adb"] = adb_name
    final = final[["RP", "adb", "geometry"]]
    logging.info(f"  {adb_name} done: {len(final)} polygons")
    return final


# ── 1. LOAD ISPRA ─────────────────────────────────────────────────────────────
logging.info("Loading ISPRA national mosaic")
ispra_gdfs = {}
for level, path in ISPRA_INPUTS.items():
    gdf = gpd.read_file(path)
    gdf["geometry"] = gdf.geometry.buffer(0)
    ispra_gdfs[level] = gdf
    logging.info(f"  {level}: {len(gdf)} polygons")

# ── 2. LOAD DISTRICT BOUNDARIES ───────────────────────────────────────────────
logging.info("Loading district boundaries")
delims = {}
for adb_name, path in DISTRICTS.items():
    gdf = gpd.read_file(path)
    delims[adb_name] = gdf
    logging.info(f"  {adb_name} boundary loaded")

# ── 3. PROCESS EACH DISTRICT ──────────────────────────────────────────────────
results = {}
for adb_name, delim_gdf in delims.items():
    results[adb_name] = process_district(delim_gdf, ispra_gdfs, adb_name)

# ── 4. SAVE ───────────────────────────────────────────────────────────────────
for adb_name, gdf in results.items():
    out_dir = OUTPUT_ROOT / f"ispra_adb{adb_name.lower()}"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"ispra_adb{adb_name.lower()}.shp"
    gdf.to_file(out_path)
    logging.info(f"Saved {adb_name} → {out_path}")
