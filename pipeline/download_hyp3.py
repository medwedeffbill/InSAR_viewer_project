"""
Download Sentinel-1 InSAR products from ASF HyP3.

Usage
-----
  python download_hyp3.py --config config/seattle.yml --output-dir data/seattle/hyp3

Requires
--------
  * An Earthdata account: https://urs.earthdata.nasa.gov/
  * HyP3 access enabled:  https://hyp3-api.asf.alaska.edu/
  * NETRC credentials:    ~/.netrc with machine urs.earthdata.nasa.gov

  ~/.netrc entry:
    machine urs.earthdata.nasa.gov
    login YOUR_EARTHDATA_USERNAME
    password YOUR_EARTHDATA_PASSWORD
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

import asf_search as asf
import click
import hyp3_sdk as sdk
import yaml
from tqdm import tqdm

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


def load_config(config_path: Path) -> dict:
    with open(config_path) as f:
        return yaml.safe_load(f)


def search_granules(cfg: dict) -> list[asf.ASFProduct]:
    """
    Search ASF for Sentinel-1 SLC granules covering the AOI.

    Strategy:
      1. Search broadly (no orbit filter) to discover what tracks exist.
      2. If relative_orbit is set in config AND results exist for it, use that track.
      3. Otherwise, auto-select the track with the most granules and log a recommendation.
    """
    west, south, east, north = cfg["bbox"]
    wkt = f"POLYGON(({west} {south},{east} {south},{east} {north},{west} {north},{west} {south}))"

    s1 = cfg["sentinel1"]
    date_cfg = cfg["date_range"]

    log.info("Searching ASF for S1 granules in %s ...", cfg["name"])
    results = asf.search(
        platform=["SENTINEL-1"],
        processingLevel=["SLC"],
        intersectsWith=wkt,
        start=date_cfg["start"],
        end=date_cfg["end"],
        flightDirection=s1["flight_direction"].upper(),
        maxResults=2000,
    )

    if not results:
        log.error(
            "No granules found for %s %s. "
            "Try changing flight_direction in the config to 'ascending'.",
            s1["flight_direction"].upper(), cfg["name"],
        )
        return []

    # Group by relative orbit to find available tracks
    from collections import Counter
    orbit_counts: Counter = Counter()
    for g in results:
        orbit = g.properties.get("pathNumber") or g.properties.get("relativeOrbit")
        if orbit is not None:
            orbit_counts[int(orbit)] += 1

    log.info("Tracks found (%s): %s", s1["flight_direction"].upper(),
             ", ".join(f"T{k}={v}" for k, v in sorted(orbit_counts.items(), key=lambda x: -x[1])))

    # Pick the configured orbit if it has data, else the most-covered orbit
    configured_orbit = s1.get("relative_orbit")
    if configured_orbit and orbit_counts.get(configured_orbit, 0) > 0:
        chosen_orbit = configured_orbit
        log.info("Using configured relative orbit: %d (%d granules)", chosen_orbit, orbit_counts[chosen_orbit])
    else:
        chosen_orbit = orbit_counts.most_common(1)[0][0]
        log.warning(
            "Configured relative_orbit (%s) has no data. "
            "Auto-selected orbit %d (%d granules). "
            "Update relative_orbit in your config YAML to suppress this warning.",
            configured_orbit, chosen_orbit, orbit_counts[chosen_orbit],
        )

    # Filter to the chosen orbit
    filtered = [
        g for g in results
        if int(g.properties.get("pathNumber") or g.properties.get("relativeOrbit") or -1) == chosen_orbit
    ]
    log.info("Using %d granules from orbit %d.", len(filtered), chosen_orbit)
    return filtered


def build_pairs_sbas(granules: list, max_temporal_days: int = 48) -> list[tuple]:
    """Create SBAS-style pairs: each scene connected to the next N within max_temporal_days."""
    from datetime import datetime

    dated = sorted(
        [
            (datetime.strptime(g.properties["startTime"][:10], "%Y-%m-%d"), i, g)
            for i, g in enumerate(granules)
        ],
        key=lambda x: (x[0], x[1]),   # sort by date, then insertion order as tiebreaker
    )

    pairs = []
    for i, (dt_i, _, g_i) in enumerate(dated):
        for dt_j, _, g_j in dated[i + 1 :]:
            delta = (dt_j - dt_i).days
            if delta > max_temporal_days:
                break
            pairs.append((g_i.properties["sceneName"], g_j.properties["sceneName"]))

    log.info("Built %d SBAS pairs (max baseline %d days).", len(pairs), max_temporal_days)
    return pairs


def submit_jobs(
    hyp3: sdk.HyP3, pairs: list[tuple], cfg: dict, batch_size: int = 200
) -> sdk.Batch:
    """Submit InSAR jobs in batches and return the combined Batch.

    hyp3-sdk >= 7.0 API (GAMMA retired; use the generic ISCE-based processor):
      - sdk.HyP3.prepare_insar_job(g1, g2, **opts)  → dict  (static method)
      - hyp3.submit_prepared_jobs([dict, ...])        → Batch
    """
    hyp3_cfg = cfg["hyp3"]
    max_pairs = min(len(pairs), hyp3_cfg.get("max_jobs", 200))
    pairs = pairs[:max_pairs]

    log.info("Preparing %d InSAR job definitions ...", len(pairs))

    prepared: list[dict] = []
    for g1_name, g2_name in pairs:
        job = sdk.HyP3.prepare_insar_job(
            granule1=g1_name,
            granule2=g2_name,
            looks=hyp3_cfg.get("looks", "10x2"),
            include_dem=hyp3_cfg.get("include_dem", True),
            include_inc_map=hyp3_cfg.get("include_inc_map", True),
            apply_water_mask=hyp3_cfg.get("apply_water_mask", True),
        )
        prepared.append(job)

    log.info("Submitting %d jobs to HyP3 (in batches of %d) ...", len(prepared), batch_size)

    all_jobs: list[sdk.Job] = []
    for i in range(0, len(prepared), batch_size):
        chunk = prepared[i : i + batch_size]
        batch = hyp3.submit_prepared_jobs(chunk)
        all_jobs.extend(batch.jobs)
        log.info("  Submitted batch %d/%d", i // batch_size + 1, -(-len(prepared) // batch_size))
        time.sleep(1)

    return sdk.Batch(all_jobs)


def wait_and_download(hyp3: sdk.HyP3, batch: sdk.Batch, output_dir: Path) -> None:
    """Poll HyP3 until all jobs complete, then download."""
    output_dir.mkdir(parents=True, exist_ok=True)
    log.info("Waiting for HyP3 jobs to complete (this can take hours) ...")

    batch = hyp3.watch(batch, interval=60, timeout=86400)

    succeeded = batch.filter_jobs(succeeded=True)
    failed = batch.filter_jobs(succeeded=False, failed=True)

    log.info("Jobs complete: %d succeeded, %d failed.", len(succeeded), len(failed))

    if failed:
        for job in failed.jobs:
            log.warning("  FAILED: %s", job.job_id)

    log.info("Downloading %d products to %s ...", len(succeeded), output_dir)
    succeeded.download_files(location=output_dir)
    log.info("Download complete.")


@click.command()
@click.option("--config", "-c", required=True, type=click.Path(exists=True, path_type=Path), help="AOI config YAML")
@click.option("--output-dir", "-o", required=True, type=click.Path(path_type=Path), help="Directory to store HyP3 products")
@click.option("--submit/--no-submit", default=True, show_default=True, help="Submit new jobs (disable to only download existing)")
@click.option("--existing-batch-id", default=None, help="Resume monitoring a previously submitted batch ID")
def main(config: Path, output_dir: Path, submit: bool, existing_batch_id: str | None) -> None:
    """Download Sentinel-1 InSAR products from ASF HyP3 for an AOI config."""
    cfg = load_config(config)
    log.info("AOI: %s", cfg["name"])

    hyp3 = sdk.HyP3()  # reads credentials from ~/.netrc

    if existing_batch_id:
        log.info("Resuming batch %s ...", existing_batch_id)
        batch = hyp3.find_jobs(job_id=existing_batch_id)
        wait_and_download(hyp3, batch, output_dir)
        return

    if submit:
        granules = search_granules(cfg)
        if not granules:
            log.error("No granules found. Check your AOI config and date range.")
            return

        max_temporal = cfg["mintpy"].get("max_temporal_baseline", 48)
        pairs = build_pairs_sbas(granules, max_temporal_days=max_temporal)

        if not pairs:
            log.error("No pairs constructed. Check the temporal baseline setting.")
            return

        batch = submit_jobs(hyp3, pairs, cfg)
        log.info("Batch submitted. Job IDs saved for resumption.")

        # Save job IDs to file so we can resume if needed
        ids_file = output_dir.parent / f"{cfg['id']}_job_ids.txt"
        ids_file.parent.mkdir(parents=True, exist_ok=True)
        ids_file.write_text("\n".join(j.job_id for j in batch.jobs))
        log.info("Job IDs written to %s", ids_file)

        wait_and_download(hyp3, batch, output_dir)
    else:
        log.info("--no-submit: skipping job submission.")


if __name__ == "__main__":
    main()
