"""
Run MintPy time-series processing on HyP3 InSAR products.

Usage
-----
  python run_mintpy.py --config config/seattle.yml --hyp3-dir data/seattle/hyp3 --work-dir data/seattle/mintpy

MintPy docs: https://mintpy.readthedocs.io/
HyP3+MintPy guide: https://hyp3-docs.asf.alaska.edu/guides/mintpy/
"""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

import click
import yaml

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


def load_config(config_path: Path) -> dict:
    with open(config_path) as f:
        return yaml.safe_load(f)


def write_mintpy_config(cfg: dict, hyp3_dir: Path, work_dir: Path) -> Path:
    """Generate a MintPy smallbaselineApp.cfg for HyP3 products."""
    mint = cfg["mintpy"]
    hyp3 = cfg["hyp3"]

    # HyP3 product glob patterns (unzipped structure)
    unw_glob   = str(hyp3_dir / "S1*" / "*unw_phase.tif")
    cor_glob   = str(hyp3_dir / "S1*" / "*corr.tif")
    conn_glob  = str(hyp3_dir / "S1*" / "*conncomp.tif")
    dem_glob   = str(hyp3_dir / "S1*" / "*dem.tif")
    inc_glob   = str(hyp3_dir / "S1*" / "*inc_map.tif")

    tropo = mint.get("tropospheric_correction", "no")
    tropo_method = tropo if tropo != "no" else "no"

    config_text = dedent(f"""\
        ##-----------------------------  Active Datasets  -----------------------------##
        mintpy.load.processor        = hyp3
        mintpy.load.unwFile          = {unw_glob}
        mintpy.load.corFile          = {cor_glob}
        mintpy.load.connCompFile     = {conn_glob}
        mintpy.load.demFile          = {dem_glob}
        mintpy.load.incAngleFile     = {inc_glob}

        ##-----------------------------  Interferogram Network  -----------------------##
        mintpy.network.coherenceBased    = yes
        mintpy.network.minCoherence      = {mint.get('min_coherence', 0.4)}
        mintpy.network.tempBaseMax       = {mint.get('max_temporal_baseline', 48)}
        mintpy.network.perpBaseMax       = {mint.get('max_spatial_baseline', 150)}

        ##-----------------------------  Reference Point  ----------------------------##
        mintpy.reference.lalo            = auto

        ##-----------------------------  Unwrapping Error  ---------------------------##
        mintpy.unwrapError.method        = bridging

        ##-----------------------------  Phase Deramping  ----------------------------##
        mintpy.deramp                    = no

        ##-----------------------------  Tropospheric Delay  -------------------------##
        mintpy.troposphericDelay.method  = {tropo_method}

        ##-----------------------------  DEM Error Correction  -----------------------##
        mintpy.topographicResidual       = {'yes' if mint.get('dem_error_correction', True) else 'no'}

        ##-----------------------------  Noise Evaluation  ---------------------------##
        mintpy.save.hdfEos5              = no
        mintpy.save.kmz                  = no
    """)

    work_dir.mkdir(parents=True, exist_ok=True)
    cfg_path = work_dir / "smallbaselineApp.cfg"
    cfg_path.write_text(config_text)
    log.info("MintPy config written to %s", cfg_path)
    return cfg_path


def unzip_hyp3_products(hyp3_dir: Path) -> None:
    """Unzip any zipped HyP3 products in-place."""
    zips = list(hyp3_dir.glob("*.zip"))
    if not zips:
        log.info("No ZIP files found — assuming products are already extracted.")
        return

    log.info("Extracting %d ZIP files ...", len(zips))
    for zf in zips:
        subprocess.run(
            ["unzip", "-q", "-o", str(zf), "-d", str(hyp3_dir)],
            check=True,
        )
    log.info("Extraction complete.")


def run_smallbaseline(work_dir: Path, cfg_path: Path, steps: list[str] | None = None) -> None:
    """Execute MintPy's smallbaselineApp.py."""
    cmd = ["smallbaselineApp.py", str(cfg_path)]
    if steps:
        cmd += ["--dostep", ",".join(steps)]

    log.info("Running: %s", " ".join(cmd))
    result = subprocess.run(cmd, cwd=work_dir, capture_output=False)
    if result.returncode != 0:
        log.error("MintPy exited with code %d.", result.returncode)
        sys.exit(result.returncode)
    log.info("MintPy processing complete.")


@click.command()
@click.option("--config", "-c", required=True, type=click.Path(exists=True, path_type=Path))
@click.option("--hyp3-dir", required=True, type=click.Path(exists=True, path_type=Path), help="Directory with downloaded HyP3 products")
@click.option("--work-dir", required=True, type=click.Path(path_type=Path), help="MintPy working directory (will be created)")
@click.option("--steps", default=None, help="Comma-separated MintPy steps to run (default: all). E.g. 'load_data,modify_network'")
@click.option("--skip-unzip", is_flag=True, default=False, help="Skip unzipping HyP3 products")
def main(config: Path, hyp3_dir: Path, work_dir: Path, steps: str | None, skip_unzip: bool) -> None:
    """Run MintPy SBAS processing on HyP3 InSAR products."""
    cfg = load_config(config)
    log.info("Processing AOI: %s", cfg["name"])

    if not skip_unzip:
        unzip_hyp3_products(hyp3_dir)

    cfg_path = write_mintpy_config(cfg, hyp3_dir, work_dir)

    step_list = [s.strip() for s in steps.split(",")] if steps else None
    run_smallbaseline(work_dir, cfg_path, step_list)

    # Validate expected outputs exist
    expected = ["timeseries.h5", "velocity.h5", "temporalCoherence.h5"]
    for fname in expected:
        fpath = work_dir / fname
        if fpath.exists():
            log.info("  ✓ %s", fname)
        else:
            log.warning("  ✗ %s NOT FOUND — processing may have failed", fname)


if __name__ == "__main__":
    main()
