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

    # HyP3 product glob patterns — must be absolute paths because MintPy
    # runs with cwd=work_dir, so relative paths would resolve incorrectly.
    # Note: HyP3 ISCE burst products do not include conncomp files.
    base = hyp3_dir.resolve()
    unw_glob  = str(base / "S1*" / "*unw_phase.tif")
    cor_glob  = str(base / "S1*" / "*corr.tif")
    dem_glob  = str(base / "S1*" / "*dem.tif")
    inc_glob  = str(base / "S1*" / "*inc_map.tif")

    tropo = mint.get("tropospheric_correction", "no")
    tropo_method = tropo if tropo != "no" else "no"

    config_text = dedent(f"""\
        ##-----------------------------  Active Datasets  -----------------------------##
        mintpy.load.processor        = hyp3
        mintpy.load.unwFile          = {unw_glob}
        mintpy.load.corFile          = {cor_glob}
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
        # HyP3 ISCE burst products do not include connected-components files,
        # so bridging correction is not available — skip this step.
        mintpy.unwrapError.method        = no

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
    """Unzip any zipped HyP3 products in-place, deleting each ZIP after successful extraction.

    Deleting as we go keeps peak disk usage to roughly (largest ZIP + extracted content)
    rather than (all ZIPs + all extracted content), which is critical on space-constrained
    machines.  ZIPs whose matching directory already exists are skipped and deleted immediately.
    Corrupt ZIPs (e.g. from interrupted downloads) are logged and skipped rather than crashing.
    """
    import zipfile

    zips = list(hyp3_dir.glob("*.zip"))
    if not zips:
        log.info("No ZIP files found — assuming products are already extracted.")
        return

    log.info("Extracting %d ZIP files (deleting each ZIP after extraction) ...", len(zips))
    skipped: list[str] = []

    for i, zf in enumerate(zips, start=1):
        stem = zf.stem
        dest_dir = hyp3_dir / stem
        if dest_dir.exists():
            log.info("  [%d/%d] %s — already extracted, removing ZIP", i, len(zips), stem)
            zf.unlink()
            continue

        if not zipfile.is_zipfile(zf):
            log.warning(
                "  [%d/%d] %s.zip appears corrupt (incomplete download?) — skipping",
                i, len(zips), stem,
            )
            skipped.append(stem)
            continue

        log.info("  [%d/%d] Extracting %s ...", i, len(zips), stem)
        try:
            subprocess.run(
                ["unzip", "-q", "-o", str(zf), "-d", str(hyp3_dir)],
                check=True,
            )
            zf.unlink()
            log.info("  [%d/%d] Extracted and removed %s.zip", i, len(zips), stem)
        except subprocess.CalledProcessError as exc:
            log.warning(
                "  [%d/%d] Failed to extract %s.zip (exit %d) — skipping",
                i, len(zips), stem, exc.returncode,
            )
            skipped.append(stem)

    if skipped:
        log.warning(
            "%d ZIP(s) were skipped due to corruption — MintPy will proceed without them:\n  %s",
            len(skipped), "\n  ".join(skipped),
        )
    log.info("Extraction complete.")


def run_smallbaseline(work_dir: Path, cfg_path: Path, steps: list[str] | None = None) -> None:
    """Execute MintPy's smallbaselineApp.py."""
    cmd = ["smallbaselineApp.py", str(cfg_path.resolve())]
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
