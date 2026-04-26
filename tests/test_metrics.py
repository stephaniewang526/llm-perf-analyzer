"""Tests for core.metrics -- statistical computation."""

import math

import numpy as np
import pytest

from core.metrics import (
    compute_deltas,
    compute_stats,
    filter_sentinels,
    format_duration,
    format_number,
    is_monotonic_increasing,
    pct_change,
    percentile,
)


class TestFilterSentinels:
    def test_removes_large_sentinels(self):
        values = [1.0, 2.0, 2**63, 3.0]
        result = filter_sentinels(values)
        np.testing.assert_array_equal(result, [1.0, 2.0, 3.0])

    def test_removes_negative_sentinels(self):
        values = [1.0, -(2**63), 2.0]
        result = filter_sentinels(values)
        np.testing.assert_array_equal(result, [1.0, 2.0])

    def test_keeps_normal_values(self):
        values = [0, -100, 100, 999999]
        result = filter_sentinels(values)
        assert len(result) == 4

    def test_empty_input(self):
        result = filter_sentinels([])
        assert len(result) == 0


class TestComputeStats:
    def test_basic_stats(self):
        values = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        stats = compute_stats(values)
        assert stats is not None
        assert stats["count"] == 10
        assert stats["min"] == 1.0
        assert stats["max"] == 10.0
        assert stats["mean"] == pytest.approx(5.5)
        assert stats["median"] == pytest.approx(5.5)

    def test_single_value(self):
        stats = compute_stats([42])
        assert stats is not None
        assert stats["count"] == 1
        assert stats["mean"] == 42.0
        assert stats["stddev"] == 0.0

    def test_empty_returns_none(self):
        assert compute_stats([]) is None

    def test_percentiles(self):
        values = list(range(1, 101))
        stats = compute_stats(values)
        assert stats["p95"] == pytest.approx(95.05, abs=0.1)
        assert stats["p99"] == pytest.approx(99.01, abs=0.1)

    def test_stddev(self):
        values = [10, 10, 10, 10]
        stats = compute_stats(values)
        assert stats["stddev"] == 0.0


class TestComputeDeltas:
    def test_monotonic_series(self):
        values = [0, 10, 25, 50, 100]
        deltas = compute_deltas(values)
        np.testing.assert_array_equal(deltas, [10, 15, 25, 50])

    def test_negative_delta_clamped_to_zero(self):
        values = [100, 200, 50, 150]  # drop at index 2.
        deltas = compute_deltas(values)
        np.testing.assert_array_equal(deltas, [100, 0, 100])

    def test_single_value_returns_empty(self):
        deltas = compute_deltas([42])
        assert len(deltas) == 0

    def test_empty_returns_empty(self):
        deltas = compute_deltas([])
        assert len(deltas) == 0


class TestIsMonotonicIncreasing:
    def test_known_prefix_match(self):
        values = list(range(100))
        assert is_monotonic_increasing(
            values,
            known_prefixes=["requests_total."],
            key="requests_total.api",
        )

    def test_monotonic_heuristic(self):
        values = list(range(1000))
        assert is_monotonic_increasing(values)

    def test_non_monotonic_rejected(self):
        values = [10, 5, 8, 3, 7, 2, 9, 1, 6, 4] * 10
        assert not is_monotonic_increasing(values)

    def test_too_few_samples(self):
        assert not is_monotonic_increasing([1, 2, 3])

    def test_constant_values_rejected(self):
        values = [42] * 100
        assert not is_monotonic_increasing(values)


class TestPercentile:
    def test_median(self):
        assert percentile([1, 2, 3, 4, 5], 50) == 3.0

    def test_p0_and_p100(self):
        assert percentile([10, 20, 30], 0) == 10.0
        assert percentile([10, 20, 30], 100) == 30.0

    def test_empty_returns_zero(self):
        assert percentile([], 50) == 0.0

    def test_interpolation(self):
        result = percentile([0, 10], 50)
        assert result == pytest.approx(5.0)


class TestPctChange:
    def test_increase(self):
        assert pct_change(100, 150) == pytest.approx(50.0)

    def test_decrease(self):
        assert pct_change(200, 100) == pytest.approx(-50.0)

    def test_no_change(self):
        assert pct_change(100, 100) == pytest.approx(0.0)

    def test_zero_baseline_zero_current(self):
        assert pct_change(0, 0) == 0.0

    def test_zero_baseline_nonzero_current(self):
        assert pct_change(0, 100) == float("inf")

    def test_negative_baseline(self):
        assert pct_change(-100, -50) == pytest.approx(50.0)


class TestFormatNumber:
    def test_billions(self):
        assert format_number(1_500_000_000) == "1.50B"

    def test_millions(self):
        assert format_number(2_500_000) == "2.50M"

    def test_thousands(self):
        assert format_number(1_500) == "1.5K"

    def test_small_float(self):
        assert format_number(0.005) == "0.0050"

    def test_medium_float(self):
        assert format_number(0.5) == "0.500"

    def test_integer(self):
        assert format_number(42) == "42"

    def test_none(self):
        assert format_number(None) == "N/A"

    def test_nan(self):
        assert format_number(float("nan")) == "nan"

    def test_inf(self):
        assert format_number(float("inf")) == "inf"

    def test_regular_float(self):
        assert format_number(3.14) == "3.14"


class TestFormatDuration:
    def test_hours(self):
        assert format_duration(7200) == "2.0h"

    def test_minutes(self):
        assert format_duration(300) == "5.0m"

    def test_seconds(self):
        assert format_duration(45) == "45s"

    def test_none(self):
        assert format_duration(None) == "N/A"
