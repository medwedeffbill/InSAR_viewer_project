# InSAR Explorer — Data Pipeline

This directory contains the Python pipeline that processes raw Sentinel-1 InSAR
products into web-ready data assets.

## Setup

```bash
conda env create -f environment.yml
conda activate insar-pipeline
```

All steps below assume this environment is active. If you open a new terminal, run
`conda activate insar-pipeline` again before running pipeline scripts.

## Step 1 — Download from HyP3

Requires a free [NASA Earthdata account](https://urs.earthdata.nasa.gov/) with
[HyP3 access](https://hyp3-api.asf.alaska.edu/).

Add your credentials to `~/.netrc`:
```
machine urs.earthdata.nasa.gov
login YOUR_USERNAME
password YOUR_PASSWORD
```

Then download an AOI:
```bash
python download_hyp3.py \
    --config config/seattle.yml \
    --output-dir data/seattle/hyp3
```

## Step 2 — MintPy time series

```bash
python run_mintpy.py \
    --config    config/seattle.yml \
    --hyp3-dir  data/seattle/hyp3 \
    --work-dir  data/seattle/mintpy
```

Expected outputs in `data/seattle/mintpy/`:
- `timeseries.h5`
- `velocity.h5`
- `temporalCoherence.h5`

## Step 3 — ML anomaly detection

```bash
python anomaly_detection.py \
    --mintpy-dir data/seattle/mintpy \
    --output-dir data/seattle/export \
    --config     config/seattle.yml
```

Outputs: `anomaly_score.npy`, `labels.json`, `meta.json`

## Step 4 — Export to web formats

```bash
python export_cogs.py \
    --mintpy-dir data/seattle/mintpy \
    --ml-dir     data/seattle/export \
    --output-dir data/seattle/web \
    --config     config/seattle.yml
```

Outputs in `data/seattle/web/`:
- `velocity_mm_yr.tif` — Cloud Optimized GeoTIFF
- `coherence_mean.tif`
- `anomaly_score.tif`
- `seasonal_amplitude.tif`
- `timeseries.zarr/` — Zarr store for browser pixel lookup
- `ts_tiles/` — Chunked JSON tiles
- `aoi_metadata.json`

## Step 5 — Generate map tiles

```bash
python generate_tiles.py \
    --cog-dir    data/seattle/web \
    --output-dir tiles \
    --aoi-id     seattle \
    --zoom-min   6 \
    --zoom-max   13
```

## Step 6 — Upload to Cloudflare R2

Copy `.env.example` to `.env` and fill in your R2 credentials.

```bash
python upload_r2.py \
    --aoi-id    seattle \
    --web-dir   data/seattle/web \
    --tiles-dir tiles
```

Then configure CORS on your R2 bucket (dashboard → Settings → CORS):
```json
[
  {
    "AllowedOrigins": ["https://your-vercel-app.vercel.app", "https://yoursite.com"],
    "AllowedMethods": ["GET", "HEAD"],
    "AllowedHeaders": ["*"],
    "ExposeHeaders": ["Content-Range", "Accept-Ranges"],
    "MaxAgeSeconds": 3600
  }
]
```

## Running all AOIs

```bash
for AOI in seattle mt_rainier portuguese_bend; do
    python download_hyp3.py --config config/${AOI}.yml --output-dir data/${AOI}/hyp3
    python run_mintpy.py    --config config/${AOI}.yml --hyp3-dir data/${AOI}/hyp3 --work-dir data/${AOI}/mintpy
    python anomaly_detection.py --mintpy-dir data/${AOI}/mintpy --output-dir data/${AOI}/export --config config/${AOI}.yml
    python export_cogs.py   --mintpy-dir data/${AOI}/mintpy --ml-dir data/${AOI}/export --output-dir data/${AOI}/web --config config/${AOI}.yml
    python generate_tiles.py --cog-dir data/${AOI}/web --output-dir tiles --aoi-id ${AOI}
    python upload_r2.py     --aoi-id ${AOI} --web-dir data/${AOI}/web --tiles-dir tiles
done
```
