"""Tests for the Prometheus exposition format adapter."""

import io
import math
from pathlib import Path

import pytest

from adapters.prometheus_adapter import (
    _base_metric_name,
    _parse_data_line,
    read_prometheus,
)

FIXTURES = Path(__file__).parent / "fixtures"


class TestParseDataLine:
    def test_simple_metric(self):
        name, val, ts = _parse_data_line("cpu_usage 42.5 1700000000000")
        assert name == "cpu_usage"
        assert val == "42.5"
        assert ts == "1700000000000"

    def test_labeled_metric(self):
        name, val, ts = _parse_data_line(
            'http_requests_total{method="GET",code="200"} 100 1700000000000'
        )
        assert name == 'http_requests_total{method="GET",code="200"}'
        assert val == "100"
        assert ts == "1700000000000"

    def test_no_timestamp(self):
        name, val, ts = _parse_data_line("up 1")
        assert name == "up"
        assert val == "1"
        assert ts is None

    def test_empty_line(self):
        name, val, ts = _parse_data_line("")
        assert name is None

    def test_comment_like(self):
        name, val, ts = _parse_data_line("# some comment")
        assert name is None

    def test_inf_value(self):
        name, val, ts = _parse_data_line('bucket{le="+Inf"} 100 170000')
        assert name == 'bucket{le="+Inf"}'
        assert val == "100"


class TestBaseMetricName:
    def test_simple(self):
        assert _base_metric_name("cpu_usage") == "cpu_usage"

    def test_labeled(self):
        assert _base_metric_name('http_requests{method="GET"}') == "http_requests"

    def test_labeled_with_total_suffix(self):
        assert _base_metric_name('http_requests_total{method="GET"}') == "http_requests"

    def test_bucket_suffix(self):
        assert _base_metric_name("request_duration_bucket") == "request_duration"

    def test_count_suffix(self):
        assert _base_metric_name("request_duration_count") == "request_duration"

    def test_sum_suffix(self):
        assert _base_metric_name("request_duration_sum") == "request_duration"

    def test_total_suffix(self):
        assert _base_metric_name("http_requests_total") == "http_requests"


class TestReadPrometheus:
    def test_fixture_file(self):
        data = read_prometheus(FIXTURES / "sample_prometheus.txt")
        metrics = data["metrics"]
        types = data["metric_types"]
        meta = data["metadata"]

        assert meta["adapter"] == "prometheus"
        assert meta["sample_count"] == 5
        assert meta["metric_count"] > 0

    def test_counter_types_detected(self):
        data = read_prometheus(FIXTURES / "sample_prometheus.txt")
        types = data["metric_types"]

        assert types['http_requests_total{method="GET",code="200"}'] == "counter"
        assert types['http_requests_total{method="POST",code="200"}'] == "counter"
        assert types["simple_counter"] == "counter"

    def test_gauge_types_detected(self):
        data = read_prometheus(FIXTURES / "sample_prometheus.txt")
        types = data["metric_types"]

        assert types["cpu_usage_percent"] == "gauge"
        assert types["memory_bytes"] == "gauge"

    def test_histogram_sum_count_kept(self):
        data = read_prometheus(FIXTURES / "sample_prometheus.txt")
        metrics = data["metrics"]

        assert "request_duration_seconds_sum" in metrics
        assert "request_duration_seconds_count" in metrics

    def test_histogram_buckets_skipped_by_default(self):
        data = read_prometheus(FIXTURES / "sample_prometheus.txt")
        metrics = data["metrics"]

        bucket_keys = [k for k in metrics if "_bucket{" in k]
        assert len(bucket_keys) == 0

    def test_histogram_buckets_included_when_requested(self):
        data = read_prometheus(
            FIXTURES / "sample_prometheus.txt", skip_buckets=False
        )
        metrics = data["metrics"]
        bucket_keys = [k for k in metrics if "_bucket{" in k]
        assert len(bucket_keys) > 0

    def test_counter_values_monotonic(self):
        data = read_prometheus(FIXTURES / "sample_prometheus.txt")
        vals = data["metrics"]["simple_counter"]
        assert vals == [0, 10, 25, 45, 70]

    def test_gauge_values(self):
        data = read_prometheus(FIXTURES / "sample_prometheus.txt")
        vals = data["metrics"]["cpu_usage_percent"]
        assert len(vals) == 5
        assert vals[0] == pytest.approx(45.2)
        assert vals[2] == pytest.approx(52.1)

    def test_timestamps_converted_to_seconds(self):
        data = read_prometheus(FIXTURES / "sample_prometheus.txt")
        timestamps = data["timestamps"]
        assert timestamps is not None
        assert len(timestamps) == 5
        assert timestamps[0] == pytest.approx(1700000000.0)
        assert timestamps[-1] == pytest.approx(1700000004.0)

    def test_time_range_metadata(self):
        data = read_prometheus(FIXTURES / "sample_prometheus.txt")
        tr = data["metadata"]["time_range"]
        assert tr is not None
        assert tr["duration_seconds"] == pytest.approx(4.0)
        assert tr["samples"] == 5

    def test_metric_filter(self):
        data = read_prometheus(
            FIXTURES / "sample_prometheus.txt",
            metric_filter=["cpu_usage"],
        )
        metrics = data["metrics"]
        assert "cpu_usage_percent" in metrics
        assert "simple_counter" not in metrics
        assert 'http_requests_total{method="GET",code="200"}' not in metrics

    def test_string_io(self):
        text = (
            "# TYPE up gauge\n"
            "up 1 1700000000000\n"
            "up 1 1700000001000\n"
        )
        data = read_prometheus(io.StringIO(text))
        assert data["metrics"]["up"] == [1.0, 1.0]
        assert data["metric_types"]["up"] == "gauge"

    def test_empty_input(self):
        data = read_prometheus(io.StringIO(""))
        assert data["metrics"] == {}
        assert data["metric_types"] == {}

    def test_no_timestamps(self):
        text = "# TYPE up gauge\nup 1\nup 2\n"
        data = read_prometheus(io.StringIO(text))
        assert data["timestamps"] is None

    def test_untyped_metric(self):
        text = "mystery_metric 42 1700000000000\n"
        data = read_prometheus(io.StringIO(text))
        assert data["metric_types"]["mystery_metric"] == "untyped"

    def test_nan_and_inf_values(self):
        text = (
            "# TYPE m gauge\n"
            "m NaN 1700000000000\n"
            "m +Inf 1700000001000\n"
            "m 42 1700000002000\n"
        )
        data = read_prometheus(io.StringIO(text))
        vals = data["metrics"]["m"]
        assert math.isnan(vals[0])
        assert math.isinf(vals[1])
        assert vals[2] == 42.0
