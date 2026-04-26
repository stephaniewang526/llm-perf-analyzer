"""
Metric polarity classification and regression/improvement detection.

Polarity defines the "good" direction for a metric:
  - higher_is_better: throughput metrics (going UP is good)
  - lower_is_better: cost/resource metrics (going DOWN is good)
  - neutral: informational or context-dependent

Polarity rules are configurable via YAML or dict, so any observability
system can define its own rules without code changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class PolarityConfig:
    """Configurable polarity rules for metric classification.

    Rules are checked in order; first matching prefix wins.
    """

    higher_is_better: list[str] = field(default_factory=list)
    lower_is_better: list[str] = field(default_factory=list)
    neutral: list[str] = field(default_factory=list)

    # Optional: prefixes that mark a metric as "priority" for analysis
    priority_prefixes: list[str] = field(default_factory=list)

    # Optional: prefixes that identify cumulative counters needing rate computation
    counter_prefixes: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PolarityConfig:
        """Build from a dict (e.g. parsed YAML)."""
        return cls(
            higher_is_better=data.get("higher_is_better", []),
            lower_is_better=data.get("lower_is_better", []),
            neutral=data.get("neutral", []),
            priority_prefixes=data.get("priority_prefixes", []),
            counter_prefixes=data.get("counter_prefixes", []),
        )

    @classmethod
    def from_yaml(cls, path: str | Path) -> PolarityConfig:
        """Load polarity rules from a YAML file."""
        import yaml  # deferred so yaml isn't required unless using this method

        with open(path) as f:
            data = yaml.safe_load(f)
        return cls.from_dict(data)

    @classmethod
    def empty(cls) -> PolarityConfig:
        """Return a config with no rules (everything is neutral)."""
        return cls()


def get_polarity(key: str, config: PolarityConfig) -> str:
    """Return 'higher_is_better', 'lower_is_better', or 'neutral'."""
    for prefix in config.higher_is_better:
        if key.startswith(prefix):
            return "higher_is_better"
    for prefix in config.lower_is_better:
        if key.startswith(prefix):
            return "lower_is_better"
    for prefix in config.neutral:
        if key.startswith(prefix):
            return "neutral"
    return "neutral"


def is_priority(key: str, config: PolarityConfig) -> bool:
    """Return True if the metric matches a priority prefix."""
    for prefix in config.priority_prefixes:
        if key.startswith(prefix):
            return True
    return False


def is_regression(comparison: dict) -> bool:
    """True if this metric moved in the *bad* direction."""
    pol = comparison.get("polarity", "neutral")
    mean_chg = comparison["mean_change_pct"]
    if pol == "higher_is_better":
        return mean_chg < 0  # throughput dropped
    if pol == "lower_is_better":
        return mean_chg > 0  # cost increased
    return False


def is_improvement(comparison: dict) -> bool:
    """True if this metric moved in the *good* direction."""
    pol = comparison.get("polarity", "neutral")
    mean_chg = comparison["mean_change_pct"]
    if pol == "higher_is_better":
        return mean_chg > 0  # throughput increased
    if pol == "lower_is_better":
        return mean_chg < 0  # cost decreased
    return False


def verdict(comparison: dict, threshold: float) -> str:
    """Short verdict: REGRESSION / IMPROVEMENT / stable / changed."""
    if abs(comparison["mean_change_pct"]) < threshold:
        return "stable"
    if is_regression(comparison):
        return "REGRESSION"
    if is_improvement(comparison):
        return "IMPROVEMENT"
    return "changed"


def polarity_label(polarity: str) -> str:
    """Human-readable label for a polarity value."""
    return {
        "higher_is_better": "THROUGHPUT (higher is better)",
        "lower_is_better": "COST (lower is better)",
        "neutral": "INFO",
    }.get(polarity, "INFO")
