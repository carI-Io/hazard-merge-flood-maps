"""
STEP 8 — ADB Po PGRA 2027: reproject depth tiles to EPSG:3035 @ 5 m + mosaic

USAGE (server only — raw depth tiles are only on the server):
  conda activate ccpy4
  python 08_adbpo_raster_reproject.py

INPUT:
  <SERVER>/data/Altezza/adb_po_pgra_2027_l/*.tif
  Raw flood depth raster tiles (metres) for the low-probability scenario (TR500)
  in the ADB Po PGRA 2027 plan. Each tile is one spatial section; they arrive
  in an arbitrary native CRS and resolution.

PROCESSING:
  1. Reproject each tile to EPSG:3035 at 5 m resolution (bilinear resampling).
  2. Build a GDAL Virtual Raster (VRT) from all reprojected tiles.
     A VRT is a lightweight XML file that references the source tiles — no data
     is copied. GDAL reads it as if it were a single raster.
  3. Translate the VRT to a single GeoTIFF. This is the step that actually
     reads all tiles and writes them into one file.

CHOICES:
  - bilinear resampling: interpolates the 4 nearest source pixels. Better than
    nearest-neighbour for continuous values like water depth.
  - float32 with nodata=-9999: preserves sub-metre depth precision; -9999 is
    safe outside the Int16 range and unambiguous as nodata.
  - DEFLATE + tiled + predictor=2: lossless compression. Predictor=2 (horizontal
    differencing) works well for floating-point continuous fields.
  - BIGTIFF=YES: required because the merged tile exceeds 4 GB.

OUTPUT:
  <SERVER>/data/Altezza/adbpo_pgra2027_l_merged_3035_5m.tif

NEXT STEP: run 09_adbpo_raster_merge_milano.py
"""

import logging
import sys
from pathlib import Path

from osgeo import gdal
import rasterio
from rasterio.warp import calculate_default_transform, reproject, Resampling

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

# ── Paths ─────────────────────────────────────────────────────────────────────
ALTEZZA_ROOT = Path("/home/admin_climatecharted_com/data/Altezza")

SRC_FOLDER = ALTEZZA_ROOT / "adb_po_pgra_2027_l"
DST_RES = 5  # metres — 5 m output resolution
DST_CRS = "EPSG:3035"

DST_FOLDER = ALTEZZA_ROOT / f"adb_po_pgra_2027_l_3035_{DST_RES}m"
VRT_PATH = ALTEZZA_ROOT / "adbpo_pgra2027_l_merged.vrt"
OUT_PATH = ALTEZZA_ROOT / f"adbpo_pgra2027_l_merged_3035_{DST_RES}m.tif"

# ── 1. REPROJECT TILES ────────────────────────────────────────────────────────
DST_FOLDER.mkdir(exist_ok=True)
tif_files = list(SRC_FOLDER.glob("*.tif"))
logging.info(f"Found {len(tif_files)} source tiles in {SRC_FOLDER}")

for idx, f in enumerate(tif_files, 1):
    out_file = DST_FOLDER / (f.stem + f"_3035_{DST_RES}m.tif")

    with rasterio.open(f) as src:
        # calculate_default_transform computes the output grid parameters
        # (transform, width, height) that best fit the source extent at the
        # target CRS and resolution, without distortion.
        transform, width, height = calculate_default_transform(
            src.crs, DST_CRS, src.width, src.height, *src.bounds, resolution=DST_RES
        )

        kwargs = src.meta.copy()
        kwargs.update({
            "crs": DST_CRS,
            "transform": transform,
            "width": width,
            "height": height,
            "dtype": "float32",
            "nodata": -9999.0,
            "compress": "DEFLATE",
            "tiled": True,
            "predictor": 2,
        })

        with rasterio.open(out_file, "w", **kwargs) as dst:
            for band in range(1, src.count + 1):
                # rasterio.warp.reproject: reads from src grid, reprojects to dst grid.
                # Bilinear uses a 2×2 weighted average — smooth for continuous depth values.
                reproject(
                    source=rasterio.band(src, band),
                    destination=rasterio.band(dst, band),
                    src_transform=src.transform,
                    src_crs=src.crs,
                    dst_transform=transform,
                    dst_crs=DST_CRS,
                    resampling=Resampling.bilinear,
                    src_nodata=src.nodata,
                    dst_nodata=kwargs["nodata"],
                )

    logging.info(f"[{idx}/{len(tif_files)}] {f.name} → {out_file.name}")

# ── 2. BUILD VRT ──────────────────────────────────────────────────────────────
# gdal.BuildVRT creates a virtual mosaic in an XML descriptor file.
# It reads the spatial extents of each tile and assembles a logical view
# of the full coverage — no pixel data is read or written here.
reprojected = list(DST_FOLDER.glob("*.tif"))
gdal.BuildVRT(str(VRT_PATH), [str(f) for f in reprojected])
logging.info(f"VRT built: {VRT_PATH} ({len(reprojected)} tiles)")

# ── 3. TRANSLATE VRT TO SINGLE GEOTIFF ───────────────────────────────────────
# gdal.Translate reads the VRT (which in turn reads the tiles) and writes
# everything to a single output GeoTIFF. This is the expensive step.
gdal.Translate(
    str(OUT_PATH),
    str(VRT_PATH),
    creationOptions=[
        "COMPRESS=DEFLATE",
        "BIGTIFF=YES",
        "TILED=YES",
        "PREDICTOR=2",
    ],
)
logging.info(f"Mosaic saved → {OUT_PATH}")
