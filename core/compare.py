"""
Regression detection: compare baseline vs candidate metric datasets.

Accepts generic metric dicts ({metric_name: [values, ...]}) and a
PolarityConfig, producing structured comparison results suitable for
report generation or direct LLM consumption.
"""

from __future__ import annotations

from typing import Any, Sequence

from .metrics import compute_rates, compute_stats, filter_sentinels, pct_change
from .polarity import PolarityConfig, get_polarity, is_improvement, is_priority, is_regression


def build_comparison(
    key: str,
    baseline_values: Sequence[float],
    candidate_values: Sequence[float],
    is_counter: bool,
    polarity: str,
    priority: bool,
) -> dict[str, Any] | None:
    """Build a single metric comparison record.

    Returns None if either side has no usable data after filtering/rates.
    """
    b_vals = filter_sentinels(baseline_values)
    c_vals = filter_sentinels(candidate_values)
    if len(b_vals) == 0 or len(c_vals) == 0:
        return None

    metric_type = "gauge"
    if is_counter:
        b_vals = compute_rates(b_vals)
        c_vals = compute_rates(c_vals)
        if len(b_vals) == 0 or len(c_vals) == 0:
            return None
        metric_type = "counter (rate/s)"

    b_stats = compute_stats(b_vals)
    c_stats = compute_stats(c_vals)
    if b_stats is None or c_stats is None:
        return None

    mean_chg = pct_change(b_stats["mean"], c_stats["mean"])
    p95_chg = pct_change(b_stats["p95"], c_stats["p95"])
    max_chg = pct_change(b_stats["max"], c_stats["max"])

    severity = abs(mean_chg) * 0.5 + abs(p95_chg) * 0.3 + abs(max_chg) * 0.2
    if priority:
        severity *= 2.0

    return {
        "key": key,
        "type": metric_type,
        "polarity": polarity,
        "baseline": b_stats,
        "candidate": c_stats,
        "mean_change_pct": mean_chg,
        "p95_change_pct": p95_chg,
        "max_change_pct": max_chg,
        "severity": severity,
        "priority": priority,
    }


def compare_metrics(
    baseline: dict[str, list[float]],
    candidate: dict[str, list[float]],
    config: PolarityConfig,
    threshold: float = 5.0,
    key_filter: callable | None = None,
    metric_types: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Compare two metric datasets and classify regressions/improvements.

    Args:
        baseline: {metric_name: [values]} for the known-good run.
        candidate: {metric_name: [values]} for the run under test.
        config: PolarityConfig defining metric directions and counter prefixes.
        threshold: minimum % change to flag as significant.
        key_filter: optional callable(key) -> bool to include/exclude metrics.
        metric_types: optional {metric_name: "counter"|"gauge"|...} from adapters
            that natively know the type. Overrides heuristic counter detection.

    Returns dict with keys: comparisons, significant, regressions,
    improvements, shared_keys, baseline_only, candidate_only.
    """
    from .metrics import is_likely_counter

    shared_keys = set(baseline) & set(candidate)
    baseline_only = set(baseline) - set(candidate)
    candidate_only = set(candidate) - set(baseline)

    comparisons: list[dict[str, Any]] = []
    for key in sorted(shared_keys):
        if key_filter and not key_filter(key):
            continue

        b_values = baseline[key]
        c_values = candidate[key]

        if metric_types and key in metric_types:
            counter = metric_types[key] == "counter"
        else:
            counter = is_likely_counter(
                b_values, known_counter_prefixes=config.counter_prefixes, key=key
            ) or is_likely_counter(
                c_values, known_counter_prefixes=config.counter_prefixes, key=key
            )

        polarity = get_polarity(key, config)
        priority = is_priority(key, config)

        comp = build_comparison(key, b_values, c_values, counter, polarity, priority)
        if comp is not None:
            comparisons.append(comp)

    comparisons.sort(key=lambda x: x["severity"], reverse=True)

    significant = [
        c
        for c in comparisons
        if abs(c["mean_change_pct"]) >= threshold or abs(c["p95_change_pct"]) >= threshold
    ]
    regressions = [c for c in significant if is_regression(c)]
    improvements = [c for c in significant if is_improvement(c)]

    return {
        "comparisons": comparisons,
        "significant": significant,
        "regressions": regressions,
        "improvements": improvements,
        "shared_keys": shared_keys,
        "baseline_only": baseline_only,
        "candidate_only": candidate_only,
        "threshold": threshold,
    }
