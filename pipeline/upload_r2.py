"""
Upload processed data to Cloudflare R2.

R2 is S3-compatible: uses boto3 with a custom endpoint URL.

Setup
-----
  1. Create a Cloudflare R2 bucket (dashboard.cloudflare.com → R2)
  2. Create an API token with Object Read & Write permissions
  3. Copy .env.example → .env and fill in your credentials:

     R2_ACCOUNT_ID=your_account_id
     R2_ACCESS_KEY_ID=your_access_key
     R2_SECRET_ACCESS_KEY=your_secret_key
     R2_BUCKET_NAME=insar-explorer

  4. Enable public access on the bucket (R2 dashboard → Settings → Public Access)
  5. Optionally add a custom domain (e.g. data.yoursite.com → the bucket)

Usage
-----
  python upload_r2.py --aoi-id seattle --web-dir data/seattle/web --tiles-dir tiles/seattle

  # Dry run (list what would be uploaded)
  python upload_r2.py --aoi-id seattle --web-dir data/seattle/web --tiles-dir tiles/seattle --dry-run
"""

from __future__ import annotations

import logging
import mimetypes
import os
from pathlib import Path

import boto3
import click
from botocore.config import Config
from dotenv import load_dotenv
from tqdm import tqdm

load_dotenv()
log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

MIME_MAP = {
    ".tif":     "image/tiff",
    ".tiff":    "image/tiff",
    ".json":    "application/json",
    ".png":     "image/png",
    ".zarr":    "application/octet-stream",
    ".zarray":  "application/json",
    ".zgroup":  "application/json",
    ".zattrs":  "application/json",
    ".zmetadata": "application/json",
}


def get_s3_client():
    account_id = os.environ["R2_ACCOUNT_ID"]
    return boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )


def get_content_type(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in MIME_MAP:
        return MIME_MAP[ext]
    # Zarr chunk files have no extension
    if path.name.startswith(".z"):
        return "application/json"
    mime, _ = mimetypes.guess_type(str(path))
    return mime or "application/octet-stream"


def collect_files(root_dir: Path, prefix: str) -> list[tuple[Path, str]]:
    """Collect (local_path, s3_key) pairs for all files under root_dir."""
    pairs = []
    for fpath in sorted(root_dir.rglob("*")):
        if fpath.is_file():
            relative = fpath.relative_to(root_dir)
            s3_key = f"{prefix}/{relative}".replace("\\", "/")
            pairs.append((fpath, s3_key))
    return pairs


def upload_files(
    s3,
    bucket: str,
    pairs: list[tuple[Path, str]],
    dry_run: bool = False,
    public: bool = True,
) -> int:
    uploaded = 0
    for local_path, s3_key in tqdm(pairs, desc="Uploading", unit="file"):
        content_type = get_content_type(local_path)
        extra: dict = {"ContentType": content_type}
        if public:
            extra["ACL"] = "public-read"

        if dry_run:
            log.info("  [DRY RUN] %s → s3://%s/%s", local_path, bucket, s3_key)
        else:
            try:
                s3.upload_file(str(local_path), bucket, s3_key, ExtraArgs=extra)
                uploaded += 1
            except Exception as e:
                log.error("  FAILED %s: %s", local_path, e)

    return uploaded


@click.command()
@click.option("--aoi-id",    required=True, help="AOI identifier (top-level R2 prefix)")
@click.option("--web-dir",   required=True, type=click.Path(exists=True, path_type=Path), help="COGs + metadata directory")
@click.option("--tiles-dir", required=True, type=click.Path(exists=True, path_type=Path), help="Pre-rendered tiles directory")
@click.option("--dry-run",   is_flag=True, default=False, help="List files without uploading")
@click.option("--no-public", is_flag=True, default=False, help="Do not set public-read ACL")
def main(aoi_id: str, web_dir: Path, tiles_dir: Path, dry_run: bool, no_public: bool) -> None:
    """Upload AOI data files to Cloudflare R2."""
    bucket = os.environ.get("R2_BUCKET_NAME", "insar-explorer")

    if not dry_run:
        s3 = get_s3_client()
        log.info("Connected to R2 bucket: %s", bucket)
    else:
        s3 = None
        log.info("DRY RUN — no files will be uploaded.")

    # COGs, Zarr, JSON metadata
    web_pairs = collect_files(web_dir, aoi_id)
    log.info("Web assets: %d files", len(web_pairs))

    # Pre-rendered PNG tiles
    aoi_tiles_dir = tiles_dir / aoi_id
    if aoi_tiles_dir.exists():
        tile_pairs = collect_files(aoi_tiles_dir, f"{aoi_id}/tiles")
        log.info("Tile assets: %d files", len(tile_pairs))
    else:
        tile_pairs = []
        log.warning("Tiles directory not found: %s", aoi_tiles_dir)

    all_pairs = web_pairs + tile_pairs
    log.info("Total files to upload: %d", len(all_pairs))

    n = upload_files(s3, bucket, all_pairs, dry_run=dry_run, public=not no_public)

    if not dry_run:
        log.info("Upload complete: %d/%d files.", n, len(all_pairs))
        log.info("Public URL root: https://<your-r2-public-domain>/%s/", aoi_id)


if __name__ == "__main__":
    main()
