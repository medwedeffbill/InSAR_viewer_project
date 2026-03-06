"""
Generate PNG map tiles from COG rasters using rio-tiler.

Produces XYZ/TMS-compatible tiles stored as:
  {output_dir}/{aoi_id}/{layer}/{z}/{x}/{y}.png

These are served directly from Cloudflare R2 as MapLibre GL raster tile sources.

Usage
-----
  python generate_tiles.py \\
      --cog-dir   data/seattle/web \\
      --output-dir tiles/seattle \\
      --aoi-id    seattle \\
      --zoom-min  6 \\
      --zoom-max  13
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

try:
    from rio_tiler.io import COGReader
    from rio_tiler.colormap import cmap as CMAPS
except ModuleNotFoundError as e:
    if "rio_tiler" in str(e):
        print(
            "Error: rio_tiler not found. Activate the pipeline environment first:\n"
            "  conda activate insar-pipeline\n"
            "Then run this script again.",
            file=sys.stderr,
        )
        sys.exit(1)
    raise

import click
import numpy as np
from PIL import Image
from rasterio.crs import CRS
from tqdm import tqdm
import mercantile

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# ──────────────────────────────────────────────────────────────────────────────
# Colour scale configuration
# ──────────────────────────────────────────────────────────────────────────────

LAYER_STYLES: dict[str, dict] = {
    "velocity_mm_yr": {
        "colormap":  "RdBu_r",   # matplotlib colormap names are case-sensitive
        "rescale":   (-30, 30),
        "nodata":    float("nan"),
    },
    "coherence_mean": {
        "colormap":  "Greys",
        "rescale":   (0, 1),
        "nodata":    float("nan"),
    },
    "anomaly_score": {
        "colormap":  "YlOrRd",
        "rescale":   (0, 1),
        "nodata":    float("nan"),
    },
    "seasonal_amplitude": {
        "colormap":  "viridis",
        "rescale":   (0, 20),
        "nodata":    float("nan"),
    },
}


def value_to_rgba(data: np.ndarray, mask: np.ndarray, colormap_name: str, vmin: float, vmax: float) -> np.ndarray:
    """
    Map float32 data → RGBA uint8 using a matplotlib colormap.
    Transparent where mask == 0 (no data).
    """
    import matplotlib.pyplot as plt
    import matplotlib.colors as mcolors

    cmap = plt.get_cmap(colormap_name.replace("_r", "") + ("_r" if colormap_name.endswith("_r") else ""))

    # Normalise to [0, 1]
    normed = np.clip((data.astype(float) - vmin) / max(vmax - vmin, 1e-9), 0.0, 1.0)
    rgba = (cmap(normed) * 255).astype(np.uint8)   # (H, W, 4)

    # Apply no-data mask: alpha = 0 where mask == 0
    rgba[:, :, 3] = np.where(mask > 0, rgba[:, :, 3], 0)

    return rgba


def render_tile(
    reader: COGReader,
    x: int,
    y: int,
    z: int,
    style: dict,
    tile_size: int = 256,
) -> Image.Image | None:
    """Render one XYZ tile as a PIL Image. Returns None if no data in tile."""
    try:
        img = reader.tile(x, y, z, tilesize=tile_size)
    except Exception:
        return None

    data = img.data[0]    # (H, W)  float32
    mask = img.mask       # (H, W)  uint8, 0 = nodata

    if mask.max() == 0:
        return None   # entirely masked

    vmin, vmax = style["rescale"]
    rgba = value_to_rgba(data, mask, style["colormap"], vmin, vmax)
    return Image.fromarray(rgba, mode="RGBA")


def get_tiles_for_zoom(bbox: tuple[float, float, float, float], zoom: int) -> list:
    """Return all mercantile tiles covering the bbox at a given zoom level."""
    west, south, east, north = bbox
    return list(mercantile.tiles(west, south, east, north, zooms=zoom))


# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────

@click.command()
@click.option("--cog-dir",    required=True, type=click.Path(exists=True, path_type=Path), help="Directory with COG rasters")
@click.option("--output-dir", required=True, type=click.Path(path_type=Path),              help="Root output directory for tiles")
@click.option("--aoi-id",     required=True, help="AOI identifier (used in output path)")
@click.option("--zoom-min",   default=6,  show_default=True)
@click.option("--zoom-max",   default=13, show_default=True)
@click.option("--tile-size",  default=256, show_default=True)
@click.option("--layers",     default="all", show_default=True, help="Comma-separated layer names or 'all'")
def main(
    cog_dir: Path,
    output_dir: Path,
    aoi_id: str,
    zoom_min: int,
    zoom_max: int,
    tile_size: int,
    layers: str,
) -> None:
    """Generate PNG tiles from COG rasters for MapLibre GL serving."""
    layer_names = list(LAYER_STYLES.keys()) if layers == "all" else [l.strip() for l in layers.split(",")]

    for layer_name in layer_names:
        cog_path = cog_dir / f"{layer_name}.tif"
        if not cog_path.exists():
            log.warning("COG not found, skipping: %s", cog_path)
            continue

        style = LAYER_STYLES[layer_name]
        layer_out = output_dir / aoi_id / layer_name
        layer_out.mkdir(parents=True, exist_ok=True)

        log.info("Tiling layer: %s  zooms=%d–%d", layer_name, zoom_min, zoom_max)

        with COGReader(str(cog_path)) as reader:
            # WGS84 (EPSG:4326) is the global lat/lon system; web tiles and mercantile expect bounds in degrees
            bounds = reader.get_geographic_bounds(crs=CRS.from_epsg(4326))   # (west, south, east, north)

            total_tiles = sum(
                len(get_tiles_for_zoom(bounds, z)) for z in range(zoom_min, zoom_max + 1)
            )
            log.info("  ~%d tiles to generate", total_tiles)

            with tqdm(total=total_tiles, desc=f"  {layer_name}", unit="tile") as pbar:
                for z in range(zoom_min, zoom_max + 1):
                    tiles = get_tiles_for_zoom(bounds, z)
                    for tile in tiles:
                        x, y = tile.x, tile.y
                        img = render_tile(reader, x, y, z, style, tile_size)

                        if img is not None:
                            tile_dir = layer_out / str(z) / str(x)
                            tile_dir.mkdir(parents=True, exist_ok=True)
                            img.save(tile_dir / f"{y}.png", format="PNG", optimize=True)

                        pbar.update(1)

        log.info("  Done: %s", layer_out)

    log.info("Tile generation complete → %s", output_dir)


if __name__ == "__main__":
    main()
