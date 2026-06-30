#!/usr/bin/env bash
# =============================================================================
# Flood Hazard Map Pipeline — Orchestration Script
# =============================================================================
#
# Run this script on the Linux server (paths inside 01–07 scripts are set for
# the server by default; adjust DATA_ROOT in each script for local Windows use).
#
# EXECUTION ORDER — run steps in sequence; each script depends on its predecessor.
#
#   Step 1  ADB Po basin: dissolve + H>M>L overlay (preserves sourceoffl)
#   Step 2  ADB AM: topological dissolve by RP
#   Step 3  ADB AS: topological dissolve by RP
#   Step 4  ADB AO: Tiranti H>M>L overlay (server only — raw files not local)
#   Step 5  ISPRA: national mosaic H>M>L overlay (server only)
#   Step 6  ISPRA → SI / SA / AC district clip (server only)
#   Step 7  Final merge → ispra_adb_20260630.shp  ← main deliverable
#
# Steps 4, 5, 6 only need to be re-run if the source data changes; their
# outputs already exist on local disk.
#
# USAGE:
#   source "$HOME/miniforge3/etc/profile.d/conda.sh"
#   conda activate ccpy4
#   bash run.sh
# =============================================================================

set -euo pipefail

source "$HOME/miniforge3/etc/profile.d/conda.sh"
conda activate ccpy4

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# -- Step 1: ADB Po -----------------------------------------------------------
echo "[$(date '+%H:%M:%S')] Step 1 — ADB Po overlay (with sourceoffl)"
python 01_adb_po_overlay.py

# -- Step 2: ADB AM -----------------------------------------------------------
echo "[$(date '+%H:%M:%S')] Step 2 — ADB AM dissolve"
python 02_adb_am_overlay.py

# -- Step 3: ADB AS -----------------------------------------------------------
echo "[$(date '+%H:%M:%S')] Step 3 — ADB AS dissolve"
python 03_adb_as_overlay.py

# -- Step 4: ADB AO (server only) ---------------------------------------------
# Uncomment to reprocess from raw Tiranti files on server.
# echo "[$(date '+%H:%M:%S')] Step 4 — ADB AO overlay"
# python 04_adb_ao_overlay.py

# -- Step 5: ISPRA overlay (server only) --------------------------------------
# Uncomment to reprocess from raw ISPRA premerge files on server.
# echo "[$(date '+%H:%M:%S')] Step 5 — ISPRA overlay"
# python 05_ispra_overlay.py

# -- Step 6: ISPRA → SI/SA/AC (server only) -----------------------------------
# Uncomment to reprocess ISPRA district clips on server.
# echo "[$(date '+%H:%M:%S')] Step 6 — ISPRA district clip"
# python 06_ispra_adb_si_sa_ac.py

# -- Step 7: Final merge → ispra_adb_20260630.shp ----------------------------
echo "[$(date '+%H:%M:%S')] Step 7 — Final merge"
python 07_merge_all.py

echo "[$(date '+%H:%M:%S')] Pipeline complete."
