"""
ML-based anomaly detection for InSAR displacement time series.

Pipeline
--------
  1. Load MintPy timeseries.h5  →  (N_pixels × T_timesteps)
  2. STL decompose each pixel   →  trend + seasonal + residual
  3. Extract per-pixel features →  residual_variance, trend_magnitude,
                                    seasonal_amplitude, change_point_score,
                                    trend_acceleration
  4. Score with Isolation Forest →  anomaly_score ∈ [0, 1]
  5. Detect change points        →  ruptures PELT algorithm per pixel
  6. Rule-based "why flagged?"   →  human-readable label strings
  7. Save:
       anomaly_score.npy  — (rows × cols) float32
       labels.json        — sparse dict keyed "row_col" → {score, labels, cp_date}

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
from statsmodels.tsa.seasonal import STL
from tqdm import tqdm

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# ──────────────────────────────────────────────────────────────────────────────
# Data structures
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class PixelFeatures:
    residual_variance: float = 0.0
    trend_magnitude: float = 0.0        # |mm/yr|
    seasonal_amplitude: float = 0.0     # peak-to-peak mm
    trend_acceleration: float = 0.0     # second derivative of trend
    cp_score: float = 0.0               # ruptures normalised cost reduction
    cp_date_idx: Optional[int] = None   # timestep index of change point


@dataclass
class PixelResult:
    row: int
    col: int
    anomaly_score: float
    labels: list[str] = field(default_factory=list)
    change_point_date: Optional[str] = None


# ──────────────────────────────────────────────────────────────────────────────
# Loading
# ──────────────────────────────────────────────────────────────────────────────

def load_timeseries(mintpy_dir: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, tuple]:
    """
    Load MintPy outputs.

    Returns
    -------
    ts        : (T, rows, cols) float32  displacement in mm
    dates     : (T,)             str     'YYYYMMDD'
    coh       : (rows, cols)     float32 mean temporal coherence
    transform : (6,)             float64 GDAL-style geotransform
    """
    ts_file = mintpy_dir / "timeseries.h5"
    vel_file = mintpy_dir / "velocity.h5"
    coh_file = mintpy_dir / "temporalCoherence.h5"

    for f in [ts_file, vel_file, coh_file]:
        if not f.exists():
            raise FileNotFoundError(f"Expected MintPy output not found: {f}")

    with h5py.File(ts_file, "r") as hf:
        ts     = hf["timeseries"][:]            # (T, rows, cols), metres
        ts     = ts * 1000.0                    # → mm
        dates  = [d.decode() for d in hf["date"][:]]

        # Extract geotransform from MintPy attributes
        attrs = dict(hf.attrs)
        x0 = float(attrs.get("X_FIRST", 0))
        y0 = float(attrs.get("Y_FIRST", 0))
        dx = float(attrs.get("X_STEP", 0.0001))
        dy = float(attrs.get("Y_STEP", -0.0001))
        transform = (x0, dx, 0.0, y0, 0.0, dy)

    with h5py.File(coh_file, "r") as hf:
        coh = hf["temporalCoherence"][:]

    log.info("Loaded time series: shape=%s, T=%d dates, coherence shape=%s", ts.shape, len(dates), coh.shape)
    return ts.astype(np.float32), np.array(dates), coh.astype(np.float32), transform


# ──────────────────────────────────────────────────────────────────────────────
# STL decomposition
# ──────────────────────────────────────────────────────────────────────────────

def _stl_decompose(series: np.ndarray, period: int = 12) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Decompose a 1-D time series via STL.
    period=12 assumes ~monthly cadence (6-day repeat → ~12 obs/season).
    Returns trend, seasonal, residual arrays of same length.
    """
    try:
        stl = STL(series, period=period, robust=True)
        res = stl.fit()
        return res.trend, res.seasonal, res.resid
    except Exception:
        # Fall back to simple linear trend if STL fails (e.g. too few points)
        t = np.arange(len(series), dtype=float)
        slope, intercept = np.polyfit(t, series, 1)
        trend = slope * t + intercept
        return trend, np.zeros_like(series), series - trend


def extract_features(series: np.ndarray, dates: np.ndarray, period: int = 12) -> PixelFeatures:
    """Extract anomaly-relevant features from one pixel's time series."""
    import ruptures as rpt

    feat = PixelFeatures()

    if np.all(series == 0) or np.isnan(series).all():
        return feat

    # Fill isolated NaNs by linear interpolation
    valid = ~np.isnan(series)
    if valid.sum() < 6:
        return feat
    if not valid.all():
        x = np.arange(len(series))
        series = np.interp(x, x[valid], series[valid])

    trend, seasonal, residual = _stl_decompose(series, period=period)

    # Residual variance
    feat.residual_variance = float(np.var(residual))

    # Seasonal amplitude (peak-to-peak)
    feat.seasonal_amplitude = float(np.ptp(seasonal))

    # Trend magnitude: fit linear to trend component
    t = np.arange(len(trend), dtype=float)
    if len(t) > 2:
        slope, _ = np.polyfit(t, trend, 1)
        # Convert slope (mm/obs) → mm/yr assuming ~6-day cadence
        obs_per_year = 365.0 / 6.0
        feat.trend_magnitude = abs(float(slope) * obs_per_year)

        # Trend acceleration: curvature of second-order fit
        coeffs = np.polyfit(t, trend, 2)
        feat.trend_acceleration = abs(float(coeffs[0]) * obs_per_year**2)

    # Change point detection on the residual using PELT
    try:
        model = rpt.Pelt(model="rbf", min_size=4, jump=2).fit(residual.reshape(-1, 1))
        bkps = model.predict(pen=3.0)  # penalty controls sensitivity

        if len(bkps) > 1:  # at least one interior break
            cp_idx = bkps[-2]  # last break before end
            # Score = cost improvement normalised by series length
            baseline_cost = float(np.var(residual) * len(residual))
            before = residual[:cp_idx]
            after  = residual[cp_idx:]
            segmented_cost = float(np.var(before) * len(before) + np.var(after) * len(after))
            if baseline_cost > 0:
                feat.cp_score = max(0.0, 1.0 - segmented_cost / baseline_cost)
            feat.cp_date_idx = cp_idx
    except Exception:
        pass

    return feat


# ──────────────────────────────────────────────────────────────────────────────
# Batch feature extraction
# ──────────────────────────────────────────────────────────────────────────────

def extract_all_features(
    ts: np.ndarray,
    dates: np.ndarray,
    coh: np.ndarray,
    min_coherence: float = 0.4,
    period: int = 12,
) -> tuple[np.ndarray, list[tuple[int, int]], list[PixelFeatures]]:
    """
    Extract features for all valid pixels.

    Returns
    -------
    feature_matrix : (N_valid, 5)  float32
    pixel_indices  : [(row, col), ...]  length N_valid
    feature_list   : [PixelFeatures, ...]  length N_valid
    """
    T, rows, cols = ts.shape
    feature_names = ["residual_variance", "trend_magnitude", "seasonal_amplitude", "trend_acceleration", "cp_score"]

    pixel_indices: list[tuple[int, int]] = []
    feature_list: list[PixelFeatures] = []

    mask = coh >= min_coherence
    valid_pixels = list(zip(*np.where(mask)))
    log.info("Extracting features for %d coherent pixels (of %d total) ...", len(valid_pixels), rows * cols)

    for row, col in tqdm(valid_pixels, desc="Feature extraction", unit="px"):
        series = ts[:, row, col].astype(float)
        feat = extract_features(series, dates, period=period)
        pixel_indices.append((int(row), int(col)))
        feature_list.append(feat)

    feature_matrix = np.array(
        [
            [f.residual_variance, f.trend_magnitude, f.seasonal_amplitude, f.trend_acceleration, f.cp_score]
            for f in feature_list
        ],
        dtype=np.float32,
    )

    log.info("Feature matrix shape: %s", feature_matrix.shape)
    return feature_matrix, pixel_indices, feature_list


# ──────────────────────────────────────────────────────────────────────────────
# Isolation Forest scoring
# ──────────────────────────────────────────────────────────────────────────────

def compute_anomaly_scores(feature_matrix: np.ndarray, contamination: float = 0.05) -> np.ndarray:
    """
    Fit Isolation Forest and return anomaly scores in [0, 1].

    IsolationForest.score_samples returns negative values where more negative
    = more anomalous. We remap to [0, 1] with 1 = most anomalous.
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

    raw_scores = clf.score_samples(X)   # more negative → more anomalous
    # Normalise to [0, 1]
    lo, hi = raw_scores.min(), raw_scores.max()
    if hi > lo:
        scores = 1.0 - (raw_scores - lo) / (hi - lo)
    else:
        scores = np.zeros_like(raw_scores)

    return scores.astype(np.float32)


# ──────────────────────────────────────────────────────────────────────────────
# Rule-based labelling
# ──────────────────────────────────────────────────────────────────────────────

def _percentile_thresholds(feature_list: list[PixelFeatures], p: float = 90) -> dict:
    """Compute distribution-based thresholds for each feature."""
    return {
        "residual_variance":   float(np.percentile([f.residual_variance   for f in feature_list], p)),
        "trend_magnitude":     float(np.percentile([f.trend_magnitude     for f in feature_list], p)),
        "seasonal_amplitude":  float(np.percentile([f.seasonal_amplitude  for f in feature_list], p)),
        "trend_acceleration":  float(np.percentile([f.trend_acceleration  for f in feature_list], p)),
        "cp_score":            0.25,   # absolute threshold for change-point significance
    }


def assign_labels(
    feat: PixelFeatures,
    thresholds: dict,
    dates: np.ndarray,
) -> list[str]:
    """Return a list of human-readable reason strings for a flagged pixel."""
    labels: list[str] = []

    if feat.residual_variance > thresholds["residual_variance"]:
        labels.append("High residual variance — signal not explained by trend or seasonality")

    if feat.trend_magnitude > thresholds["trend_magnitude"]:
        direction = "subsidence" if feat.trend_magnitude < 0 else "uplift/inflation"
        labels.append(f"Rapid {direction} ({feat.trend_magnitude:.1f} mm/yr LOS rate)")

    if feat.seasonal_amplitude > thresholds["seasonal_amplitude"]:
        labels.append(f"Strong seasonal signal ({feat.seasonal_amplitude:.1f} mm peak-to-peak)")

    if feat.cp_score > thresholds["cp_score"] and feat.cp_date_idx is not None:
        if feat.cp_date_idx < len(dates):
            raw = dates[feat.cp_date_idx]
            date_str = f"{raw[:4]}-{raw[4:6]}-{raw[6:]}" if len(raw) == 8 else raw
            labels.append(f"Change point detected near {date_str}")

    if feat.trend_acceleration > thresholds["trend_acceleration"]:
        labels.append("Accelerating deformation rate")

    return labels


# ──────────────────────────────────────────────────────────────────────────────
# Output
# ──────────────────────────────────────────────────────────────────────────────

def build_output_arrays(
    ts_shape: tuple,
    pixel_indices: list[tuple[int, int]],
    scores: np.ndarray,
    feature_list: list[PixelFeatures],
    dates: np.ndarray,
    anomaly_threshold: float = 0.65,
) -> tuple[np.ndarray, dict]:
    """
    Build:
      score_raster : (rows, cols) float32,  NaN where no coherent data
      label_dict   : {row_col: {score, labels, change_point_date}}
    """
    T, rows, cols = ts_shape
    score_raster = np.full((rows, cols), np.nan, dtype=np.float32)

    thresholds = _percentile_thresholds(feature_list)

    label_dict: dict = {}

    for i, (row, col) in enumerate(pixel_indices):
        score = float(scores[i])
        score_raster[row, col] = score

        if score >= anomaly_threshold:
            feat = feature_list[i]
            labels = assign_labels(feat, thresholds, dates)

            cp_date = None
            if feat.cp_date_idx is not None and feat.cp_date_idx < len(dates):
                raw = dates[feat.cp_date_idx]
                cp_date = f"{raw[:4]}-{raw[4:6]}-{raw[6:]}" if len(raw) == 8 else raw

            label_dict[f"{row}_{col}"] = {
                "score": round(score, 4),
                "labels": labels,
                "change_point_date": cp_date,
            }

    log.info("Flagged %d pixels (score ≥ %.2f).", len(label_dict), anomaly_threshold)
    return score_raster, label_dict


def save_outputs(
    output_dir: Path,
    score_raster: np.ndarray,
    label_dict: dict,
    ts: np.ndarray,
    dates: np.ndarray,
    transform: tuple,
    coh: np.ndarray,
) -> None:
    """Save all outputs to disk for use by export_cogs.py."""
    output_dir.mkdir(parents=True, exist_ok=True)

    np.save(output_dir / "anomaly_score.npy", score_raster)
    log.info("Saved anomaly_score.npy  shape=%s", score_raster.shape)

    labels_path = output_dir / "labels.json"
    with open(labels_path, "w") as f:
        json.dump(label_dict, f, indent=2)
    log.info("Saved labels.json  (%d anomalous pixels)", len(label_dict))

    # Save geotransform and date info for downstream scripts
    meta = {
        "transform": list(transform),
        "shape": {"T": int(ts.shape[0]), "rows": int(ts.shape[1]), "cols": int(ts.shape[2])},
        "dates": list(dates),
        "crs": "EPSG:4326",
    }
    with open(output_dir / "meta.json", "w") as f:
        json.dump(meta, f, indent=2)
    log.info("Saved meta.json")


# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────

@click.command()
@click.option("--mintpy-dir",  required=True, type=click.Path(exists=True, path_type=Path))
@click.option("--output-dir",  required=True, type=click.Path(path_type=Path))
@click.option("--config",      required=True, type=click.Path(exists=True, path_type=Path))
@click.option("--contamination", default=0.05, show_default=True, help="Expected fraction of anomalous pixels (IsolationForest)")
@click.option("--anomaly-threshold", default=0.65, show_default=True, help="Score cutoff for label assignment")
@click.option("--period", default=12, show_default=True, help="STL seasonal period in observations (~12 for 6-day repeat Sentinel-1)")
def main(
    mintpy_dir: Path,
    output_dir: Path,
    config: Path,
    contamination: float,
    anomaly_threshold: float,
    period: int,
) -> None:
    """Run ML anomaly detection on MintPy time series outputs."""
    cfg = load_config(config)
    min_coh = cfg["mintpy"].get("min_coherence", 0.4)

    ts, dates, coh, transform = load_timeseries(mintpy_dir)
    feature_matrix, pixel_indices, feature_list = extract_all_features(
        ts, dates, coh, min_coherence=min_coh, period=period
    )

    if len(pixel_indices) == 0:
        log.error("No coherent pixels found. Check your coherence threshold.")
        return

    log.info("Scoring anomalies with Isolation Forest ...")
    scores = compute_anomaly_scores(feature_matrix, contamination=contamination)

    score_raster, label_dict = build_output_arrays(
        ts.shape, pixel_indices, scores, feature_list, dates, anomaly_threshold
    )

    save_outputs(output_dir, score_raster, label_dict, ts, dates, transform, coh)
    log.info("Anomaly detection complete. Results in %s", output_dir)


def load_config(config_path: Path) -> dict:
    with open(config_path) as f:
        return yaml.safe_load(f)


if __name__ == "__main__":
    main()
