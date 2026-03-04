"""
Download Sentinel-1 InSAR products from ASF HyP3.

Usage
-----
  # Submit jobs and wait for them to finish:
  python download_hyp3.py --config config/seattle.yml --output-dir data/seattle/hyp3

  # Resume after a connection drop (reads saved job IDs, skips resubmission):
  python download_hyp3.py --config config/seattle.yml --output-dir data/seattle/hyp3 --resume

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
import requests
import yaml
from tqdm import tqdm

# Transient network exceptions that warrant a retry
_NETWORK_ERRORS = (
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
    requests.exceptions.ChunkedEncodingError,
)
# Seconds to wait before each successive retry (capped at 5 minutes)
_RETRY_DELAYS = [30, 60, 120, 180, 300]

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

    # Filter to a single burst (by acquisition UTC second).
    #
    # HyP3 ISCE burst products process one Sentinel-1 burst at a time.  A
    # typical AOI spans 1–3 bursts, each acquired ~2.7 s apart on the same
    # pass.  Mixing bursts produces interferograms with incompatible pixel
    # dimensions that MintPy cannot ingest.  We keep only the burst with the
    # most granules; when the AOI is deliberately multi-burst the operator
    # should use the multi-burst processor instead.
    filtered = _filter_to_dominant_burst(filtered)
    return filtered


def _filter_to_dominant_burst(granules: list) -> list:
    """Keep only granules that belong to the most-represented burst.

    Bursts on the same pass are separated by ~2.7 s.  We round each
    granule's acquisition UTC second to the nearest 5-second bucket so that
    the same burst across different passes always hashes to the same bucket.
    """
    from collections import Counter

    def _burst_bucket(g: asf.ASFProduct) -> int:
        start = g.properties.get("startTime", "")
        # startTime format: "2021-01-03T14:12:31.000000Z"
        if len(start) >= 19:
            h, m, s = int(start[11:13]), int(start[14:16]), int(start[17:19])
            total_s = h * 3600 + m * 60 + s
            return round(total_s / 5) * 5  # round to nearest 5 s
        return 0

    buckets = Counter(_burst_bucket(g) for g in granules)
    if len(buckets) == 1:
        return granules  # only one burst, nothing to do

    dominant_bucket, dominant_count = buckets.most_common(1)[0]
    other_buckets = {b: c for b, c in buckets.items() if b != dominant_bucket}

    log.info(
        "Multiple burst time-groups detected: dominant bucket T≈%ds (%d granules), "
        "others: %s — keeping dominant burst only.",
        dominant_bucket,
        dominant_count,
        ", ".join(f"T≈{b}s ({c})" for b, c in sorted(other_buckets.items())),
    )

    kept = [g for g in granules if _burst_bucket(g) == dominant_bucket]
    log.info("After burst filter: %d granules retained.", len(kept))
    return kept


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


def _get_job_with_retry(hyp3: sdk.HyP3, job_id: str) -> sdk.Job:
    """Fetch a single job, retrying on transient network errors."""
    for attempt, delay in enumerate(_RETRY_DELAYS, start=1):
        try:
            return hyp3.get_job_by_id(job_id)
        except _NETWORK_ERRORS as exc:
            log.warning(
                "Connection error fetching job %s (attempt %d/%d): %s — retrying in %ds ...",
                job_id[:8], attempt, len(_RETRY_DELAYS), type(exc).__name__, delay,
            )
            time.sleep(delay)
    # Final attempt — let the exception propagate
    return hyp3.get_job_by_id(job_id)


def _poll_until_complete(
    hyp3: sdk.HyP3, job_ids: list[str], poll_interval: int = 60
) -> sdk.Batch:
    """
    Poll job statuses until every job reaches a terminal state.

    Each individual `get_job_by_id` call is wrapped in retry logic so that a
    momentary connection drop retries that one call rather than crashing the
    whole loop.  Progress is preserved across reconnections because we always
    rebuild the batch from the saved job IDs rather than relying on in-memory
    state.
    """
    total = len(job_ids)
    log.info("Polling %d jobs until complete (poll interval: %ds) ...", total, poll_interval)

    with tqdm(total=total, unit="jobs", desc="HyP3 jobs") as pbar:
        last_done = 0
        while True:
            jobs = [_get_job_with_retry(hyp3, jid) for jid in job_ids]
            batch = sdk.Batch(jobs)

            done = sum(
                1 for j in batch.jobs if j.status_code in ("SUCCEEDED", "FAILED")
            )
            pbar.update(done - last_done)
            last_done = done

            if done == total:
                log.info("All %d jobs have reached a terminal state.", total)
                return batch

            pending = total - done
            log.info(
                "%d/%d jobs done, %d still running. Next check in %ds.",
                done, total, pending, poll_interval,
            )
            time.sleep(poll_interval)


def wait_and_download(
    hyp3: sdk.HyP3, job_ids: list[str], output_dir: Path, poll_interval: int = 60
) -> None:
    """Poll HyP3 until all jobs complete, then download. Retries on connection errors."""
    output_dir.mkdir(parents=True, exist_ok=True)
    log.info("Waiting for %d HyP3 jobs to complete (this can take hours) ...", len(job_ids))

    batch = _poll_until_complete(hyp3, job_ids, poll_interval=poll_interval)

    succeeded = batch.filter_jobs(succeeded=True)
    failed = batch.filter_jobs(succeeded=False, failed=True)

    log.info("Jobs complete: %d succeeded, %d failed.", len(succeeded), len(failed))
    if failed.jobs:
        for job in failed.jobs:
            log.warning("  FAILED: %s", job.job_id)

    if not succeeded.jobs:
        log.error("No succeeded jobs to download.")
        return

    log.info("Downloading %d products to %s ...", len(succeeded), output_dir)
    for attempt, delay in enumerate(_RETRY_DELAYS, start=1):
        try:
            succeeded.download_files(location=output_dir)
            break
        except _NETWORK_ERRORS as exc:
            if attempt == len(_RETRY_DELAYS):
                raise
            log.warning(
                "Download interrupted (attempt %d/%d): %s — retrying in %ds ...",
                attempt, len(_RETRY_DELAYS), type(exc).__name__, delay,
            )
            time.sleep(delay)

    log.info("Download complete.")


@click.command()
@click.option("--config", "-c", required=True, type=click.Path(exists=True, path_type=Path), help="AOI config YAML")
@click.option("--output-dir", "-o", required=True, type=click.Path(path_type=Path), help="Directory to store HyP3 products")
@click.option("--resume", is_flag=True, default=False, help="Skip submission and resume monitoring from the saved job-IDs file")
@click.option("--submit/--no-submit", default=True, show_default=True, help="Submit new jobs (use --resume instead of --no-submit to monitor existing jobs)")
def main(config: Path, output_dir: Path, resume: bool, submit: bool) -> None:
    """Download Sentinel-1 InSAR products from ASF HyP3 for an AOI config."""
    cfg = load_config(config)
    log.info("AOI: %s", cfg["name"])

    hyp3 = sdk.HyP3()  # reads credentials from ~/.netrc

    ids_file = output_dir.parent / f"{cfg['id']}_job_ids.txt"

    if resume:
        if not ids_file.exists():
            log.error(
                "No saved job IDs found at %s. "
                "Run without --resume to submit new jobs first.",
                ids_file,
            )
            return
        job_ids = ids_file.read_text().strip().splitlines()
        log.info("Resuming %d jobs from %s ...", len(job_ids), ids_file)
        wait_and_download(hyp3, job_ids, output_dir)
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

        job_ids = [j.job_id for j in batch.jobs]
        ids_file.parent.mkdir(parents=True, exist_ok=True)
        ids_file.write_text("\n".join(job_ids))
        log.info("Job IDs written to %s (use --resume to reconnect if interrupted)", ids_file)

        wait_and_download(hyp3, job_ids, output_dir)
    else:
        log.info("--no-submit: skipping job submission. Use --resume to monitor existing jobs.")


if __name__ == "__main__":
    main()
