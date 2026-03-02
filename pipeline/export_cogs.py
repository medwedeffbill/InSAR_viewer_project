"""
Export MintPy outputs + ML results to web-ready formats.

Produces
--------
  {output_dir}/
    velocity_mm_yr.tif          COG — linear LOS velocity
    coherence_mean.tif          COG — mean temporal coherence
    anomaly_score.tif           COG — ML anomaly score [0,1]
    seasonal_amplitude.tif      COG — seasonal peak-to-peak amplitude
    timeseries.zarr/            Zarr store — (T, rows, cols) displacement mm
    ts_tiles/{r}_{c}.json       Chunked pixel time series (32×32 tiles)
    aoi_metadata.json           AOI manifest for the frontend

Usage
-----
  python export_cogs.py \\
      --mintpy-dir  data/seattle/mintpy \\
      --ml-dir      data/seattle/export \\
      --output-dir  data/seattle/web \\
      --config      config/seattle.yml
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import click
import h5py
import numpy as np
import rasterio
import yaml
import zarr
from rasterio.crs import CRS
from rasterio.transform import from_bounds, Affine
from rio_cogeo.cogeo import cog_translate
from rio_cogeo.profiles import cog_profiles
import tempfile

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def load_config(p: Path) -> dict:
    with open(p) as f:
        return yaml.safe_load(f)


def mintpy_attrs_to_transform(attrs: dict) -> tuple[Affine, CRS, tuple]:
    """Convert MintPy HDF5 attributes to rasterio transform + CRS."""
    x0   = float(attrs.get("X_FIRST", 0))
    y0   = float(attrs.get("Y_FIRST", 0))
    dx   = float(attrs.get("X_STEP",  0.0001))
    dy   = float(attrs.get("Y_STEP", -0.0001))
    rows = int(attrs.get("LENGTH", 0))
    cols = int(attrs.get("WIDTH",  0))

    transform = Affine(dx, 0.0, x0, 0.0, dy, y0)
    crs = CRS.from_epsg(4326)

    west  = x0
    north = y0
    east  = x0 + dx * cols
    south = y0 + dy * rows
    bbox  = (west, south, east, north)

    return transform, crs, bbox


def write_cog(data: np.ndarray, transform: Affine, crs: CRS, out_path: Path, nodata: float = np.nan) -> None:
    """Write a 2-D float32 array as a Cloud Optimized GeoTIFF."""
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(suffix=".tif", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    rows, cols = data.shape
    with rasterio.open(
        tmp_path,
        "w",
        driver="GTiff",
        height=rows,
        width=cols,
        count=1,
        dtype="float32",
        crs=crs,
        transform=transform,
        nodata=nodata,
    ) as dst:
        dst.write(data.astype(np.float32), 1)

    cog_translate(
        str(tmp_path),
        str(out_path),
        cog_profiles.get("deflate"),
        in_memory=False,
        quiet=True,
    )
    tmp_path.unlink()
    log.info("  COG written: %s  (shape=%s)", out_path.name, data.shape)


# ──────────────────────────────────────────────────────────────────────────────
# MintPy → COG conversion
# ──────────────────────────────────────────────────────────────────────────────

def export_velocity(mintpy_dir: Path, output_dir: Path) -> tuple[Affine, CRS, tuple]:
    """Export velocity.h5 → velocity_mm_yr.tif COG."""
    with h5py.File(mintpy_dir / "velocity.h5", "r") as hf:
        velocity = hf["velocity"][:] * 1000.0    # m/yr → mm/yr
        attrs = dict(hf.attrs)

    transform, crs, bbox = mintpy_attrs_to_transform(attrs)
    write_cog(velocity, transform, crs, output_dir / "velocity_mm_yr.tif")
    return transform, crs, bbox


def export_coherence(mintpy_dir: Path, output_dir: Path, transform: Affine, crs: CRS) -> None:
    """Export temporalCoherence.h5 → coherence_mean.tif COG."""
    with h5py.File(mintpy_dir / "temporalCoherence.h5", "r") as hf:
        coh = hf["temporalCoherence"][:]
    write_cog(coh, transform, crs, output_dir / "coherence_mean.tif")


def export_anomaly_score(ml_dir: Path, output_dir: Path, transform: Affine, crs: CRS) -> None:
    """Export ML anomaly_score.npy → anomaly_score.tif COG."""
    score = np.load(ml_dir / "anomaly_score.npy")
    write_cog(score, transform, crs, output_dir / "anomaly_score.tif")


def export_seasonal_amplitude(mintpy_dir: Path, output_dir: Path, transform: Affine, crs: CRS) -> None:
    """
    Compute seasonal amplitude from timeseries.h5 and export as COG.
    We fit a sin+cos model to each pixel to extract the annual amplitude.
    """
    with h5py.File(mintpy_dir / "timeseries.h5", "r") as hf:
        ts    = hf["timeseries"][:] * 1000.0   # m → mm,  shape (T, rows, cols)
        dates = [d.decode() for d in hf["date"][:]]

    from datetime import datetime

    # Days since first acquisition → decimal year
    t0 = datetime.strptime(dates[0], "%Y%m%d")
    t_days = np.array([(datetime.strptime(d, "%Y%m%d") - t0).days for d in dates], dtype=float)
    t_yr   = t_days / 365.25
    omega  = 2 * np.pi          # 1 cycle / year

    T, rows, cols = ts.shape
    A  = np.column_stack([np.cos(omega * t_yr), np.sin(omega * t_yr), np.ones(T)])  # design matrix

    # Reshape ts to (T, N) for batch least-squares
    ts_flat = ts.reshape(T, -1)
    valid   = ~np.any(np.isnan(ts_flat), axis=0)

    coeffs = np.zeros((3, rows * cols), dtype=np.float32)
    if valid.any():
        coeffs[:, valid] = np.linalg.lstsq(A, ts_flat[:, valid], rcond=None)[0]

    amp = np.sqrt(coeffs[0] ** 2 + coeffs[1] ** 2) * 2.0   # peak-to-peak
    amp = amp.reshape(rows, cols).astype(np.float32)

    write_cog(amp, transform, crs, output_dir / "seasonal_amplitude.tif")


# ──────────────────────────────────────────────────────────────────────────────
# Zarr time series store
# ──────────────────────────────────────────────────────────────────────────────

def export_zarr_timeseries(mintpy_dir: Path, output_dir: Path, transform: Affine, bbox: tuple) -> None:
    """
    Write displacement time series as a Zarr store for browser-side access.

    Store layout
    ------------
    timeseries.zarr/
      displacement/   (T, rows, cols)  float32  mm
      dates/          (T,)             <U8
      .zattrs         → geotransform, bbox, crs
    """
    zarr_path = output_dir / "timeseries.zarr"

    with h5py.File(mintpy_dir / "timeseries.h5", "r") as hf:
        ts    = (hf["timeseries"][:] * 1000.0).astype(np.float32)   # mm
        dates = np.array([d.decode() for d in hf["date"][:]])

    T, rows, cols = ts.shape

    store = zarr.DirectoryStore(str(zarr_path))
    root  = zarr.group(store, overwrite=True)

    # Chunk: full time series for 32×32 spatial tiles
    root.create_dataset(
        "displacement",
        data=ts,
        chunks=(T, min(32, rows), min(32, cols)),
        dtype="float32",
        compressor=zarr.Blosc(cname="zstd", clevel=5, shuffle=zarr.Blosc.BITSHUFFLE),
    )
    root.create_dataset("dates", data=dates.astype("U8"), dtype=str)

    x0, dx = float(transform.c), float(transform.a)
    y0, dy = float(transform.f), float(transform.e)

    root.attrs.update(
        {
            "transform": [x0, dx, 0.0, y0, 0.0, dy],
            "bbox": list(bbox),
            "crs": "EPSG:4326",
            "shape": {"T": T, "rows": rows, "cols": cols},
            "units": "mm",
        }
    )

    log.info("  Zarr store written: %s  shape=(%d, %d, %d)", zarr_path, T, rows, cols)


# ──────────────────────────────────────────────────────────────────────────────
# Chunked pixel time series JSON tiles
# ──────────────────────────────────────────────────────────────────────────────

def export_ts_tile_json(mintpy_dir: Path, ml_dir: Path, output_dir: Path, tile_size: int = 32) -> None:
    """
    Write spatial tile JSON files for browser-side pixel lookup.

    Each tile covers tile_size × tile_size pixels.
    File: ts_tiles/{tile_row}_{tile_col}.json
    Content: { "pixels": { "r_c": { "d": [...mm], "trend": [...], "seasonal": [...], "residual": [...] } } }
    """
    from statsmodels.tsa.seasonal import STL

    with h5py.File(mintpy_dir / "timeseries.h5", "r") as hf:
        ts    = (hf["timeseries"][:] * 1000.0).astype(np.float32)
        dates = [d.decode() for d in hf["date"][:]]

    with h5py.File(mintpy_dir / "temporalCoherence.h5", "r") as hf:
        coh = hf["temporalCoherence"][:]

    labels_path = ml_dir / "labels.json"
    labels_dict = {}
    if labels_path.exists():
        with open(labels_path) as f:
            labels_dict = json.load(f)

    T, rows, cols = ts.shape
    tiles_dir = output_dir / "ts_tiles"
    tiles_dir.mkdir(parents=True, exist_ok=True)

    n_tile_rows = (rows + tile_size - 1) // tile_size
    n_tile_cols = (cols + tile_size - 1) // tile_size
    total_tiles = n_tile_rows * n_tile_cols

    log.info("Writing %d tile JSON files (%d×%d tiles of %d×%d px) ...", total_tiles, n_tile_rows, n_tile_cols, tile_size, tile_size)

    from tqdm import tqdm as _tqdm

    for tr in _tqdm(range(n_tile_rows), desc="Tile rows"):
        for tc in range(n_tile_cols):
            r0 = tr * tile_size
            c0 = tc * tile_size
            r1 = min(r0 + tile_size, rows)
            c1 = min(c0 + tile_size, cols)

            pixels: dict = {}
            for r in range(r0, r1):
                for c in range(c0, c1):
                    if coh[r, c] < 0.3:
                        continue   # skip incoherent pixels

                    series = ts[:, r, c].tolist()
                    key = f"{r}_{c}"

                    # Fast STL decomposition
                    try:
                        arr = np.array(series, dtype=float)
                        valid = ~np.isnan(arr)
                        if valid.sum() >= 6:
                            if not valid.all():
                                x = np.arange(T)
                                arr = np.interp(x, x[valid], arr[valid])
                            stl_res = STL(arr, period=12, robust=True).fit()
                            decomp = {
                                "trend":    [round(v, 2) for v in stl_res.trend.tolist()],
                                "seasonal": [round(v, 2) for v in stl_res.seasonal.tolist()],
                                "residual": [round(v, 2) for v in stl_res.resid.tolist()],
                            }
                        else:
                            decomp = {}
                    except Exception:
                        decomp = {}

                    pixel_data: dict = {"d": [round(v, 2) if not np.isnan(v) else None for v in series]}
                    pixel_data.update(decomp)

                    if key in labels_dict:
                        pixel_data["anomaly"] = labels_dict[key]

                    pixels[f"{r - r0}_{c - c0}"] = pixel_data   # relative coords within tile

            if pixels:
                tile_path = tiles_dir / f"{tr}_{tc}.json"
                with open(tile_path, "w") as f:
                    json.dump({"tile_row": tr, "tile_col": tc, "r0": r0, "c0": c0, "pixels": pixels, "dates": dates}, f, separators=(",", ":"))

    log.info("Tile JSON export complete.")


# ──────────────────────────────────────────────────────────────────────────────
# AOI manifest
# ──────────────────────────────────────────────────────────────────────────────

def write_aoi_metadata(cfg: dict, output_dir: Path, bbox: tuple, dates: list[str]) -> None:
    """Write aoi_metadata.json consumed by the frontend on startup."""
    west, south, east, north = bbox

    meta = {
        "id":          cfg["id"],
        "name":        cfg["name"],
        "description": cfg["description"].strip(),
        "bbox":        list(bbox),
        "center":      cfg.get("center", [(west + east) / 2, (south + north) / 2]),
        "zoom":        cfg.get("zoom", 10),
        "featured":    cfg.get("featured", False),
        "case_study":  cfg.get("case_study", None),
        "date_range":  [dates[0], dates[-1]] if dates else [],
        "layers": [
            {"id": "velocity",           "name": "LOS Velocity",          "unit": "mm/yr",   "vmin": cfg["display"]["vmin"],  "vmax": cfg["display"]["vmax"],  "colorscale": cfg["display"]["colorscale"]},
            {"id": "coherence",          "name": "Mean Coherence",        "unit": "",        "vmin": 0,    "vmax": 1,    "colorscale": "Greys"},
            {"id": "anomaly_score",      "name": "Anomaly Score",         "unit": "",        "vmin": 0,    "vmax": 1,    "colorscale": "YlOrRd"},
            {"id": "seasonal_amplitude", "name": "Seasonal Amplitude",    "unit": "mm",      "vmin": 0,    "vmax": 20,   "colorscale": "viridis"},
        ],
    }

    out_path = output_dir / "aoi_metadata.json"
    with open(out_path, "w") as f:
        json.dump(meta, f, indent=2)
    log.info("  AOI metadata written: %s", out_path)


# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────

@click.command()
@click.option("--mintpy-dir",  required=True, type=click.Path(exists=True, path_type=Path))
@click.option("--ml-dir",      required=True, type=click.Path(exists=True, path_type=Path))
@click.option("--output-dir",  required=True, type=click.Path(path_type=Path))
@click.option("--config",      required=True, type=click.Path(exists=True, path_type=Path))
@click.option("--tile-size",   default=32, show_default=True, help="Pixel tile size for JSON tile export")
@click.option("--skip-zarr",   is_flag=True, default=False, help="Skip Zarr export (faster for testing)")
@click.option("--skip-tiles",  is_flag=True, default=False, help="Skip tile JSON export")
def main(
    mintpy_dir: Path,
    ml_dir: Path,
    output_dir: Path,
    config: Path,
    tile_size: int,
    skip_zarr: bool,
    skip_tiles: bool,
) -> None:
    """Export MintPy + ML outputs to COGs, Zarr, and tile JSON for web serving."""
    cfg = load_config(config)
    output_dir.mkdir(parents=True, exist_ok=True)

    log.info("=== Exporting COGs ===")
    transform, crs, bbox = export_velocity(mintpy_dir, output_dir)
    export_coherence(mintpy_dir, output_dir, transform, crs)
    export_anomaly_score(ml_dir, output_dir, transform, crs)
    export_seasonal_amplitude(mintpy_dir, output_dir, transform, crs)

    if not skip_zarr:
        log.info("=== Exporting Zarr time series ===")
        export_zarr_timeseries(mintpy_dir, output_dir, transform, bbox)

    if not skip_tiles:
        log.info("=== Exporting tile JSON ===")
        export_ts_tile_json(mintpy_dir, ml_dir, output_dir, tile_size=tile_size)

    log.info("=== Writing AOI metadata ===")
    with h5py.File(mintpy_dir / "timeseries.h5", "r") as hf:
        dates = [d.decode() for d in hf["date"][:]]
    write_aoi_metadata(cfg, output_dir, bbox, dates)

    log.info("Export complete → %s", output_dir)


if __name__ == "__main__":
    main()
