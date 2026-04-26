"""Tests for core.compare -- regression detection across metric datasets."""

import pytest

from core.compare import build_comparison, compare_metrics
from core.polarity import PolarityConfig


@pytest.fixture
def simple_config():
    return PolarityConfig(
        higher_is_better=["throughput."],
        lower_is_better=["latency."],
        neutral=["info."],
        priority_prefixes=["throughput."],
        counter_prefixes=[],
    )


class TestBuildComparison:
    def test_gauge_comparison(self):
        baseline = [10.0, 12.0, 11.0, 13.0, 10.5] * 10
        current = [20.0, 22.0, 21.0, 23.0, 20.5] * 10
        result = build_comparison(
            "throughput.ops", baseline, current,
            is_counter=False, polarity="higher_is_better", priority=True,
        )
        assert result is not None
        assert result["key"] == "throughput.ops"
        assert result["type"] == "gauge"
        assert result["mean_change_pct"] > 0  # values roughly doubled
        assert result["priority"] is True

    def test_counter_comparison(self):
        baseline = list(range(0, 1000, 10))
        current = list(range(0, 2000, 20))
        result = build_comparison(
            "ops.total", baseline, current,
            is_counter=True, polarity="higher_is_better", priority=False,
        )
        assert result is not None
        assert result["type"] == "counter (rate/s)"

    def test_empty_baseline_returns_none(self):
        result = build_comparison(
            "metric", [], [1, 2, 3],
            is_counter=False, polarity="neutral", priority=False,
        )
        assert result is None

    def test_all_sentinels_returns_none(self):
        sentinels = [2**63] * 10
        result = build_comparison(
            "metric", sentinels, [1, 2, 3],
            is_counter=False, polarity="neutral", priority=False,
        )
        assert result is None

    def test_priority_boosts_severity(self):
        values = list(range(50))
        r_priority = build_comparison(
            "a", values, [v * 2 for v in values],
            is_counter=False, polarity="neutral", priority=True,
        )
        r_normal = build_comparison(
            "b", values, [v * 2 for v in values],
            is_counter=False, polarity="neutral", priority=False,
        )
        assert r_priority["severity"] > r_normal["severity"]


class TestCompareMetrics:
    def test_detects_regression(self, simple_config):
        baseline = {"throughput.ops": [100.0] * 50}
        current = {"throughput.ops": [50.0] * 50}  # throughput halved.
        result = compare_metrics(baseline, current, simple_config, threshold=5.0)
        assert len(result["regressions"]) == 1
        assert result["regressions"][0]["key"] == "throughput.ops"

    def test_detects_improvement(self, simple_config):
        baseline = {"latency.p99": [100.0] * 50}
        current = {"latency.p99": [50.0] * 50}  # latency halved = good.
        result = compare_metrics(baseline, current, simple_config, threshold=5.0)
        assert len(result["improvements"]) == 1
        assert result["improvements"][0]["key"] == "latency.p99"

    def test_stable_within_threshold(self, simple_config):
        baseline = {"throughput.ops": [100.0] * 50}
        current = {"throughput.ops": [101.0] * 50}  # ~1% change.
        result = compare_metrics(baseline, current, simple_config, threshold=5.0)
        assert len(result["regressions"]) == 0
        assert len(result["improvements"]) == 0
        assert len(result["significant"]) == 0

    def test_tracks_added_removed_metrics(self, simple_config):
        baseline = {"throughput.ops": [100.0] * 50, "old.metric": [1.0] * 50}
        current = {"throughput.ops": [100.0] * 50, "new.metric": [1.0] * 50}
        result = compare_metrics(baseline, current, simple_config, threshold=5.0)
        assert "old.metric" in result["baseline_only"]
        assert "new.metric" in result["current_only"]

    def test_key_filter(self, simple_config):
        baseline = {
            "throughput.ops": [100.0] * 50,
            "latency.p99": [100.0] * 50,
        }
        current = {
            "throughput.ops": [50.0] * 50,
            "latency.p99": [200.0] * 50,
        }
        result = compare_metrics(
            baseline, current, simple_config, threshold=5.0,
            key_filter=lambda k: "throughput" in k,
        )
        assert len(result["comparisons"]) == 1
        assert result["comparisons"][0]["key"] == "throughput.ops"

    def test_multiple_metrics_sorted_by_severity(self, simple_config):
        baseline = {
            "throughput.a": [100.0] * 50,
            "throughput.b": [100.0] * 50,
        }
        current = {
            "throughput.a": [50.0] * 50,   # -50%.
            "throughput.b": [90.0] * 50,   # -10%.
        }
        result = compare_metrics(baseline, current, simple_config, threshold=5.0)
        assert len(result["comparisons"]) == 2
        assert result["comparisons"][0]["key"] == "throughput.a"  # higher severity first

    def test_empty_datasets(self, simple_config):
        result = compare_metrics({}, {}, simple_config)
        assert len(result["comparisons"]) == 0
        assert len(result["shared_keys"]) == 0
