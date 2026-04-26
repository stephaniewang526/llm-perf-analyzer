"""
Statistical computation for numeric data.

All functions operate on generic numeric arrays with no dependency on any
specific data source or observability system.
"""

from __future__ import annotations

import math
from typing import Sequence

import numpy as np


# INT64_MAX-style sentinel values used by some systems as "no limit" / "not set".
# They badly skew statistics and should be filtered before analysis.
_SENTINEL_THRESHOLD = 2**62
_NEGATIVE_SENTINEL = -(2**62)


def filter_sentinels(values: Sequence[float]) -> np.ndarray:
    """Remove sentinel values (near INT64_MAX) and NaNs that would skew statistics."""
    arr = np.asarray(values, dtype=np.float64)
    mask = np.isfinite(arr) & (arr > _NEGATIVE_SENTINEL) & (arr < _SENTINEL_THRESHOLD)
    return arr[mask]


def compute_stats(values: Sequence[float]) -> dict | None:
    """Compute statistical summary for a list of numeric values.

    Returns dict with count, min, max, mean, median, p95, p99, stddev,
    or None if the input is empty.
    """
    arr = np.asarray(values, dtype=np.float64)
    if arr.size == 0:
        return None

    n = arr.size
    mean_val = float(np.mean(arr))
    stddev_val = float(np.std(arr, ddof=1)) if n > 1 else 0.0

    p50, p95, p99 = np.percentile(arr, [50, 95, 99]).tolist()

    return {
        "count": n,
        "min": float(np.min(arr)),
        "max": float(np.max(arr)),
        "mean": mean_val,
        "median": p50,
        "p95": p95,
        "p99": p99,
        "stddev": stddev_val,
    }


def compute_deltas(values: Sequence[float]) -> np.ndarray:
    """Compute per-sample deltas from a cumulative series.

    Negative deltas (e.g. counter resets) are clamped to zero.
    Returns an empty array when fewer than two values are provided.
    """
    arr = np.asarray(values, dtype=np.float64)
    if len(arr) < 2:
        return np.array([], dtype=np.float64)
    deltas = np.diff(arr)
    np.maximum(deltas, 0, out=deltas)
    return deltas


def is_monotonic_increasing(
    values: Sequence[float],
    known_prefixes: list[str] | None = None,
    key: str | None = None,
    min_samples: int = 10,
) -> bool:
    """Determine whether a series is monotonically non-decreasing.

    If *key* is provided and matches any prefix in *known_prefixes*,
    returns True immediately. Otherwise uses a heuristic: samples must
    be non-decreasing and the last value must exceed the first.

    *min_samples* controls the minimum number of data points required
    for the heuristic check (default 10).
    """
    if key and known_prefixes:
        for prefix in known_prefixes:
            if key.startswith(prefix):
                return True

    arr = np.asarray(values, dtype=np.float64)
    if arr.size < min_samples:
        return False
    step = max(1, arr.size // 100)
    sampled = arr[::step]
    if np.any(np.diff(sampled) < 0):
        return False
    return bool(arr[-1] > arr[0])


def percentile(sorted_values: list[float], p: float) -> float:
    """Compute the p-th percentile of a pre-sorted list using linear interpolation."""
    if not sorted_values:
        return 0.0
    k = (len(sorted_values) - 1) * (p / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_values[int(k)]
    return sorted_values[int(f)] * (c - k) + sorted_values[int(c)] * (k - f)


def pct_change(baseline: float, candidate: float) -> float:
    """Percentage change from *baseline* to *candidate*."""
    if baseline == 0:
        return 0.0 if candidate == 0 else float("inf")
    return ((candidate - baseline) / abs(baseline)) * 100.0


def format_number(n: float | int | None) -> str:
    """Format a number for compact, human-readable display."""
    if n is None:
        return "N/A"
    if isinstance(n, float) and (math.isnan(n) or math.isinf(n)):
        return str(n)
    abs_n = abs(n)
    if abs_n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.2f}B"
    if abs_n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if abs_n >= 1_000:
        return f"{n / 1_000:.1f}K"
    if isinstance(n, int):
        return str(n)
    if abs_n < 0.01 and n != 0:
        return f"{n:.4f}"
    if abs_n < 1:
        return f"{n:.3f}"
    return f"{n:.2f}"


def format_duration(seconds: float | None) -> str:
    """Human-readable duration string."""
    if seconds is None:
        return "N/A"
    if seconds > 3600:
        return f"{seconds / 3600:.1f}h"
    if seconds > 60:
        return f"{seconds / 60:.1f}m"
    return f"{seconds:.0f}s"
