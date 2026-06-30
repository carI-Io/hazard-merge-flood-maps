"""
STEP 9 — Integrate higher-resolution Milano TR500 depth raster

USAGE (server only):
  conda activate ccpy4
  python 09_adbpo_raster_merge_milano.py

INPUTS:
  <SERVER>/data/Altezza/adbpo_pgra2027_l_merged_3035_5m.tif  (from step 08)
  <SERVER>/data/Altezza/Milano_TR500_5m.tif
    Higher-resolution flood depth model for the Milan metropolitan area at TR500.
    Both rasters must be on the same EPSG:3035 grid and resolution (5 m).

WHY: The ADB Po PGRA 2027 raster uses a coarser hydraulic model for the Milan
area. A separate high-resolution model (TR500, 5 m) provides better local
accuracy. Where the two rasters overlap, the higher depth value is kept
(conservative / worst-case assumption). Where only Milano has data (ADB Po
has nodata), the Milano value is used.

MERGE LOGIC (pixel-level):
  both valid → np.maximum(adbpo, milano)
  only milano valid → milano
  only adbpo valid → adbpo (no change needed)

EFFICIENCY: Instead of loading the entire ADB Po raster into memory, we:
  1. Copy the base (ADB Po) file to the output path with shutil.copy.
  2. Open the copy in update mode (r+) and overwrite only the Milano window
     using rasterio windowed I/O. The window is computed from Milano's bounds
     and the output raster's transform.

OUTPUT:
  <SERVER>/data/Altezza/adbpo_pgra2027_l_merged_milano_tr500_3035_5m.tif

NEXT STEP: run 10_adbpo_raster_to_db.py
"""

import logging
import shutil
import sys
import time
from pathlib import Path

import numpy as np
import rasterio
from rasterio.windows import from_bounds

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

# ── Paths ─────────────────────────────────────────────────────────────────────
ALTEZZA_ROOT = Path("/home/admin_climatecharted_com/data/Altezza")

ADBPO_PATH = ALTEZZA_ROOT / "adbpo_pgra2027_l_merged_3035_5m.tif"
MILANO_PATH = ALTEZZA_ROOT / "Milano_TR500_5m.tif"
OUT_PATH = ALTEZZA_ROOT / "adbpo_pgra2027_l_merged_milano_tr500_3035_5m.tif"

# ── 1. COPY BASE RASTER ───────────────────────────────────────────────────────
# shutil.copy copies the ADB Po raster byte-for-byte. We then open the copy
# in update mode (r+) so we can overwrite only the Milano window — much faster
# than re-reading and re-writing the whole raster.
t0 = time.time()
logging.info(f"Copying base raster → {OUT_PATH}")
shutil.copy(ADBPO_PATH, OUT_PATH)

# ── 2. WRITE MILANO WINDOW ────────────────────────────────────────────────────
with rasterio.open(OUT_PATH, "r+") as dst, rasterio.open(MILANO_PATH) as mil_src:

    # Read the full Milano raster into memory (small relative to ADB Po)
    mil_data = mil_src.read(1)
    mil_nodata = mil_src.nodata

    # from_bounds converts geographic bounds (left, bottom, right, top) to a
    # rasterio Window (row/column offsets and shape) relative to the dst grid.
    # round_offsets/round_lengths ensures pixel-perfect integer alignment.
    window = from_bounds(*mil_src.bounds, transform=dst.transform)
    window = window.round_offsets().round_lengths()
    logging.info(f"Milano window in ADB Po grid: {window}")

    # Windowed read: load only the ADB Po pixels that correspond to Milano's extent
    adb_data = dst.read(1, window=window)
    adb_nodata = dst.nodata

    # Boolean masks for valid pixels
    adb_valid = adb_data != adb_nodata
    mil_valid = mil_data != mil_nodata

    out_data = adb_data.copy()

    # Where both are valid: keep the higher depth (conservative/worst-case)
    both_valid = adb_valid & mil_valid
    out_data[both_valid] = np.maximum(adb_data[both_valid], mil_data[both_valid])

    # Where only Milano has data: use Milano
    only_mil = (~adb_valid) & mil_valid
    out_data[only_mil] = mil_data[only_mil]

    # Write only the Milano window into the output file (the rest is already correct)
    dst.write(out_data, 1, window=window)

logging.info(f"Done in {time.time() - t0:.1f}s → {OUT_PATH}")
