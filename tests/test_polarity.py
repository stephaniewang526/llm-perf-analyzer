"""Tests for core.polarity -- metric classification and regression detection."""

import pytest

from core.polarity import (
    PolarityConfig,
    get_polarity,
    is_improvement,
    is_priority,
    is_regression,
    polarity_label,
    verdict,
)


@pytest.fixture
def sample_config():
    return PolarityConfig(
        higher_is_better=["throughput.", "ops_per_sec"],
        lower_is_better=["latency.", "error_rate"],
        neutral=["connections.current"],
        priority_prefixes=["throughput.", "latency."],
        counter_prefixes=["throughput."],
    )


class TestPolarityConfig:
    def test_from_dict(self):
        data = {
            "higher_is_better": ["rate."],
            "lower_is_better": ["latency."],
            "neutral": ["info."],
            "priority_prefixes": ["rate."],
            "counter_prefixes": ["rate."],
        }
        config = PolarityConfig.from_dict(data)
        assert config.higher_is_better == ["rate."]
        assert config.lower_is_better == ["latency."]
        assert config.counter_prefixes == ["rate."]

    def test_from_dict_missing_keys(self):
        config = PolarityConfig.from_dict({})
        assert config.higher_is_better == []
        assert config.lower_is_better == []

    def test_empty(self):
        config = PolarityConfig.empty()
        assert config.higher_is_better == []
        assert config.priority_prefixes == []


class TestGetPolarity:
    def test_higher_is_better(self, sample_config):
        assert get_polarity("throughput.reads", sample_config) == "higher_is_better"

    def test_lower_is_better(self, sample_config):
        assert get_polarity("latency.p99", sample_config) == "lower_is_better"

    def test_neutral_explicit(self, sample_config):
        assert get_polarity("connections.current", sample_config) == "neutral"

    def test_neutral_default(self, sample_config):
        assert get_polarity("unknown.metric", sample_config) == "neutral"

    def test_first_match_wins(self):
        config = PolarityConfig(
            higher_is_better=["metric."],
            lower_is_better=["metric.sub."],
        )
        assert get_polarity("metric.sub.value", config) == "higher_is_better"


class TestIsPriority:
    def test_priority_match(self, sample_config):
        assert is_priority("throughput.reads", sample_config)

    def test_non_priority(self, sample_config):
        assert not is_priority("connections.current", sample_config)


class TestRegressionDetection:
    def test_throughput_regression(self):
        comp = {"polarity": "higher_is_better", "mean_change_pct": -15.0}
        assert is_regression(comp)
        assert not is_improvement(comp)

    def test_throughput_improvement(self):
        comp = {"polarity": "higher_is_better", "mean_change_pct": 15.0}
        assert not is_regression(comp)
        assert is_improvement(comp)

    def test_cost_regression(self):
        comp = {"polarity": "lower_is_better", "mean_change_pct": 20.0}
        assert is_regression(comp)
        assert not is_improvement(comp)

    def test_cost_improvement(self):
        comp = {"polarity": "lower_is_better", "mean_change_pct": -20.0}
        assert not is_regression(comp)
        assert is_improvement(comp)

    def test_neutral_never_regression(self):
        comp = {"polarity": "neutral", "mean_change_pct": 100.0}
        assert not is_regression(comp)
        assert not is_improvement(comp)

    def test_zero_change(self):
        comp = {"polarity": "higher_is_better", "mean_change_pct": 0.0}
        assert not is_regression(comp)
        assert not is_improvement(comp)


class TestVerdict:
    def test_below_threshold_is_stable(self):
        comp = {"polarity": "higher_is_better", "mean_change_pct": 3.0}
        assert verdict(comp, threshold=5.0) == "stable"

    def test_regression_verdict(self):
        comp = {"polarity": "higher_is_better", "mean_change_pct": -10.0}
        assert verdict(comp, threshold=5.0) == "REGRESSION"

    def test_improvement_verdict(self):
        comp = {"polarity": "lower_is_better", "mean_change_pct": -10.0}
        assert verdict(comp, threshold=5.0) == "IMPROVEMENT"

    def test_neutral_changed(self):
        comp = {"polarity": "neutral", "mean_change_pct": 50.0}
        assert verdict(comp, threshold=5.0) == "changed"


class TestPolarityLabel:
    def test_all_labels(self):
        assert polarity_label("higher_is_better") == "THROUGHPUT (higher is better)"
        assert polarity_label("lower_is_better") == "COST (lower is better)"
        assert polarity_label("neutral") == "INFO"
        assert polarity_label("unknown") == "INFO"
