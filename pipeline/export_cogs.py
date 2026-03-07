"""
Export MintPy outputs + ML results to web-ready formats.

Produces
--------
  {output_dir}/
    velocity_mm_yr.tif          COG — linear LOS velocity (EPSG:4326)
    coherence_mean.tif          COG — mean temporal coherence (EPSG:4326)
    anomaly_score.tif           COG — ML anomaly score [0,1] (EPSG:4326)
    seasonal_amplitude.tif      COG — seasonal peak-to-peak amplitude (EPSG:4326)
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
import tempfile
from pathlib import Path

import click
import h5py
import numpy as np
import rasterio
import yaml
import zarr
from pyproj import Transformer
from rasterio.crs import CRS
from rasterio.transform import Affine, array_bounds
from rasterio.warp import calculate_default_transform, reproject, Resampling
from rio_cogeo.cogeo import cog_translate
from rio_cogeo.profiles import cog_profiles

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

WGS84 = CRS.from_epsg(4326)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def load_config(p: Path) -> dict:
    with open(p) as f:
        return yaml.safe_load(f)


def mintpy_attrs_to_geo(attrs: dict) -> tuple[Affine, CRS, tuple[float, ...]]:
    """
    Parse MintPy HDF5 attributes and return:
        native_transform  – Affine in the dataset's native CRS (may be UTM)
        native_crs        – The native CRS read from the EPSG attribute
        wgs84_bbox        – (west, south, east, north) in WGS84 degrees

    MintPy stores X_FIRST/Y_FIRST in the native coordinate units (metres for
    UTM, degrees for geographic).  The old code assumed EPSG:4326 regardless,
    which caused a UTM-metre / degree unit mismatch that would have placed every
    output raster thousands of degrees off-map.
    """
    x0   = float(attrs.get("X_FIRST", 0))
    y0   = float(attrs.get("Y_FIRST", 0))
    dx   = float(attrs.get("X_STEP",  0.0001))
    dy   = float(attrs.get("Y_STEP", -0.0001))
    rows = int(attrs.get("LENGTH", 0))
    cols = int(attrs.get("WIDTH",  0))
    epsg = int(attrs.get("EPSG", 4326))

    native_transform = Affine(dx, 0.0, x0, 0.0, dy, y0)
    native_crs = CRS.from_epsg(epsg)

    # Compute the four corners in the native CRS, then convert to WGS84.
    # Transforming all four corners (not just two) handles cases where the
    # projection boundary curves relative to lat/lon.
    west  = x0
    north = y0
    east  = x0 + dx * cols
    south = y0 + dy * rows   # dy is negative → south < north

    if epsg != 4326:
        t = Transformer.from_crs(epsg, 4326, always_xy=True)
        lons, lats = t.transform(
            [west, west, east, east],
            [south, north, south, north],
        )
        wgs84_bbox: tuple[float, ...] = (min(lons), min(lats), max(lons), max(lats))
    else:
        wgs84_bbox = (west, south, east, north)

    return native_transform, native_crs, wgs84_bbox


def write_cog(
    data: np.ndarray,
    native_transform: Affine,
    native_crs: CRS,
    out_path: Path,
    nodata: float = np.nan,
) -> None:
    """
    Write a 2-D float32 array as a Cloud Optimized GeoTIFF in EPSG:4326.

    If the source data is in a projected CRS (e.g. UTM EPSG:32610), it is
    reprojected to WGS84 (EPSG:4326) before writing.  Storing all COGs in
    geographic coordinates means any web-mapping library can display them
    without special projection configuration.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    arr = data.astype(np.float32)
    rows, cols = arr.shape

    with tempfile.NamedTemporaryFile(suffix=".tif", delete=False) as tmp:
        reprojected_path = Path(tmp.name)

    if native_crs == WGS84:
        # Already geographic — write directly to the reprojection target path.
        with rasterio.open(
            reprojected_path, "w", driver="GTiff",
            height=rows, width=cols, count=1, dtype="float32",
            crs=native_crs, transform=native_transform, nodata=nodata,
        ) as dst:
            dst.write(arr, 1)
    else:
        # Compute the optimal WGS84 transform that preserves native resolution.
        left, bottom, right, top = array_bounds(rows, cols, native_transform)
        dst_transform, dst_width, dst_height = calculate_default_transform(
            native_crs, WGS84, cols, rows,
            left=left, bottom=bottom, right=right, top=top,
        )

        # Write source in native CRS to a temporary intermediate file.
        with tempfile.NamedTemporaryFile(suffix=".tif", delete=False) as src_tmp:
            src_path = Path(src_tmp.name)

        with rasterio.open(
            src_path, "w", driver="GTiff",
            height=rows, width=cols, count=1, dtype="float32",
            crs=native_crs, transform=native_transform, nodata=nodata,
        ) as src_dst:
            src_dst.write(arr, 1)

        with rasterio.open(src_path) as src:
            with rasterio.open(
                reprojected_path, "w", driver="GTiff",
                height=dst_height, width=dst_width, count=1, dtype="float32",
                crs=WGS84, transform=dst_transform, nodata=nodata,
            ) as dst:
                reproject(
                    source=rasterio.band(src, 1),
                    destination=rasterio.band(dst, 1),
                    src_transform=native_transform,
                    src_crs=native_crs,
                    dst_transform=dst_transform,
                    dst_crs=WGS84,
                    resampling=Resampling.bilinear,
                )
        src_path.unlink()

    # Convert the (reprojected) intermediate GeoTIFF into a tiled COG.
    cog_translate(
        str(reprojected_path), str(out_path),
        cog_profiles.get("deflate"),
        in_memory=False, quiet=True,
    )
    reprojected_path.unlink()
    log.info("  COG written: %s  (shape=%s, crs=EPSG:4326)", out_path.name, data.shape)


# ──────────────────────────────────────────────────────────────────────────────
# MintPy → COG conversion
# ──────────────────────────────────────────────────────────────────────────────

def export_velocity(mintpy_dir: Path, output_dir: Path) -> tuple[Affine, CRS, tuple]:
    """Export velocity.h5 → velocity_mm_yr.tif COG (EPSG:4326).

    Returns the native transform, native CRS, and WGS84 bbox so callers can
    pass them to subsequent export functions and to write_aoi_metadata.
    """
    with h5py.File(mintpy_dir / "velocity.h5", "r") as hf:
        velocity = hf["velocity"][:] * 1000.0    # m/yr → mm/yr
        attrs = dict(hf.attrs)

    native_transform, native_crs, wgs84_bbox = mintpy_attrs_to_geo(attrs)
    write_cog(velocity, native_transform, native_crs, output_dir / "velocity_mm_yr.tif")
    return native_transform, native_crs, wgs84_bbox


def export_coherence(
    mintpy_dir: Path, output_dir: Path,
    native_transform: Affine, native_crs: CRS,
) -> None:
    """Export temporalCoherence.h5 → coherence_mean.tif COG (EPSG:4326)."""
    with h5py.File(mintpy_dir / "temporalCoherence.h5", "r") as hf:
        coh = hf["temporalCoherence"][:]
    write_cog(coh, native_transform, native_crs, output_dir / "coherence_mean.tif")


def export_anomaly_score(
    ml_dir: Path, output_dir: Path,
    native_transform: Affine, native_crs: CRS,
) -> None:
    """Export ML anomaly_score.npy → anomaly_score.tif COG (EPSG:4326)."""
    score = np.load(ml_dir / "anomaly_score.npy")
    write_cog(score, native_transform, native_crs, output_dir / "anomaly_score.tif")


def export_seasonal_amplitude(
    mintpy_dir: Path, output_dir: Path,
    native_transform: Affine, native_crs: CRS,
) -> None:
    """
    Compute seasonal amplitude from timeseries_demErr.h5 and export as COG (EPSG:4326).

    Uses the DEM-error-corrected time series rather than the raw timeseries.h5
    so that residual topographic phase has been removed before the seasonal fit.
    A sin + cos model is fitted at each pixel to extract the annual amplitude.
    """
    ts_file = mintpy_dir / "timeseries_demErr.h5"
    with h5py.File(ts_file, "r") as hf:
        ts    = hf["timeseries"][:] * 1000.0   # m → mm,  shape (T, rows, cols)
        dates = [d.decode() for d in hf["date"][:]]

    from datetime import datetime

    t0     = datetime.strptime(dates[0], "%Y%m%d")
    t_days = np.array([(datetime.strptime(d, "%Y%m%d") - t0).days for d in dates], dtype=float)
    t_yr   = t_days / 365.25
    omega  = 2 * np.pi     # 1 cycle / year

    T, rows, cols = ts.shape
    A = np.column_stack([np.cos(omega * t_yr), np.sin(omega * t_yr), np.ones(T)])

    ts_flat = ts.reshape(T, -1)
    valid   = ~np.any(np.isnan(ts_flat), axis=0)

    coeffs = np.zeros((3, rows * cols), dtype=np.float32)
    if valid.any():
        coeffs[:, valid] = np.linalg.lstsq(A, ts_flat[:, valid], rcond=None)[0]

    amp = np.sqrt(coeffs[0] ** 2 + coeffs[1] ** 2) * 2.0   # peak-to-peak mm
    amp = amp.reshape(rows, cols).astype(np.float32)

    write_cog(amp, native_transform, native_crs, output_dir / "seasonal_amplitude.tif")


# ──────────────────────────────────────────────────────────────────────────────
# Zarr time series store
# ──────────────────────────────────────────────────────────────────────────────

def export_zarr_timeseries(
    mintpy_dir: Path, output_dir: Path,
    native_transform: Affine, native_crs: CRS,
    wgs84_bbox: tuple,
) -> None:
    """
    Write the DEM-error-corrected displacement time series as a Zarr store.

    Store layout
    ------------
    timeseries.zarr/
      displacement/   (T, rows, cols)  float32  mm
      dates/          (T,)             <U8
      .zattrs         → transform_utm, bbox_wgs84, crs info

    The data is kept on the native UTM grid (no reprojection) for pixel-level
    accuracy.  Both the UTM transform and the WGS84 bbox are stored in the
    attributes so the frontend can handle map-display centering (WGS84 bbox)
    and pixel-coordinate lookups (UTM transform).
    """
    zarr_path = output_dir / "timeseries.zarr"

    with h5py.File(mintpy_dir / "timeseries_demErr.h5", "r") as hf:
        ts    = (hf["timeseries"][:] * 1000.0).astype(np.float32)   # mm
        dates = np.array([d.decode() for d in hf["date"][:]])

    T, rows, cols = ts.shape

    root = zarr.open_group(str(zarr_path), mode="w")
    root.create_array(
        "displacement",
        data=ts,
        chunks=(T, min(32, rows), min(32, cols)),
        compressors=[zarr.codecs.Blosc(cname="zstd", clevel=5, shuffle=1)],
    )
    root.create_array("dates", data=dates.astype("U8"))

    x0_utm = float(native_transform.c)
    dx_utm = float(native_transform.a)
    y0_utm = float(native_transform.f)
    dy_utm = float(native_transform.e)

    root.attrs.update(
        {
            "transform_utm": [x0_utm, dx_utm, 0.0, y0_utm, 0.0, dy_utm],
            "bbox_wgs84":    list(wgs84_bbox),
            "crs_native":    f"EPSG:{native_crs.to_epsg()}",
            "crs_display":   "EPSG:4326",
            "shape":         {"T": T, "rows": rows, "cols": cols},
            "units":         "mm",
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

    with h5py.File(mintpy_dir / "timeseries_demErr.h5", "r") as hf:
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

    log.info(
        "Writing %d tile JSON files (%d×%d tiles of %d×%d px) ...",
        total_tiles, n_tile_rows, n_tile_cols, tile_size, tile_size,
    )

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
                        continue

                    series = ts[:, r, c].tolist()
                    key = f"{r}_{c}"

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

                    pixels[f"{r - r0}_{c - c0}"] = pixel_data

            if pixels:
                tile_path = tiles_dir / f"{tr}_{tc}.json"
                with open(tile_path, "w") as f:
                    json.dump(
                        {"tile_row": tr, "tile_col": tc, "r0": r0, "c0": c0,
                         "pixels": pixels, "dates": dates},
                        f, separators=(",", ":"),
                    )

    log.info("Tile JSON export complete.")


# ──────────────────────────────────────────────────────────────────────────────
# AOI manifest
# ──────────────────────────────────────────────────────────────────────────────

def write_aoi_metadata(
    cfg: dict,
    output_dir: Path,
    wgs84_bbox: tuple,
    dates: list[str],
    *,
    shape: dict,
    transform: list[float],
    crs_native: str,
    crs_proj4: str,
    tile_size: int = 32,
) -> None:
    """Write aoi_metadata.json consumed by the frontend on startup.

    bbox and center are always in WGS84 (lon/lat) degrees regardless of the
    native CRS of the processed rasters.

    shape, transform, crs_native, and tile_size enable pixel-level click lookup:
    the frontend converts lat/lng → native coords → row/col for ts_tiles lookup.
    """
    west, south, east, north = wgs84_bbox

    meta = {
        "id":          cfg["id"],
        "name":        cfg["name"],
        "description": cfg["description"].strip(),
        "bbox":        list(wgs84_bbox),
        "center":      cfg.get("center", [(west + east) / 2, (south + north) / 2]),
        "zoom":        cfg.get("zoom", 10),
        "featured":    cfg.get("featured", False),
        "case_study":  cfg.get("case_study", None),
        "date_range":  [dates[0], dates[-1]] if dates else [],
        "shape":       shape,
        "transform":   transform,
        "crs_native":  crs_native,
        "crs_proj4":   crs_proj4,
        "tile_size":   tile_size,
        "layers": [
            {"id": "velocity",           "name": "LOS Velocity",       "unit": "mm/yr", "vmin": cfg["display"]["vmin"],  "vmax": cfg["display"]["vmax"],  "colorscale": cfg["display"]["colorscale"]},
            {"id": "coherence",          "name": "Mean Coherence",     "unit": "",      "vmin": 0,   "vmax": 1,   "colorscale": "Greys"},
            {"id": "anomaly_score",      "name": "Anomaly Score",      "unit": "",      "vmin": 0,   "vmax": 1,   "colorscale": "YlOrRd"},
            {"id": "seasonal_amplitude", "name": "Seasonal Amplitude", "unit": "mm",    "vmin": 0,   "vmax": 20,  "colorscale": "viridis"},
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
    native_transform, native_crs, wgs84_bbox = export_velocity(mintpy_dir, output_dir)
    export_coherence(mintpy_dir, output_dir, native_transform, native_crs)
    export_anomaly_score(ml_dir, output_dir, native_transform, native_crs)
    export_seasonal_amplitude(mintpy_dir, output_dir, native_transform, native_crs)

    if not skip_zarr:
        log.info("=== Exporting Zarr time series ===")
        export_zarr_timeseries(mintpy_dir, output_dir, native_transform, native_crs, wgs84_bbox)

    if not skip_tiles:
        log.info("=== Exporting tile JSON ===")
        export_ts_tile_json(mintpy_dir, ml_dir, output_dir, tile_size=tile_size)

    log.info("=== Writing AOI metadata ===")
    with h5py.File(mintpy_dir / "timeseries_demErr.h5", "r") as hf:
        dates = [d.decode() for d in hf["date"][:]]
        ts = hf["timeseries"]
        T, rows, cols = ts.shape

    transform_list = [
        float(native_transform.c),   # x0
        float(native_transform.a),   # dx
        0.0,
        float(native_transform.f),   # y0
        0.0,
        float(native_transform.e),   # dy
    ]
    crs_native_str = f"EPSG:{native_crs.to_epsg()}"
    crs_proj4_str = native_crs.to_proj4().replace("=True", "").strip()
    write_aoi_metadata(
        cfg, output_dir, wgs84_bbox, dates,
        shape={"T": T, "rows": rows, "cols": cols},
        transform=transform_list,
        crs_native=crs_native_str,
        crs_proj4=crs_proj4_str,
        tile_size=tile_size,
    )

    log.info("Export complete → %s", output_dir)


if __name__ == "__main__":
    main()
