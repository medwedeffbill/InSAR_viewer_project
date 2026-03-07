# InSAR Deformation Explorer

A public, map-first web app for exploring ground deformation from Sentinel-1 InSAR time series,
with ML-based anomaly detection to surface unusual displacement signals.

**Live demo:** _https://insar.yoursite.com_ (update once deployed)

---

## What it does

| Feature | Description |
|---------|-------------|
| Interactive map | Dark-themed MapLibre GL basemap with togglable raster layers |
| LOS velocity | Mean line-of-sight displacement rate (mm/yr) from SBAS inversion |
| Anomaly score | Per-pixel Isolation Forest score highlighting unusual behaviour |
| Pixel inspector | Click any pixel → time series plot + STL decomposition + "why flagged?" |
| Seasonal analysis | Peak-to-peak annual amplitude layer |
| Export | One-click CSV download of any pixel's time series |
| Case studies | Three illustrated writeups with embedded maps |

---

## Quick Start

### Prerequisites

- **Python ≥ 3.11** (for the data pipeline) — recommend [Miniforge](https://github.com/conda-forge/miniforge)
- **Node.js ≥ 20** (for the frontend) — install via [nvm](https://github.com/nvm-sh/nvm):
  ```bash
  curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash
  # restart terminal, then:
  nvm install 20
  nvm use 20
  ```
- A free [NASA Earthdata account](https://urs.earthdata.nasa.gov/) for HyP3 data access
- A free [Cloudflare account](https://cloudflare.com) for R2 storage

### 1. Set up the pipeline

```bash
conda env create -f pipeline/environment.yml
conda activate insar-pipeline
```

See [pipeline/README.md](pipeline/README.md) for the full step-by-step processing workflow.

### 2. Run the frontend locally

```bash
cd frontend
cp .env.example .env        # fill in VITE_R2_BASE_URL
nvm use                      # uses .nvmrc → node 20
npm install
npm run dev                  # http://localhost:5173
```

> **Without R2 data:** The app works in demo mode — the Explorer loads the three featured AOIs
> with the correct extents and layer structure, but no raster tiles or time series are shown
> until you complete the pipeline and configure R2.

---

## Repository Structure

```
InSAR_viewer_project/
├── pipeline/               Python data pipeline
│   ├── environment.yml     Conda environment
│   ├── config/             Per-AOI YAML configs
│   │   ├── seattle.yml
│   │   ├── mt_rainier.yml
│   │   └── portuguese_bend.yml
│   ├── download_hyp3.py    HyP3 job submission + download
│   ├── run_mintpy.py       MintPy SBAS processing wrapper
│   ├── anomaly_detection.py  ML pipeline (STL + Isolation Forest + ruptures)
│   ├── export_cogs.py      COG + Zarr + tile JSON export
│   ├── generate_tiles.py   PNG tile generation (rio-tiler)
│   ├── upload_r2.py        Cloudflare R2 upload
│   └── README.md
│
├── frontend/               React web app
│   ├── src/
│   │   ├── components/     MapView, LeftPanel, RightPanel, TimeSeriesPlot, …
│   │   ├── pages/          Landing, Explorer, CaseStudy
│   │   ├── store/          Zustand state
│   │   ├── lib/            R2 client, color scales
│   │   ├── content/        Case study markdown content
│   │   └── types/          TypeScript interfaces
│   ├── vercel.json
│   └── package.json
│
├── .gitignore
└── README.md
```

---

## Deployment

### Cloudflare R2 (data)

1. Create a bucket named `insar-cogs` in the Cloudflare dashboard
2. Enable **Public Access** on the bucket
3. Optionally add a custom domain (e.g. `data.yoursite.com`)
4. Configure CORS (bucket Settings → CORS):
   ```json
   [{"AllowedOrigins":["*"],"AllowedMethods":["GET","HEAD"],"AllowedHeaders":["*"],"ExposeHeaders":["Content-Range"],"MaxAgeSeconds":3600}]
   ```
5. Run `python pipeline/upload_r2.py` after pipeline processing

### Vercel (frontend)

```bash
cd frontend
npm run build        # verify build succeeds locally first
# Then in Vercel dashboard:
#   1. Import this GitHub repo
#   2. Set root directory → frontend/
#   3. Add env var: VITE_R2_BASE_URL=https://your-r2-url
#   4. Deploy
```

Or via CLI:
```bash
npm i -g vercel
vercel --cwd frontend
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| SAR processing | ASF HyP3 (Sentinel-1 SBAS) |
| Time series | MintPy SBAS inversion |
| ML | Isolation Forest · STL decomposition · ruptures PELT |
| Raster export | rio-cogeo COGs · rio-tiler PNG tiles · Zarr time series |
| Storage | Cloudflare R2 (S3-compatible, zero egress fees) |
| Frontend map | MapLibre GL JS (open source, no API key) |
| Charts | Recharts |
| State | Zustand |
| Styling | Tailwind CSS |
| Hosting | Vercel (free tier) |

---

## Data Attribution

Contains modified Copernicus Sentinel data (ESA), processed by ASF / NASA JPL.
Sentinel-1 data accessed via [Alaska Satellite Facility](https://asf.alaska.edu/).
