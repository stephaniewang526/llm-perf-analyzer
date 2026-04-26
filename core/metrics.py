"""
Statistical computation for numeric metric data.

All functions operate on generic numeric arrays -- no dependency on any
specific observability system (Prometheus, custom JSON, etc.).
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
    """Remove sentinel values (near INT64_MAX) that would skew statistics."""
    arr = np.asarray(values, dtype=np.float64)
    mask = (arr > _NEGATIVE_SENTINEL) & (arr < _SENTINEL_THRESHOLD)
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

    return {
        "count": n,
        "min": float(np.min(arr)),
        "max": float(np.max(arr)),
        "mean": mean_val,
        "median": float(np.percentile(arr, 50)),
        "p95": float(np.percentile(arr, 95)),
        "p99": float(np.percentile(arr, 99)),
        "stddev": stddev_val,
    }


def compute_rates(values: Sequence[float]) -> np.ndarray:
    """Compute per-sample deltas from cumulative counter values.

    Negative deltas (counter resets) are clamped to zero.
    """
    arr = np.asarray(values, dtype=np.float64)
    if len(arr) < 2:
        return np.array([], dtype=np.float64)
    deltas = np.diff(arr)
    np.maximum(deltas, 0, out=deltas)
    return deltas


def is_likely_counter(
    values: Sequence[float],
    known_counter_prefixes: list[str] | None = None,
    key: str | None = None,
) -> bool:
    """Determine whether a metric is a cumulative counter.

    If *key* is provided and matches any prefix in *known_counter_prefixes*,
    returns True immediately. Otherwise uses a heuristic: monotonically
    non-decreasing with a meaningful range.
    """
    if key and known_counter_prefixes:
        for prefix in known_counter_prefixes:
            if key.startswith(prefix):
                return True

    arr = np.asarray(values, dtype=np.float64)
    if arr.size < 10:
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
