"""
Structured markdown report generator for LLM-consumable performance analysis.

Produces reports with predictable sections, consistent tables, and
machine-parseable structure -- designed to maximize LLM analysis quality
over raw metric dumps.

Supports two modes:
  - Summary: single dataset statistics
  - Comparison: baseline vs candidate regression analysis
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Sequence

from .compare import compare_metrics
from .metrics import (
    compute_deltas,
    compute_stats,
    filter_sentinels,
    format_duration,
    format_number,
    is_monotonic_increasing,
)
from .polarity import (
    PolarityConfig,
    is_priority,
    polarity_label,
    verdict,
)

SCHEMA_VERSION = "1.0"


def generate_summary_report(
    metrics: dict[str, list[float]],
    config: PolarityConfig | None = None,
    metadata: dict[str, Any] | None = None,
    top_n: int = 50,
    metric_types: dict[str, str] | None = None,
) -> str:
    """Generate a structured summary report for a single metrics dataset.

    Args:
        metrics: {metric_name: [values]} from any adapter.
        config: polarity config for classification. If None, all metrics are neutral.
        metadata: optional dict with source, time_range, etc.
        top_n: max metrics to show in each section.
        metric_types: optional {metric_name: "counter"|"gauge"|...} from adapters
            that natively know the type (e.g. Prometheus). Overrides heuristic
            counter detection.
    """
    if config is None:
        config = PolarityConfig.empty()
    metadata = metadata or {}

    lines: list[str] = []

    _emit_schema_header(lines, "summary")
    _emit_metadata(lines, metadata)
    _emit_time_range(lines, metadata.get("time_range"))

    stats_by_key = _compute_all_stats(metrics, config, metric_types=metric_types)

    lines.append("## Metrics Overview")
    lines.append("")
    lines.append(f"- **Total metrics**: {len(stats_by_key)}")
    lines.append("")

    priority_stats = {k: v for k, v in stats_by_key.items() if is_priority(k, config)}
    if priority_stats:
        _emit_stats_table(lines, "Priority Metrics", priority_stats, top_n)

    _emit_stats_table(lines, f"All Metrics (top {min(top_n, len(stats_by_key))} by mean)", stats_by_key, top_n)

    _emit_data_sources(lines, metadata)

    return "\n".join(lines)


def generate_comparison_report(
    baseline: dict[str, list[float]],
    candidate: dict[str, list[float]],
    config: PolarityConfig | None = None,
    threshold: float = 5.0,
    baseline_metadata: dict[str, Any] | None = None,
    candidate_metadata: dict[str, Any] | None = None,
    top_n: int = 50,
    metric_types: dict[str, str] | None = None,
) -> str:
    """Generate a structured comparison report: baseline vs candidate.

    Args:
        baseline: {metric_name: [values]} for the known-good run.
        candidate: {metric_name: [values]} for the run under test.
        config: polarity config. If None, all metrics are neutral.
        threshold: minimum % change to flag as significant.
        baseline_metadata: optional metadata for baseline.
        candidate_metadata: optional metadata for candidate.
        top_n: max metrics per section.
        metric_types: optional {metric_name: "counter"|"gauge"|...} from adapters
            that natively know the type. Overrides heuristic counter detection.
    """
    if config is None:
        config = PolarityConfig.empty()
    baseline_metadata = baseline_metadata or {}
    candidate_metadata = candidate_metadata or {}

    result = compare_metrics(baseline, candidate, config, threshold,
                             metric_types=metric_types)

    lines: list[str] = []

    _emit_schema_header(lines, "comparison")
    _emit_comparison_metadata(lines, baseline_metadata, candidate_metadata)
    _emit_comparison_time_range(lines, baseline_metadata, candidate_metadata)
    _emit_verdict(lines, result, threshold)
    _emit_regressions(lines, result["regressions"], top_n)
    _emit_improvements(lines, result["improvements"], top_n)
    _emit_schema_changes(lines, result["baseline_only"], result["candidate_only"], result["shared_keys"])
    _emit_stable_priority(lines, result["comparisons"], threshold)
    _emit_full_comparison(lines, result["significant"], threshold)
    _emit_data_sources(lines, candidate_metadata)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _emit_schema_header(lines: list[str], report_type: str) -> None:
    lines.append("# Performance Analysis Report")
    lines.append("")
    lines.append("## Schema")
    lines.append("")
    lines.append("| Field | Value |")
    lines.append("|-------|-------|")
    lines.append(f"| schema_version | {SCHEMA_VERSION} |")
    lines.append("| format | llm-perf-result |")
    lines.append(f"| report_type | {report_type} |")
    lines.append(f"| generated_at | {datetime.now(timezone.utc).isoformat()} |")
    lines.append("")


def _emit_metadata(lines: list[str], metadata: dict[str, Any]) -> None:
    if not metadata:
        return
    display_keys = {k: v for k, v in metadata.items() if k not in ("time_range",) and v is not None}
    if not display_keys:
        return
    lines.append("## Metadata")
    lines.append("")
    lines.append("| Field | Value |")
    lines.append("|-------|-------|")
    for k, v in display_keys.items():
        lines.append(f"| {k} | {v} |")
    lines.append("")


def _emit_time_range(lines: list[str], time_range: dict | None) -> None:
    if not time_range:
        return
    lines.append("## Time Range")
    lines.append("")
    lines.append(f"- **Start**: {time_range.get('start', 'N/A')}")
    lines.append(f"- **End**: {time_range.get('end', 'N/A')}")
    dur = time_range.get("duration_seconds")
    lines.append(f"- **Duration**: {format_duration(dur)}")
    lines.append(f"- **Samples**: {time_range.get('samples', 'N/A'):,}")
    lines.append("")


def _emit_comparison_metadata(
    lines: list[str],
    baseline_meta: dict[str, Any],
    candidate_meta: dict[str, Any],
) -> None:
    lines.append("## Environment")
    lines.append("")
    lines.append("| | Baseline | Candidate |")
    lines.append("|---|----------|-----------|")
    all_keys = list(dict.fromkeys(
        [k for k in baseline_meta if k != "time_range"]
        + [k for k in candidate_meta if k != "time_range"]
    ))
    for k in all_keys:
        b_val = baseline_meta.get(k, "N/A")
        c_val = candidate_meta.get(k, "N/A")
        if b_val is not None and c_val is not None:
            lines.append(f"| {k} | {b_val} | {c_val} |")
    lines.append("")


def _emit_comparison_time_range(
    lines: list[str],
    baseline_meta: dict[str, Any],
    candidate_meta: dict[str, Any],
) -> None:
    b_tr = baseline_meta.get("time_range")
    c_tr = candidate_meta.get("time_range")
    if not b_tr and not c_tr:
        return
    lines.append("## Time Range")
    lines.append("")
    lines.append("| | Baseline | Candidate |")
    lines.append("|---|----------|-----------|")

    def _get(tr, key, default="N/A"):
        return tr.get(key, default) if tr else default

    lines.append(f"| start | {_get(b_tr, 'start')} | {_get(c_tr, 'start')} |")
    b_dur = format_duration(_get(b_tr, "duration_seconds", None))
    c_dur = format_duration(_get(c_tr, "duration_seconds", None))
    lines.append(f"| duration | {b_dur} | {c_dur} |")
    lines.append(f"| samples | {_get(b_tr, 'samples')} | {_get(c_tr, 'samples')} |")
    lines.append("")


def _emit_verdict(lines: list[str], result: dict, threshold: float) -> None:
    regressions = result["regressions"]
    improvements = result["improvements"]
    significant = result["significant"]
    comparisons = result["comparisons"]

    lines.append("## Overall Verdict")
    lines.append("")
    lines.append(f"- **Regressions**: {len(regressions)} metrics got worse")
    lines.append(f"- **Improvements**: {len(improvements)} metrics got better")
    lines.append(
        f"- **Significant changes**: {len(significant)} of {len(comparisons)} "
        f"metrics exceeded {threshold}% threshold"
    )
    lines.append("")

    if regressions:
        lines.append(
            "> **Action needed**: regressions detected in the candidate build. "
            "See details below."
        )
    elif improvements:
        lines.append(
            f"> **Candidate looks good**: no regressions detected; "
            f"{len(improvements)} metrics improved."
        )
    else:
        lines.append("> **No significant change** between baseline and candidate.")
    lines.append("")


def _emit_regressions(lines: list[str], regressions: list[dict], top_n: int) -> None:
    if not regressions:
        return
    lines.append(f"## Regressions ({len(regressions)} metrics got worse)")
    lines.append("")
    lines.append("| Metric | Category | Baseline Mean | Candidate Mean | Change | P95 Chg |")
    lines.append("|--------|----------|--------------|----------------|--------|---------|")
    for c in regressions[:top_n]:
        cat = polarity_label(c["polarity"])
        lines.append(
            f"| `{c['key']}` | {cat} "
            f"| {format_number(c['baseline']['mean'])} "
            f"| {format_number(c['candidate']['mean'])} "
            f"| {c['mean_change_pct']:+.1f}% "
            f"| {c['p95_change_pct']:+.1f}% |"
        )
    lines.append("")


def _emit_improvements(lines: list[str], improvements: list[dict], top_n: int) -> None:
    if not improvements:
        return
    lines.append(f"## Improvements ({len(improvements)} metrics got better)")
    lines.append("")
    lines.append("| Metric | Category | Baseline Mean | Candidate Mean | Change | P95 Chg |")
    lines.append("|--------|----------|--------------|----------------|--------|---------|")
    for c in improvements[:top_n]:
        cat = polarity_label(c["polarity"])
        lines.append(
            f"| `{c['key']}` | {cat} "
            f"| {format_number(c['baseline']['mean'])} "
            f"| {format_number(c['candidate']['mean'])} "
            f"| {c['mean_change_pct']:+.1f}% "
            f"| {c['p95_change_pct']:+.1f}% |"
        )
    lines.append("")


def _emit_schema_changes(
    lines: list[str],
    baseline_only: set[str],
    candidate_only: set[str],
    shared_keys: set[str],
) -> None:
    if not baseline_only and not candidate_only:
        return
    lines.append("## Schema Changes")
    lines.append("")
    lines.append(f"- **Shared metrics**: {len(shared_keys)}")
    lines.append(f"- **Removed in candidate**: {len(baseline_only)}")
    lines.append(f"- **Added in candidate**: {len(candidate_only)}")
    if candidate_only:
        lines.append("")
        lines.append("<details><summary>New metrics in candidate</summary>")
        lines.append("")
        for k in sorted(candidate_only)[:50]:
            lines.append(f"- `{k}`")
        lines.append("")
        lines.append("</details>")
    if baseline_only:
        lines.append("")
        lines.append("<details><summary>Removed metrics from baseline</summary>")
        lines.append("")
        for k in sorted(baseline_only)[:50]:
            lines.append(f"- `{k}`")
        lines.append("")
        lines.append("</details>")
    lines.append("")


def _emit_stable_priority(
    lines: list[str],
    comparisons: list[dict],
    threshold: float,
) -> None:
    stable = [
        c for c in comparisons
        if c.get("priority")
        and abs(c["mean_change_pct"]) < threshold
        and abs(c["p95_change_pct"]) < threshold
    ]
    if not stable:
        return
    lines.append(f"## Stable Priority Metrics (within {threshold}% threshold)")
    lines.append("")
    for c in stable[:30]:
        lines.append(
            f"- `{c['key']}`: mean "
            f"{format_number(c['baseline']['mean'])} -> "
            f"{format_number(c['candidate']['mean'])} "
            f"({c['mean_change_pct']:+.1f}%)"
        )
    lines.append("")


def _emit_full_comparison(lines: list[str], significant: list[dict], threshold: float) -> None:
    lines.append("<details><summary>Full comparison of all significant metrics</summary>")
    lines.append("")
    if significant:
        lines.append("| Metric | Category | B Mean | C Mean | Change | Verdict | B P95 | C P95 | P95 Chg |")
        lines.append("|--------|----------|--------|--------|--------|---------|-------|-------|---------|")
        for c in significant:
            v = verdict(c, threshold)
            cat = polarity_label(c["polarity"])
            lines.append(
                f"| `{c['key']}` | {cat} "
                f"| {format_number(c['baseline']['mean'])} "
                f"| {format_number(c['candidate']['mean'])} "
                f"| {c['mean_change_pct']:+.1f}% "
                f"| {v} "
                f"| {format_number(c['baseline']['p95'])} "
                f"| {format_number(c['candidate']['p95'])} "
                f"| {c['p95_change_pct']:+.1f}% |"
            )
    lines.append("")
    lines.append("</details>")
    lines.append("")


def _emit_stats_table(
    lines: list[str],
    title: str,
    stats_by_key: dict[str, dict],
    top_n: int,
) -> None:
    sorted_stats = sorted(stats_by_key.items(), key=lambda x: abs(x[1]["mean"]), reverse=True)
    lines.append(f"## {title}")
    lines.append("")
    lines.append("| Metric | Type | Mean | P50 | P95 | Max | StdDev |")
    lines.append("|--------|------|------|-----|-----|-----|--------|")
    for key, s in sorted_stats[:top_n]:
        lines.append(
            f"| `{key}` | {s['type']} | {format_number(s['mean'])} | "
            f"{format_number(s['median'])} | {format_number(s['p95'])} | "
            f"{format_number(s['max'])} | {format_number(s['stddev'])} |"
        )
    lines.append("")


def _emit_data_sources(lines: list[str], metadata: dict[str, Any]) -> None:
    source = metadata.get("source")
    if not source:
        return
    lines.append("## Data Sources")
    lines.append("")
    lines.append("| Source | Path |")
    lines.append("|--------|------|")
    lines.append(f"| input | {source} |")
    lines.append("")


def _compute_all_stats(
    metrics: dict[str, list[float]],
    config: PolarityConfig,
    metric_types: dict[str, str] | None = None,
) -> dict[str, dict]:
    """Compute stats for every metric, handling counters via rate conversion.

    When *metric_types* is provided (e.g. from a Prometheus adapter), it is
    used to determine counter vs gauge instead of the heuristic.
    """
    result = {}
    for key in sorted(metrics):
        values = filter_sentinels(metrics[key])
        if len(values) == 0:
            continue

        counter = _is_counter(key, values, config, metric_types)
        if counter:
            rate_values = compute_deltas(values)
            if len(rate_values) == 0:
                continue
            s = compute_stats(rate_values)
            if s is not None:
                s["type"] = "counter (rate/s)"
                result[key] = s
        else:
            s = compute_stats(values)
            if s is not None:
                s["type"] = "gauge"
                result[key] = s
    return result


def _is_counter(
    key: str,
    values: Sequence,
    config: PolarityConfig,
    metric_types: dict[str, str] | None,
) -> bool:
    """Check whether a metric is a counter, preferring declared types."""
    if metric_types and key in metric_types:
        return metric_types[key] == "counter"
    return is_monotonic_increasing(
        values, known_prefixes=config.counter_prefixes, key=key
    )
