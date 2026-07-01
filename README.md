# Flood Hazard Map Processing

Scripts to merge Italian flood hazard vector layers from ISPRA and multiple ADB districts into a single national hazard map, plus a raster pipeline for ADB Po water depth.

---

## Repository structure

```
utils.py                      Shared spatial functions (dissolve, overlay, geometry repair)

── Vector pipeline (01–07) ─────────────────────────────────────────
01_adb_po_overlay.py          ADB Po: dissolve + H>M>L overlay, preserves sourceoffl
02_adb_am_overlay.py          ADB Alto Adriatico/Alpi Marittime: dissolve by RP
03_adb_as_overlay.py          ADB Alpi Settentrionali: dissolve by RP
04_adb_ao_overlay.py          ADB Appennino Occidentale (Tiranti): H>M>L overlay
05_ispra_overlay.py           ISPRA national mosaic: fast H>M>L overlay (server only)
06_ispra_adb_si_sa_ac.py      Clip ISPRA to SI/SA/AC district boundaries (server only)
07_merge_all.py               Final merge → ispra_adb_20260630.shp  ← main output

── Raster pipeline (08–10) ─────────────────────────────────────────
08_adbpo_raster_reproject.py  Reproject ADB Po PGRA 2027 depth tiles → EPSG:3035 5m
09_adbpo_raster_merge_milano.py  Integrate Milano TR500 depth raster (windowed max)
10_adbpo_raster_to_db.py     Upload depth raster to PostGIS (raster2pgsql)

── Bash helpers ─────────────────────────────────────────────────────
run.sh                        Orchestration: runs steps 01–07 in sequence
load_raster.sh                Single-pass raster2pgsql load (alternative to step 10)
load_raster_chuncks.sh        Chunked raster2pgsql load with retry (for >4 GB rasters)
```

---

## Execution sequence

### Vector pipeline — build `ispra_adb_20260630.shp`

Steps 04, 05, 06 are **server only** (their outputs already exist locally). Steps 01–03 and 07 run on Windows from the local data.

```bash
# Steps 01–03 can be run in any order (independent)
python 01_adb_po_overlay.py     # ~30 min — large dissolve
python 02_adb_am_overlay.py     # ~5 min
python 03_adb_as_overlay.py     # ~5 min

# Step 07 uses outputs of 01–03 + pre-built outputs of 04/05/06
python 07_merge_all.py          # ~2 min
```

Or use `run.sh` on the server to run everything in sequence.
{ time ./run.sh; }

### Raster pipeline — build depth GeoTIFF

Run on server only (raw tiles are server-side).

```bash
python 08_adbpo_raster_reproject.py    # reproject + mosaic tiles
python 09_adbpo_raster_merge_milano.py # overlay Milano raster
python 10_adbpo_raster_to_db.py       # load to PostGIS
```

---

## Data sources

### ISPRA national mosaic (2020)
Three hazard classes at national scale:

| Code | Probability | Nominal RP |
|------|-------------|-----------|
| H | High | ~20–50 yr |
| M | Medium | ~100–200 yr |
| L | Low | ~200–500 yr |

Used directly for SI (Sicilia), SA (Sardegna), AC (Appennino Centrale) districts.

### ADB district hazard plans

| Script | District | Source |
|--------|----------|--------|
| `01` | ADB Po | `adb_po_2026_{H,M,L}_sorted_cum_prob_RP_clean.shp` |
| `02` | ADB Alto Adriatico / Alpi Marittime | `ADB-AM_2026_merge_cum_prob_RP.shp` |
| `03` | ADB Alpi Settentrionali | `PIANIFICAZIONE_SIT_PGRA_ITC_FLUVIAL_cum_prob_RP.shp` |
| `04` | ADB Appennino Occidentale | Tiranti TR30/100/300 premerge shapefiles |
| `06` | ADB Sicilia / Sardegna / App. Centrale | ISPRA national mosaic clipped to boundaries |

### Watercourse datasets (Corpi_Idrici)

Named river line datasets used to assign the `watercourse` column.
Copy the `Corpi_Idrici/` folder into `DATA_ROOT` before running step 07.

| Subfolder | Dataset | Name column | Coverage |
|-----------|---------|-------------|----------|
| `Reticolo_Idrografico/` | `Elementi_Idrici.shp` | `toponimo` | Po basin (national network) |
| `REGIONE PIEMONTE .../` | `Tratti_idrici_Piemonte.shp` | `NOMINU10` | Full Piemonte |
| `REGIONE_LOMBARDIA/` | `Corsi_acqua_AIPO.shp` | `NOME` | Main managed rivers (Lombardia) |
| `REGIONE_LOMBARDIA/` | `Tratti_idrici_Lombardia.shp` | `NOME` | Full Lombardia |
| `REGIONE VENETO .../` | `Tratti_idrici_Veneto.shp` | `NOME_CI` | Full Veneto |

Not used: `Tratti_Idrici/Tratti_Idrici.shp` (641k lines, no river names in schema),
`Corsi_acqua_RIB.shp` (drainage/irrigation canals, not flood-source rivers).
Southern Italy (SI, SA, AC) has no watercourse data available — `watercourse` will be NULL.

### ADB Po depth rasters (PGRA 2027)
Flood water-depth tiles for the TR500 (low-probability) scenario.
Produced by the raster pipeline (steps 08–10).

---

## Output schema

### `ispra_adb_20260630.shp`

| Column | Type | Description |
|--------|------|-------------|
| `rp` | float | Return period in years (1–500) |
| `adb` | str | District code: PO, AM, AS, AO, SI, SA, AC |
| `sourceoffl` | str | Flood source (PO only; fluvial / seaWater / pluvial / …; NULL for other ADBs) |
| `watercourse`\* | str | Name of the associated watercourse; NULL where not determinable |
| `geometry` | Polygon | EPSG:3035 |

\* Saved as `watercours` in .shp files (10-character shapefile column name limit); full name in .gpkg.

**Watercourse assignment (two-tier)**:
1. **ADB Po — attribute-based (exact)**: each ADB Po source shapefile carries a `nomeelidr` column
   (EU Flood Directive field `nomeElementoIdrografico`) with the official hydrographic element name,
   e.g. `"Fiume Taro"`, `"Lago di Garda"`, `"Mare Adriatico"`. This is carried through the dissolve
   and overlay in step 01, then used directly in step 07. No spatial proximity involved.
2. **Other ADBs — spatial proximity (best-effort)**: for districts without embedded river names,
   a nearest-neighbour join (`sjoin_nearest`) against the Corpi_Idrici line datasets assigns the
   closest named river within 2 km. Coverage is limited to the datasets available (Po basin,
   Piemonte, Lombardia, Veneto); other districts may receive NULL.

New in this version vs `ispra_adb_20260414.shp`: `sourceoffl` and `watercourse` columns added.

---

## Core algorithms

### Graph-based topological dissolve (`dissolve_touching_by_rp` in `utils.py`)

Source shapefiles split flood zones into small tiles per administrative unit.
Adjacent tiles representing the same flood zone must be merged before the
hierarchical overlay step.

1. Build an R-tree spatial index (`gdf.sindex`) for fast bounding-box lookup.
2. For each polygon, retrieve candidates from the index and test actual topology
   (touches or intersects).
3. Build a NetworkX graph: polygons are nodes, adjacent pairs are edges.
4. Find connected components; merge each component with `union_all()`.

### H > M > L hierarchical overlay (`hierarchical_overlay` in `utils.py`)

Where hazard classes overlap spatially, the highest-probability class (H) takes
precedence. `gpd.overlay(M, H_mask, how='difference')` removes from M every
area already covered by H. The same is applied to L against H+M.

### Milano raster merge (step 09)

For pixels where both ADB Po and Milano have valid data, `np.maximum()` keeps
the higher depth value. For pixels where only Milano has data (ADB Po nodata),
the Milano value is used. Written back using windowed I/O to avoid loading the
full large base raster into memory.

---

## Environment

```
conda activate ccpy4
```

Key dependencies: `geopandas`, `shapely`, `networkx`, `pandas`, `rasterio`,
`osgeo (gdal)`, `numpy`, `tqdm`, `sqlalchemy`.

Data root (Windows local): `D:\data\HZRD_Flood\adb_2026\`

Data root (Linux server): `/home/admin_climatecharted_com/data/`
