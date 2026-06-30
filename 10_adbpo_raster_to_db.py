"""
STEP 10 — Upload ADB Po depth raster to PostGIS

USAGE (server only — requires psql and raster2pgsql CLI tools):
  conda activate ccpy4
  export PGHOST_WEBGIS=<host>
  export PGDB_WEBGIS=<dbname>
  export PGUSER_WEBGIS=<user>
  export PGPASSWORD_WEBGIS=<password>
  export PGPORT_WEBGIS=<port>
  python 10_adbpo_raster_to_db.py

INPUT:
  <SERVER>/data/Altezza/adbpo_pgra2027_l_merged_milano_tr500_3035_5m.tif (from step 09)

HOW IT WORKS:
  raster2pgsql is the PostGIS CLI tool that converts a GeoTIFF to SQL INSERT
  statements (one per tile). It is piped directly to psql, so the raster is
  loaded in one pass without writing an intermediate SQL file.

  Flags used:
    -s <EPSG>  set the spatial reference
    -I         create a GiST spatial index (for fast spatial queries)
    -C         add raster constraints (valid metadata for ST_* functions)
    -M         VACUUM ANALYZE the table after loading
    -t <size>  tile size: each raster row in the DB covers 128×128 pixels

  subprocess.run executes the piped command in a shell. The PGPASSWORD
  environment variable is set per-run so it is never written to disk.
"""

import logging
import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, text

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

# ── Config ────────────────────────────────────────────────────────────────────
RASTER_FILE = "/home/admin_climatecharted_com/data/Altezza/adbpo_pgra2027_l_merged_milano_tr500_3035_5m.tif"
TABLE_NAME = "adbpo_pgra2027_l_merged_milano_tr500_3035_5m"
EPSG = 3035
TILE_SIZE = "128x128"

# DB credentials are read from environment variables — never hardcoded.
# Set PGHOST_WEBGIS, PGDB_WEBGIS, PGUSER_WEBGIS, PGPASSWORD_WEBGIS, PGPORT_WEBGIS
# before running (or fall back to the unqualified PGHOST etc. if set).
DB_ENVS = ["WEBGIS"]


def upload_raster(raster_file, table_name, db_envs, epsg, tile_size="128x128"):
    if not Path(raster_file).is_file():
        raise FileNotFoundError(f"Raster not found: {raster_file}")

    for env in db_envs:
        host = os.getenv(f"PGHOST_{env}") or os.getenv("PGHOST")
        db   = os.getenv(f"PGDB_{env}")   or os.getenv("PGDB")
        user = os.getenv(f"PGUSER_{env}") or os.getenv("PGUSER")
        pw   = os.getenv(f"PGPASSWORD_{env}") or os.getenv("PGPASSWORD")
        port = os.getenv(f"PGPORT_{env}") or os.getenv("PGPORT")

        logging.info(f"Connecting to {env}: {db}@{host}:{port}")

        # Verify the DB is reachable and PostGIS is installed before loading data
        engine = create_engine(f"postgresql://{user}:{pw}@{host}:{port}/{db}")
        with engine.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis;"))
            version = conn.execute(text("SELECT postgis_version();")).fetchone()
            logging.info(f"PostGIS version: {version[0]}")

        # raster2pgsql | psql: stream SQL directly into the database
        cmd = (
            f'raster2pgsql -s {epsg} -I -C -M "{raster_file}" '
            f'-t {tile_size} public.{table_name} | '
            f'psql -d {db} -U {user} -h {host} -p {port}'
        )
        env_vars = {**os.environ, "PGPASSWORD": pw}
        logging.info(f"Uploading {table_name} to {env}")
        result = subprocess.run(cmd, shell=True, env=env_vars, capture_output=True, text=True)

        if result.returncode == 0:
            logging.info(f"Upload complete: {table_name} → {db}")
        else:
            logging.error(f"Upload failed: {result.stderr}")


# ── Run ───────────────────────────────────────────────────────────────────────
upload_raster(
    raster_file=RASTER_FILE,
    table_name=TABLE_NAME,
    db_envs=DB_ENVS,
    epsg=EPSG,
    tile_size=TILE_SIZE,
)
