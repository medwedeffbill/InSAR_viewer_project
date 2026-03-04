"""
ML-based anomaly detection for InSAR displacement time series.

Pipeline
--------
  1. Load MintPy timeseries_demErr.h5  →  (T × rows × cols)
  2. Vectorised feature extraction across ALL valid pixels at once:
       - linear trend rate  (mm/yr)
       - residual variance  (mm²)
       - seasonal amplitude via sin+cos fit (mm peak-to-peak)
       - trend acceleration (2nd-order fit curvature, mm/yr²)
       - change-point score (variance-reduction metric, no per-pixel loop)
  3. Score with Isolation Forest →  anomaly_score ∈ [0, 1]
  4. Rule-based "why flagged?"   →  human-readable label strings
  5. Save:
       anomaly_score.npy  — (rows × cols) float32
       labels.json        — sparse dict keyed "row_col" → {score, labels, cp_date}

Note on STL
-----------
  With only ~15 observations over 6 months the STL period assumption (~12 obs/
  season) is not statistically reliable: fewer than two full seasons are present.
  We therefore replace per-pixel STL with fully vectorised polynomial and
  trigonometric fits, which run in seconds rather than hours on millions of pixels.

Usage
-----
  python anomaly_detection.py \\
      --mintpy-dir  data/seattle/mintpy \\
      --output-dir  data/seattle/export \\
      --config      config/seattle.yml
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import click
import h5py
import numpy as np
import yaml
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


# ──────────────────────────────────────────────────────────────────────────────
# Loading
# ──────────────────────────────────────────────────────────────────────────────

def load_timeseries(mintpy_dir: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, tuple, str]:
    """
    Load MintPy outputs.

    Returns
    -------
    ts        : (T, rows, cols) float32  displacement in mm
    dates     : (T,)            str      'YYYYMMDD'
    coh       : (rows, cols)    float32  temporal coherence
    transform : (6,)            float    GDAL-style geotransform (native CRS units)
    crs       : str             e.g. "EPSG:32610"
    """
    ts_file  = mintpy_dir / "timeseries_demErr.h5"   # DEM-error corrected
    coh_file = mintpy_dir / "temporalCoherence.h5"

    for f in [ts_file, coh_file]:
        if not f.exists():
            raise FileNotFoundError(f"Expected MintPy output not found: {f}")

    with h5py.File(ts_file, "r") as hf:
        ts    = hf["timeseries"][:] * 1000.0         # metres → mm
        dates = [d.decode() for d in hf["date"][:]]
        attrs = dict(hf.attrs)
        x0   = float(attrs.get("X_FIRST", 0))
        y0   = float(attrs.get("Y_FIRST", 0))
        dx   = float(attrs.get("X_STEP",  0.0001))
        dy   = float(attrs.get("Y_STEP", -0.0001))
        epsg = int(attrs.get("EPSG", 4326))
        transform = (x0, dx, 0.0, y0, 0.0, dy)
        crs = f"EPSG:{epsg}"

    with h5py.File(coh_file, "r") as hf:
        coh = hf["temporalCoherence"][:]

    log.info(
        "Loaded time series: shape=%s, T=%d dates, CRS=%s",
        ts.shape, len(dates), crs,
    )
    return ts.astype(np.float32), np.array(dates), coh.astype(np.float32), transform, crs


# ──────────────────────────────────────────────────────────────────────────────
# Vectorised feature extraction
# ──────────────────────────────────────────────────────────────────────────────

def _decimal_years(dates: list[str]) -> np.ndarray:
    """Convert YYYYMMDD strings to decimal years from the first date."""
    from datetime import datetime
    t0 = datetime.strptime(dates[0], "%Y%m%d")
    return np.array(
        [(datetime.strptime(d, "%Y%m%d") - t0).days / 365.25 for d in dates],
        dtype=np.float64,
    )


def extract_features_vectorised(
    ts: np.ndarray,
    dates: list[str],
    coh: np.ndarray,
    min_coherence: float = 0.4,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Compute per-pixel features for all coherent pixels in a single batch.

    All fitting is done via np.linalg.lstsq on a shared design matrix — no
    Python loops over pixels.

    Features (per coherent pixel)
    ──────────────────────────────
    0  trend_rate_abs     |mm/yr|     — magnitude of linear LOS velocity
    1  residual_variance  mm²         — variance after removing linear trend
    2  seasonal_amplitude mm          — peak-to-peak of annual sin+cos component
    3  trend_acceleration mm/yr²      — curvature of quadratic fit
    4  cp_score           [0,1]       — variance-reduction from best 2-segment split

    Returns
    -------
    features      : (N_valid, 5)  float32
    pixel_rc      : (N_valid, 2)  int     row/col indices of valid pixels
    trend_slopes  : (N_valid,)    float32 signed slope (mm/yr) for label direction
    """
    T, rows, cols = ts.shape
    t_yr = _decimal_years(dates)                    # (T,)
    omega = 2.0 * np.pi                             # 1 cycle / year

    # ── Build design matrix for joint fit: [linear, sin, cos, constant] ──────
    A = np.column_stack([
        t_yr,
        np.sin(omega * t_yr),
        np.cos(omega * t_yr),
        np.ones(T),
    ]).astype(np.float64)                            # (T, 4)

    # ── Select valid (coherent) pixels ───────────────────────────────────────
    mask = (coh >= min_coherence)
    ri, ci = np.where(mask)
    N = len(ri)
    log.info("Processing %d coherent pixels (%.1f%% of scene) ...", N, 100 * N / (rows * cols))

    # ── Flatten valid pixels: (T, N) ─────────────────────────────────────────
    ts_valid = ts[:, ri, ci].astype(np.float64)     # (T, N)

    # ── Replace any NaN columns with linear interpolation ────────────────────
    for j in range(N):
        col = ts_valid[:, j]
        nan_mask = np.isnan(col)
        if nan_mask.all():
            ts_valid[:, j] = 0.0
        elif nan_mask.any():
            x = np.arange(T)
            ts_valid[:, j] = np.interp(x, x[~nan_mask], col[~nan_mask])

    # ── Batch least-squares: A @ coeffs ≈ ts_valid ───────────────────────────
    # coeffs shape: (4, N)  → [slope, sin_coeff, cos_coeff, intercept]
    log.info("Fitting linear+seasonal model to %d pixels ...", N)
    coeffs, _, _, _ = np.linalg.lstsq(A, ts_valid, rcond=None)

    slope      = coeffs[0]                           # mm/yr  (N,)
    sin_c      = coeffs[1]                           # (N,)
    cos_c      = coeffs[2]                           # (N,)

    # ── Residuals after full model ────────────────────────────────────────────
    ts_hat     = A @ coeffs                          # (T, N)
    residuals  = ts_valid - ts_hat                   # (T, N)

    # ── Feature 0: trend rate (absolute, mm/yr) ───────────────────────────────
    trend_rate_abs = np.abs(slope).astype(np.float32)

    # ── Feature 1: residual variance (mm²) ───────────────────────────────────
    resid_var = np.var(residuals, axis=0).astype(np.float32)

    # ── Feature 2: seasonal amplitude (peak-to-peak mm) ──────────────────────
    # A*cos + B*sin → amplitude = 2*sqrt(A²+B²)
    seasonal_amp = (2.0 * np.sqrt(sin_c**2 + cos_c**2)).astype(np.float32)

    # ── Feature 3: trend acceleration (quadratic curvature, mm/yr²) ──────────
    # Fit 2nd-order polynomial to the linear-trend component only
    log.info("Fitting quadratic model for acceleration ...")
    A2 = np.column_stack([t_yr**2, t_yr, np.ones(T)]).astype(np.float64)
    ts_trend = (A[:, [0]] * coeffs[0:1, :] + A[:, [3]] * coeffs[3:4, :])  # linear trend
    c2, _, _, _ = np.linalg.lstsq(A2, ts_trend, rcond=None)
    accel = np.abs(c2[0]).astype(np.float32)          # 2nd-order coeff = acceleration/2!

    # ── Feature 4: change-point score ────────────────────────────────────────
    # For each pixel: find the split index that maximises variance reduction.
    # Fully vectorised over split positions (inner loop is over time steps, not pixels).
    log.info("Computing change-point scores ...")
    T_min = 4
    cp_scores = np.zeros(N, dtype=np.float32)
    baseline_var = np.var(residuals, axis=0)          # (N,)

    best_reduction = np.zeros(N, dtype=np.float64)
    for t in range(T_min, T - T_min):
        before = residuals[:t, :]                      # (t, N)
        after  = residuals[t:, :]                      # (T-t, N)
        seg_var = (
            np.var(before, axis=0) * t +
            np.var(after,  axis=0) * (T - t)
        ) / T
        reduction = baseline_var - seg_var             # positive → better split
        best_reduction = np.maximum(best_reduction, reduction)

    denom = np.where(baseline_var > 0, baseline_var, 1.0)
    cp_scores = np.clip(best_reduction / denom, 0.0, 1.0).astype(np.float32)

    # ── Stack features ────────────────────────────────────────────────────────
    features = np.column_stack([
        trend_rate_abs,
        resid_var,
        seasonal_amp,
        accel,
        cp_scores,
    ]).astype(np.float32)

    pixel_rc = np.column_stack([ri, ci])              # (N, 2) int

    log.info("Feature matrix: shape=%s, range=[%.3f, %.3f]",
             features.shape, features.min(), features.max())
    return features, pixel_rc, slope.astype(np.float32)


# ──────────────────────────────────────────────────────────────────────────────
# Isolation Forest scoring
# ──────────────────────────────────────────────────────────────────────────────

def compute_anomaly_scores(feature_matrix: np.ndarray, contamination: float = 0.05) -> np.ndarray:
    """
    Fit Isolation Forest and return anomaly scores in [0, 1].

    IsolationForest.score_samples returns negative values — more negative means
    more anomalous.  We remap so 1 = most anomalous.
    """
    scaler = StandardScaler()
    X = scaler.fit_transform(feature_matrix)

    clf = IsolationForest(
        n_estimators=200,
        contamination=contamination,
        max_features=1.0,
        random_state=42,
        n_jobs=-1,
    )
    clf.fit(X)

    raw = clf.score_samples(X)
    lo, hi = raw.min(), raw.max()
    scores = 1.0 - (raw - lo) / (hi - lo) if hi > lo else np.zeros_like(raw)
    return scores.astype(np.float32)


# ──────────────────────────────────────────────────────────────────────────────
# Rule-based labelling
# ──────────────────────────────────────────────────────────────────────────────

def _percentile_thresholds(features: np.ndarray, p: float = 90) -> dict:
    """Distribution-based thresholds derived from the valid-pixel population."""
    return {
        "trend_rate_abs":    float(np.percentile(features[:, 0], p)),
        "resid_var":         float(np.percentile(features[:, 1], p)),
        "seasonal_amp":      float(np.percentile(features[:, 2], p)),
        "accel":             float(np.percentile(features[:, 3], p)),
        "cp_score":          0.30,   # absolute threshold
    }


def assign_labels(
    feat_row: np.ndarray,
    slope: float,
    thresholds: dict,
) -> list[str]:
    """Return human-readable reason strings for a flagged pixel."""
    labels: list[str] = []
    trend_rate, resid_var, seasonal_amp, accel, cp_score = feat_row.tolist()

    if resid_var > thresholds["resid_var"]:
        labels.append("High residual variance — signal not explained by trend or seasonality")

    if trend_rate > thresholds["trend_rate_abs"]:
        direction = "subsidence (away from satellite)" if slope < 0 else "uplift / toward-satellite motion"
        labels.append(f"Rapid {direction} ({trend_rate:.1f} mm/yr LOS rate)")

    if seasonal_amp > thresholds["seasonal_amp"]:
        labels.append(f"Strong seasonal signal ({seasonal_amp:.1f} mm peak-to-peak)")

    if accel > thresholds["accel"]:
        labels.append("Accelerating deformation rate")

    if cp_score > thresholds["cp_score"]:
        labels.append("Abrupt change point in displacement time series")

    return labels


# ──────────────────────────────────────────────────────────────────────────────
# Output assembly
# ──────────────────────────────────────────────────────────────────────────────

def build_outputs(
    ts_shape: tuple,
    pixel_rc: np.ndarray,
    scores: np.ndarray,
    features: np.ndarray,
    slopes: np.ndarray,
    anomaly_threshold: float = 0.65,
) -> tuple[np.ndarray, dict]:
    """
    Build:
      score_raster : (rows, cols) float32, NaN where no coherent data
      label_dict   : {row_col: {score, labels}}  for pixels above threshold
    """
    T, rows, cols = ts_shape
    score_raster = np.full((rows, cols), np.nan, dtype=np.float32)

    thresholds = _percentile_thresholds(features)

    # Fill raster
    score_raster[pixel_rc[:, 0], pixel_rc[:, 1]] = scores

    # Build label dict for anomalous pixels only
    flagged_mask = scores >= anomaly_threshold
    log.info("Flagged %d pixels (score ≥ %.2f).", flagged_mask.sum(), anomaly_threshold)

    label_dict: dict = {}
    for i in np.where(flagged_mask)[0]:
        r, c = int(pixel_rc[i, 0]), int(pixel_rc[i, 1])
        lbls = assign_labels(features[i], float(slopes[i]), thresholds)
        label_dict[f"{r}_{c}"] = {
            "score":  round(float(scores[i]), 4),
            "labels": lbls,
        }

    return score_raster, label_dict


# ──────────────────────────────────────────────────────────────────────────────
# Save
# ──────────────────────────────────────────────────────────────────────────────

def save_outputs(
    output_dir: Path,
    score_raster: np.ndarray,
    label_dict: dict,
    ts: np.ndarray,
    dates: list[str],
    transform: tuple,
    crs: str,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    np.save(output_dir / "anomaly_score.npy", score_raster)
    log.info("Saved anomaly_score.npy  shape=%s", score_raster.shape)

    with open(output_dir / "labels.json", "w") as f:
        json.dump(label_dict, f, indent=2)
    log.info("Saved labels.json  (%d anomalous pixels)", len(label_dict))

    meta = {
        "transform": list(transform),
        "shape":     {"T": int(ts.shape[0]), "rows": int(ts.shape[1]), "cols": int(ts.shape[2])},
        "dates":     list(dates),
        "crs":       crs,
    }
    with open(output_dir / "meta.json", "w") as f:
        json.dump(meta, f, indent=2)
    log.info("Saved meta.json")


# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────

@click.command()
@click.option("--mintpy-dir",        required=True, type=click.Path(exists=True, path_type=Path))
@click.option("--output-dir",        required=True, type=click.Path(path_type=Path))
@click.option("--config",            required=True, type=click.Path(exists=True, path_type=Path))
@click.option("--contamination",     default=0.05,  show_default=True,
              help="Expected fraction of anomalous pixels (IsolationForest)")
@click.option("--anomaly-threshold", default=0.65,  show_default=True,
              help="Score cutoff for label assignment")
def main(
    mintpy_dir: Path,
    output_dir: Path,
    config: Path,
    contamination: float,
    anomaly_threshold: float,
) -> None:
    """Run vectorised ML anomaly detection on MintPy time series outputs."""
    with open(config) as fh:
        cfg = yaml.safe_load(fh)
    min_coh = cfg["mintpy"].get("min_coherence", 0.4)

    ts, dates, coh, transform, crs = load_timeseries(mintpy_dir)

    features, pixel_rc, slopes = extract_features_vectorised(
        ts, list(dates), coh, min_coherence=min_coh,
    )

    if len(pixel_rc) == 0:
        log.error("No coherent pixels found — check your coherence threshold.")
        return

    log.info("Scoring anomalies with Isolation Forest (%d trees, n_jobs=-1) ...", 200)
    scores = compute_anomaly_scores(features, contamination=contamination)

    score_raster, label_dict = build_outputs(
        ts.shape, pixel_rc, scores, features, slopes, anomaly_threshold,
    )

    save_outputs(output_dir, score_raster, label_dict, ts, list(dates), transform, crs)
    log.info("Anomaly detection complete → %s", output_dir)


if __name__ == "__main__":
    main()
