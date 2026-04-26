"""
Prometheus exposition format adapter.

Parses the standard Prometheus text exposition format into the common
metrics dict consumed by the core analysis engine.

Handles:
  - ``# TYPE`` annotations to classify counter / gauge / histogram / summary
  - ``# HELP`` annotations (captured in metadata)
  - Label sets like ``metric{key="val",key2="val2"} value timestamp``
  - Histogram bucket filtering (``_bucket`` lines skipped by default)
  - Multi-scrape files (multiple timestamp columns)

Reference: https://prometheus.io/docs/instrumenting/exposition_formats/
"""

from __future__ import annotations

import io
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_LABEL_RE = re.compile(r'^([a-zA-Z_:][a-zA-Z0-9_:]*)\{(.+)\}\s+')
_SIMPLE_RE = re.compile(r'^([a-zA-Z_:][a-zA-Z0-9_:]*)\s+')


def read_prometheus(
    source: str | Path | io.TextIOBase,
    *,
    skip_buckets: bool = True,
    metric_filter: list[str] | None = None,
) -> dict[str, Any]:
    """Read a Prometheus exposition-format file.

    Args:
        source: file path or file-like object.
        skip_buckets: if True (default), skip histogram ``_bucket`` lines.
        metric_filter: if provided, only include metrics whose base name
            contains one of these substrings (case-insensitive).

    Returns:
        dict with keys:
            metrics:      {metric_name: [float values across timestamps]}
            timestamps:   [epoch_seconds] (deduplicated, sorted)
            metadata:     {source, adapter, metric_count, sample_count, ...}
            metric_types: {metric_name: "counter"|"gauge"|"histogram"|"summary"|"untyped"}
    """
    if isinstance(source, (str, Path)):
        path = Path(source)
        text = path.read_text(encoding="utf-8-sig")
        source_name = str(path)
    else:
        text = source.read()
        source_name = getattr(source, "name", "<stream>")

    type_map: dict[str, str] = {}       # base_name -> type
    help_map: dict[str, str] = {}       # base_name -> help text
    series: dict[str, dict[str, float]] = defaultdict(dict)  # {metric: {ts: value}}
    all_timestamps: set[str] = set()

    filter_lower = [f.lower() for f in metric_filter] if metric_filter else None

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue

        if line.startswith("# TYPE "):
            parts = line[7:].split(None, 1)
            if len(parts) == 2:
                type_map[parts[0]] = parts[1].strip().lower()
            continue

        if line.startswith("# HELP "):
            parts = line[7:].split(None, 1)
            if len(parts) == 2:
                help_map[parts[0]] = parts[1].strip()
            continue

        if line.startswith("#"):
            continue

        name, value_str, ts_str = _parse_data_line(line)
        if name is None:
            continue

        base_name = _base_metric_name(name)

        if skip_buckets and "_bucket{" in name:
            continue

        if filter_lower and not any(f in base_name.lower() for f in filter_lower):
            continue

        try:
            value = float(value_str)
        except (ValueError, TypeError):
            continue

        if ts_str:
            all_timestamps.add(ts_str)
            series[name][ts_str] = value
        else:
            series[name]["0"] = value

    sorted_ts = sorted(all_timestamps)
    ts_to_idx = {ts: i for i, ts in enumerate(sorted_ts)}

    metrics: dict[str, list[float]] = {}
    resolved_types: dict[str, str] = {}

    for name in sorted(series):
        ts_values = series[name]
        if not ts_values:
            continue

        if sorted_ts:
            values = []
            for ts in sorted_ts:
                if ts in ts_values:
                    values.append(ts_values[ts])
            if not values:
                continue
        else:
            values = list(ts_values.values())

        metrics[name] = values

        prom_type = "untyped"
        for candidate in _type_lookup_names(name):
            if candidate in type_map:
                prom_type = type_map[candidate]
                break
        resolved_types[name] = prom_type

    timestamps_float = []
    if sorted_ts and sorted_ts[0] != "0":
        for ts in sorted_ts:
            try:
                ts_f = float(ts)
                if ts_f > 1e12:
                    ts_f /= 1000.0
                timestamps_float.append(ts_f)
            except ValueError:
                pass

    time_range = None
    if timestamps_float:
        time_range = {
            "start": datetime.fromtimestamp(
                min(timestamps_float), tz=timezone.utc
            ).isoformat(),
            "end": datetime.fromtimestamp(
                max(timestamps_float), tz=timezone.utc
            ).isoformat(),
            "duration_seconds": max(timestamps_float) - min(timestamps_float),
            "samples": len(timestamps_float),
        }

    return {
        "metrics": metrics,
        "timestamps": timestamps_float if timestamps_float else None,
        "metadata": {
            "source": source_name,
            "adapter": "prometheus",
            "metric_count": len(metrics),
            "sample_count": len(sorted_ts),
            "time_range": time_range,
            "metric_types_declared": len(type_map),
        },
        "metric_types": resolved_types,
    }


def _parse_data_line(line: str) -> tuple[str | None, str | None, str | None]:
    """Parse a Prometheus data line into (metric_name, value, timestamp|None)."""
    m = _LABEL_RE.match(line)
    if m:
        base = m.group(1)
        labels = m.group(2)
        rest = line[m.end():].strip()
        name = f"{base}{{{labels}}}"
    else:
        m = _SIMPLE_RE.match(line)
        if not m:
            return None, None, None
        name = m.group(1)
        rest = line[m.end():].strip()

    parts = rest.split(None, 1)
    if not parts:
        return None, None, None

    value_str = parts[0]
    ts_str = parts[1].strip() if len(parts) > 1 else None
    return name, value_str, ts_str


def _base_metric_name(full_name: str) -> str:
    """Extract the base metric name, stripping labels and histogram/summary suffixes."""
    idx = full_name.find("{")
    base = full_name[:idx] if idx != -1 else full_name
    for suffix in ("_bucket", "_count", "_sum", "_total"):
        if base.endswith(suffix):
            return base[: -len(suffix)]
    return base


def _type_lookup_names(full_name: str) -> list[str]:
    """Return candidate keys to look up in the TYPE map.

    Prometheus TYPE declarations may use the full name (``http_requests_total``)
    or the base name (``http_requests``).  Also handles labeled metrics.
    """
    idx = full_name.find("{")
    without_labels = full_name[:idx] if idx != -1 else full_name
    candidates = [without_labels]
    for suffix in ("_total", "_count", "_sum", "_bucket"):
        if without_labels.endswith(suffix):
            candidates.append(without_labels[: -len(suffix)])
    base = _base_metric_name(full_name)
    if base not in candidates:
        candidates.append(base)
    return candidates
