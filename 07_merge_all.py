"""
STEP 7 — Final merge: build ispra_adb_20260630.shp

This is the main new script. It combines all per-ADB processed layers into
a single national flood hazard vector and adds two new columns:
  - 'sourceoffl'  flood source type (fluvial, seaWater, pluvial, …) from ADB Po
  - 'watercourse' name of the nearest named river (from Corpi_Idrici datasets)

USAGE:
  conda activate ccpy4
  python 07_merge_all.py

PRE-REQUISITES — the following intermediate outputs must already exist.
  Run the numbered scripts in order if any are missing:
  - 01_adb_po_overlay.py  → adb_po_2026_overlay/adb_po_2026_overlay.shp
  - 02_adb_am_overlay.py  → ADB-AM_2026_merge_RP_overlay/ADB-AM_2026_merge_RP_overlay.shp
  - 03_adb_as_overlay.py  → ADB-AS_2026_merge_RP_overlay/ADB-AS_2026_merge_RP_overlay.shp
  - 04_adb_ao_overlay.py  → ADB_AO_Tiranti/ADB_AO_Tiranti.shp
  - 06_ispra_adb_si_sa_ac.py → ispra_adbsi/, ispra_adbsa/, ispra_adbac/

  All pre-built outputs are already on local disk under D:\data\HZRD_Flood\adb_2026\.
  For the ADB Po layer, this script falls back to AA_pda2025_H_M_L.shp
  (which already carries the sourceoffl data as 'sourceOfFl') if the step-01
  output doesn't exist yet.

  Watercourse names require the Corpi_Idrici directory:
    D:\data\HZRD_Flood\adb_2026\Corpi_Idrici\
  If the directory is absent the watercourse column is written as all-NULL.

OUTPUT:
  D:\data\HZRD_Flood\adb_2026\ispra_adb_20260630\ispra_adb_20260630.shp

  Final schema:
    rp          float   return period in years (1–500)
    adb         str     basin authority code: PO | AM | AS | AO | SI | SA | AC
    sourceoffl  str     flood source type (PO data only; NULL for other ADBs)
    watercourse str     nearest named river within 2 km; NULL where not found
                        (saved as 'watercours' in .shp due to 10-char limit)
    geometry    Polygon EPSG:3035

  Compared to ispra_adb_20260414.shp, the new file adds 'sourceoffl' and 'watercourse'.
  'RP' is stored as lowercase 'rp' for DB consistency.
"""

import logging
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd

from utils import load_watercourses, assign_watercourse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

# ── Paths ─────────────────────────────────────────────────────────────────────
DATA_ROOT = Path(r"D:\data\HZRD_Flood\adb_2026")

# Watercourse line datasets — upload Corpi_Idrici folder here before running
CORPI_IDRICI_ROOT = DATA_ROOT / "Corpi_Idrici"

# Step-01 output (dissolve + overlay from sorted_cum_prob_RP_clean inputs)
PO_OVERLAY = DATA_ROOT / "adbpo_2026" / "adb_po_2026_overlay" / "adb_po_2026_overlay.shp"

# Fallback: pre-built PO overlay that already has sourceOfFl (but column named differently)
PO_FALLBACK = DATA_ROOT / "AA_pda2025" / "AA_pda2025_H_M_L" / "AA_pda2025_H_M_L.shp"

AM_PATH = DATA_ROOT / "ADB-AM_2026_merge_RP_overlay" / "ADB-AM_2026_merge_RP_overlay.shp"
AS_PATH = DATA_ROOT / "ADB-AS_2026_merge_RP_overlay" / "ADB-AS_2026_merge_RP_overlay.shp"
AO_PATH = DATA_ROOT / "ADB_AO_Tiranti" / "ADB_AO_Tiranti.shp"

SI_PATH = DATA_ROOT / "ispra_adbsi" / "ispra_adbsi.shp"
SA_PATH = DATA_ROOT / "ispra_adbsa" / "ispra_adbsa.shp"
AC_PATH = DATA_ROOT / "ispra_adbac" / "ispra_adbac.shp"

OUTPUT_DIR = DATA_ROOT / "ispra_adb_20260630"
OUTPUT_PATH = OUTPUT_DIR / "ispra_adb_20260630.shp"

TARGET_CRS = "EPSG:3035"


def load_and_standardize(path, adb_code, rp_col="RP", sourceoffl_col=None):
    """
    Load a per-ADB overlay shapefile and return a GeoDataFrame with the
    unified output schema: [rp, adb, sourceoffl, geometry].

    rp_col: name of the return-period column in the source file.
    sourceoffl_col: if set, rename that column to 'sourceoffl'; otherwise
      the column is added with all-NULL values (other ADBs don't carry it).

    to_crs() reprojects the layer to the project CRS (EPSG:3035). This is
    needed because different ADB sources come in different native CRS.
    """
    logging.info(f"  loading {adb_code} from {path.name}")
    gdf = gpd.read_file(path)
    # Repair geometry before merge — overlay outputs can have residual invalids
    gdf["geometry"] = gdf.geometry.buffer(0)

    # Normalise return-period column to lowercase 'rp'
    if rp_col != "rp":
        gdf = gdf.rename(columns={rp_col: "rp"})

    gdf["adb"] = adb_code

    if sourceoffl_col and sourceoffl_col in gdf.columns:
        gdf = gdf.rename(columns={sourceoffl_col: "sourceoffl"})
    else:
        # Column doesn't exist in this source — fill with NULL
        gdf["sourceoffl"] = None

    # Reproject to the shared CRS for the concatenation
    gdf = gdf.to_crs(TARGET_CRS)
    gdf = gdf[["rp", "adb", "sourceoffl", "geometry"]]
    logging.info(f"    {len(gdf)} polygons, CRS: {gdf.crs}")
    return gdf


# ── 1. ADB PO ─────────────────────────────────────────────────────────────────
# Prefer the step-01 output (which has sourceoffl from the sorted_cum_prob_RP_clean
# inputs). If not yet generated, fall back to AA_pda2025_H_M_L (pre-built
# dissolved+overlaid PO layer) which has 'sourceOfFl' (10-char truncation
# of sourceOfFlooding from the gpkg source) — same data, different column name.
logging.info("ADB PO")
if PO_OVERLAY.exists():
    gdf_po = load_and_standardize(PO_OVERLAY, "PO", rp_col="RP", sourceoffl_col="sourceoffl")
else:
    logging.warning(
        f"Step-01 output not found at {PO_OVERLAY}. "
        "Falling back to AA_pda2025_H_M_L with sourceOfFl column. "
        "Run 01_adb_po_overlay.py to regenerate from source data."
    )
    # AA_pda2025_H_M_L.shp stores sourceOfFlooding as 'sourceOfFl' (shapefile 10-char limit)
    gdf_po = load_and_standardize(PO_FALLBACK, "PO", rp_col="RP", sourceoffl_col="sourceOfFl")

# ── 2. ADB AM ─────────────────────────────────────────────────────────────────
logging.info("ADB AM")
gdf_am = load_and_standardize(AM_PATH, "AM")

# ── 3. ADB AS ─────────────────────────────────────────────────────────────────
logging.info("ADB AS")
gdf_as = load_and_standardize(AS_PATH, "AS")

# ── 4. ADB AO ─────────────────────────────────────────────────────────────────
# ADB_AO_Tiranti.shp has an extra 'h' column (water depth from Tiranti method);
# it is dropped in load_and_standardize since only [rp, adb, sourceoffl, geometry] are kept.
logging.info("ADB AO")
gdf_ao = load_and_standardize(AO_PATH, "AO")

# ── 5. ISPRA — SI / SA / AC ───────────────────────────────────────────────────
# These three ADB districts use the ISPRA national mosaic clipped to their
# boundaries (processed in step 06). They already have 'adb' and 'RP' columns.
logging.info("ADB SI / SA / AC (ISPRA-derived)")

def load_ispra_district(path):
    """Load an ISPRA-derived district layer — already has 'RP' and 'adb' columns."""
    gdf = gpd.read_file(path)
    gdf["geometry"] = gdf.geometry.buffer(0)
    if "RP" in gdf.columns and "rp" not in gdf.columns:
        gdf = gdf.rename(columns={"RP": "rp"})
    gdf["sourceoffl"] = None
    gdf = gdf.to_crs(TARGET_CRS)
    return gdf[["rp", "adb", "sourceoffl", "geometry"]]

gdf_si = load_ispra_district(SI_PATH)
logging.info(f"  SI: {len(gdf_si)} polygons")
gdf_sa = load_ispra_district(SA_PATH)
logging.info(f"  SA: {len(gdf_sa)} polygons")
gdf_ac = load_ispra_district(AC_PATH)
logging.info(f"  AC: {len(gdf_ac)} polygons")

# ── 6. CONCATENATE ────────────────────────────────────────────────────────────
# pd.concat stacks multiple DataFrames row-wise. ignore_index=True resets the
# integer index so the final GeoDataFrame has a clean 0…N-1 index.
# All layers are already in EPSG:3035 after load_and_standardize.
logging.info("Concatenating all ADB layers")
final = gpd.GeoDataFrame(
    pd.concat(
        [gdf_po, gdf_am, gdf_as, gdf_ao, gdf_si, gdf_sa, gdf_ac],
        ignore_index=True,
    ),
    crs=TARGET_CRS,
)
logging.info(f"Total: {len(final)} polygons")
logging.info(f"  adb distribution:\n{final['adb'].value_counts().to_string()}")
logging.info(f"  rp range: {sorted(final['rp'].dropna().unique())}")
logging.info(f"  sourceoffl non-null: {final['sourceoffl'].notna().sum()} / {len(final)}")

# ── 7. WATERCOURSE NAMES ──────────────────────────────────────────────────────
# Load all available named river line datasets from Corpi_Idrici and perform
# a nearest-neighbour join to assign a river name to each flood polygon.
# Polygons with purely non-fluvial source (seaWater, pluvial) are skipped.
logging.info("Assigning watercourse names")
if CORPI_IDRICI_ROOT.exists():
    gdf_rivers = load_watercourses(CORPI_IDRICI_ROOT, target_crs=TARGET_CRS)
else:
    logging.warning(
        f"Corpi_Idrici directory not found at {CORPI_IDRICI_ROOT}. "
        "Copy the Corpi_Idrici folder into DATA_ROOT to enable watercourse assignment. "
        "'watercourse' column will be NULL."
    )
    gdf_rivers = None

final = assign_watercourse(final, gdf_rivers, max_dist_m=2000)
logging.info(f"  watercourse non-null: {final['watercourse'].notna().sum()} / {len(final)}")

# ── 8. SAVE ───────────────────────────────────────────────────────────────────
# Column order: rp, adb, sourceoffl, watercourse, geometry
# Note: 'watercourse' (11 chars) is saved as 'watercours' in .shp (10-char limit).
final = final[["rp", "adb", "sourceoffl", "watercourse", "geometry"]]
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
final.to_file(OUTPUT_PATH)
logging.info(f"Saved → {OUTPUT_PATH}")
