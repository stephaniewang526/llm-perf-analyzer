"""
JSON adapter: parse metric data from various JSON structures.

Auto-detects the input shape and normalizes it into the common metrics dict.
Supported layouts:

1. **Nested perf-test format** -- array of test items, each with ``info.test_name``
   and a ``metrics`` array of ``{name, value}`` objects. Common for CI systems
   that export one JSON file per run with multiple scenarios.

2. **Time-series rows** -- array of flat objects where each object is one
   sample (e.g. ``[{"ts": 1700000000, "cpu": 45, "mem": 72}, ...]``).

3. **Metric-keyed arrays** -- dict mapping metric names to arrays of values
   (e.g. ``{"cpu": [45, 47, 52], "mem": [72, 73, 71]}``).

4. **Flat object** -- dict mapping metric names to single numeric values
   (e.g. ``{"cpu": 45.2, "mem": 72.1}``).
"""

from __future__ import annotations

import io
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def read_json(
    source: str | Path | io.TextIOBase,
    *,
    test_filter: list[str] | None = None,
    timestamp_key: str | None = None,
) -> dict[str, Any]:
    """Read a JSON file and return the common metrics dict format.

    Args:
        source: file path or file-like object.
        test_filter: for nested perf-test format, only include tests whose name
            contains one of these substrings (case-insensitive).
        timestamp_key: for time-series rows, the key holding the timestamp.
            Auto-detects common names if not specified.

    Returns:
        dict with keys:
            metrics:      {metric_name: [float values]}
            timestamps:   [epoch_seconds] or None
            metadata:     {source, adapter, metric_count, sample_count, ...}
            metric_types: {metric_name: type_string} (when available)
    """
    if isinstance(source, (str, Path)):
        path = Path(source)
        text = path.read_text(encoding="utf-8-sig")
        source_name = str(path)
    else:
        text = source.read()
        source_name = getattr(source, "name", "<stream>")

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        return _empty_result(source_name, error=str(e))

    if isinstance(data, list) and data and _looks_like_perf_test_item(data[0]):
        return _parse_perf_test_items(data, source_name, test_filter)

    if isinstance(data, dict) and "results" in data:
        results = data["results"]
        if isinstance(results, list) and results and _looks_like_perf_test_item(results[0]):
            return _parse_perf_test_items(results, source_name, test_filter,
                                           extra_metadata=_extract_top_level_meta(data))

    if isinstance(data, list) and data and isinstance(data[0], dict):
        return _parse_time_series_rows(data, source_name, timestamp_key)

    if isinstance(data, dict):
        first_val = next(iter(data.values()), None) if data else None
        if isinstance(first_val, list):
            return _parse_metric_arrays(data, source_name)
        return _parse_flat_object(data, source_name)

    return _empty_result(source_name)


def _looks_like_perf_test_item(item: Any) -> bool:
    """Check if a dict looks like a nested perf-test result row."""
    if not isinstance(item, dict):
        return False
    has_metrics = "metrics" in item and isinstance(item.get("metrics"), list)
    has_info = "info" in item
    return has_metrics and has_info


def _parse_perf_test_items(
    items: list[dict],
    source_name: str,
    test_filter: list[str] | None,
    extra_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Parse nested perf-test JSON (array of items with info + metrics)."""
    metrics: dict[str, list[float]] = {}
    metric_types: dict[str, str] = {}
    filter_lower = [f.lower() for f in test_filter] if test_filter else None
    test_count = 0

    for item in items:
        info = item.get("info", {})
        test_name = info.get("test_name", "unknown")

        if filter_lower and not any(f in test_name.lower() for f in filter_lower):
            continue

        test_count += 1
        args = info.get("args", info.get("arguments", {}))
        arg_suffix = ""
        if args:
            parts = [f"{k}={v}" for k, v in sorted(args.items())]
            arg_suffix = "." + ".".join(parts)

        for m in item.get("metrics", []):
            name = m.get("name", "")
            value = m.get("value")
            if value is None or name == "":
                continue
            try:
                val = float(value)
            except (ValueError, TypeError):
                continue

            key = f"{test_name}{arg_suffix}.{name}"
            metrics.setdefault(key, []).append(val)

            direction = (
                m.get("improvement_direction")
                or (m.get("metadata", {}) or {}).get("improvement_direction")
            )
            if direction == "up":
                metric_types[key] = "throughput"
            elif direction == "down":
                metric_types[key] = "latency"

            mtype = m.get("type")
            if mtype and key not in metric_types:
                metric_types[key] = mtype.lower()

    meta = {
        "source": source_name,
        "adapter": "json",
        "format": "perf_test_items",
        "metric_count": len(metrics),
        "sample_count": test_count,
        "time_range": None,
    }
    if extra_metadata:
        meta.update(extra_metadata)

    return {
        "metrics": metrics,
        "timestamps": None,
        "metadata": meta,
        "metric_types": metric_types,
    }


def _parse_time_series_rows(
    rows: list[dict],
    source_name: str,
    timestamp_key: str | None,
) -> dict[str, Any]:
    """Parse array-of-objects where each object is one timestamped sample."""
    ts_key = timestamp_key or _detect_timestamp_key(rows[0])
    metrics: dict[str, list[float]] = {}
    timestamps: list[float] = []

    for row in rows:
        if ts_key and ts_key in row:
            ts = _parse_ts(row[ts_key])
            if ts is not None:
                timestamps.append(ts)

        for k, v in row.items():
            if k == ts_key:
                continue
            try:
                val = float(v)
            except (ValueError, TypeError):
                continue
            metrics.setdefault(k, []).append(val)

    time_range = _build_time_range(timestamps)

    return {
        "metrics": metrics,
        "timestamps": timestamps if timestamps else None,
        "metadata": {
            "source": source_name,
            "adapter": "json",
            "format": "time_series_rows",
            "metric_count": len(metrics),
            "sample_count": len(rows),
            "time_range": time_range,
        },
        "metric_types": {},
    }


def _parse_metric_arrays(
    data: dict[str, list],
    source_name: str,
) -> dict[str, Any]:
    """Parse {metric_name: [values...]} format."""
    metrics: dict[str, list[float]] = {}
    for k, arr in data.items():
        if not isinstance(arr, list):
            continue
        values = []
        for v in arr:
            try:
                values.append(float(v))
            except (ValueError, TypeError):
                continue
        if values:
            metrics[k] = values

    sample_count = max((len(v) for v in metrics.values()), default=0)

    return {
        "metrics": metrics,
        "timestamps": None,
        "metadata": {
            "source": source_name,
            "adapter": "json",
            "format": "metric_arrays",
            "metric_count": len(metrics),
            "sample_count": sample_count,
            "time_range": None,
        },
        "metric_types": {},
    }


def _parse_flat_object(
    data: dict,
    source_name: str,
) -> dict[str, Any]:
    """Parse {metric_name: value} flat object."""
    metrics: dict[str, list[float]] = {}
    for k, v in data.items():
        try:
            metrics[k] = [float(v)]
        except (ValueError, TypeError):
            continue

    return {
        "metrics": metrics,
        "timestamps": None,
        "metadata": {
            "source": source_name,
            "adapter": "json",
            "format": "flat_object",
            "metric_count": len(metrics),
            "sample_count": 1 if metrics else 0,
            "time_range": None,
        },
        "metric_types": {},
    }


def _detect_timestamp_key(sample: dict) -> str | None:
    ts_names = ("timestamp", "time", "ts", "t", "date", "epoch",
                "created_at", "completed_at", "_time")
    for key in sample:
        if key.lower() in ts_names:
            return key
    return None


def _parse_ts(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 1e12:
            ts /= 1000.0
        return ts
    if isinstance(value, str):
        try:
            ts = float(value)
            if ts > 1e12:
                ts /= 1000.0
            return ts
        except ValueError:
            pass
        for fmt in (
            "%Y-%m-%dT%H:%M:%S.%f%z",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S.%fZ",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S",
        ):
            try:
                dt = datetime.strptime(value, fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.timestamp()
            except ValueError:
                continue
    return None


def _build_time_range(timestamps: list[float]) -> dict | None:
    if not timestamps:
        return None
    return {
        "start": datetime.fromtimestamp(
            min(timestamps), tz=timezone.utc
        ).isoformat(),
        "end": datetime.fromtimestamp(
            max(timestamps), tz=timezone.utc
        ).isoformat(),
        "duration_seconds": max(timestamps) - min(timestamps),
        "samples": len(timestamps),
    }


def _extract_top_level_meta(data: dict) -> dict[str, Any]:
    """Extract useful metadata from a top-level ``id`` block if present."""
    meta = {}
    id_block = data.get("id", {})
    if isinstance(id_block, dict):
        for key in ("project", "variant", "task_name", "version"):
            if key in id_block:
                meta[key] = id_block[key]
    return meta


def _empty_result(source_name: str, error: str | None = None) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "source": source_name,
        "adapter": "json",
        "metric_count": 0,
        "sample_count": 0,
        "time_range": None,
    }
    if error:
        meta["error"] = error
    return {
        "metrics": {},
        "timestamps": None,
        "metadata": meta,
        "metric_types": {},
    }
