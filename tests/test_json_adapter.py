"""Tests for the JSON adapter."""

import io
import json
from pathlib import Path

import pytest

from adapters.json_adapter import read_json

FIXTURES = Path(__file__).parent / "fixtures"


class TestPerfTestItemsFormat:
    def test_reads_perf_test_fixture(self):
        data = read_json(FIXTURES / "sample_perf_test_items.json")
        metrics = data["metrics"]
        meta = data["metadata"]

        assert meta["adapter"] == "json"
        assert meta["format"] == "perf_test_items"
        assert meta["sample_count"] == 2
        assert meta["metric_count"] > 0

    def test_metric_names_include_test_and_args(self):
        data = read_json(FIXTURES / "sample_perf_test_items.json")
        metrics = data["metrics"]

        assert "api_read_load.concurrency=128.ops_per_sec" in metrics
        assert "bulk_write_load.concurrency=256.ops_per_sec" in metrics
        assert "api_read_load.concurrency=128.average_read_latency_us" in metrics

    def test_metric_values(self):
        data = read_json(FIXTURES / "sample_perf_test_items.json")
        metrics = data["metrics"]

        assert metrics["api_read_load.concurrency=128.ops_per_sec"] == [pytest.approx(2912.88)]
        assert metrics["bulk_write_load.concurrency=256.ops_per_sec"] == [
            pytest.approx(215847.89)
        ]

    def test_improvement_direction_mapped_to_types(self):
        data = read_json(FIXTURES / "sample_perf_test_items.json")
        types = data["metric_types"]

        assert types["api_read_load.concurrency=128.ops_per_sec"] == "throughput"
        assert types["api_read_load.concurrency=128.average_read_latency_us"] == "latency"

    def test_test_filter(self):
        data = read_json(FIXTURES / "sample_perf_test_items.json", test_filter=["api_read_load"])
        metrics = data["metrics"]

        assert "api_read_load.concurrency=128.ops_per_sec" in metrics
        assert "bulk_write_load.concurrency=256.ops_per_sec" not in metrics

    def test_no_timestamps(self):
        data = read_json(FIXTURES / "sample_perf_test_items.json")
        assert data["timestamps"] is None


class TestWrappedResultsFormat:
    def test_reads_wrapped_fixture(self):
        data = read_json(FIXTURES / "sample_wrapped_perf_results.json")
        metrics = data["metrics"]
        meta = data["metadata"]

        assert meta["format"] == "perf_test_items"
        assert meta["sample_count"] == 1
        assert "api_read_load.concurrency=128.ops_per_sec" in metrics

    def test_top_level_metadata_extracted(self):
        data = read_json(FIXTURES / "sample_wrapped_perf_results.json")
        meta = data["metadata"]

        assert meta.get("project") == "nightly-perf"
        assert meta.get("variant") == "linux-amd64"
        assert meta.get("task_name") == "benchmark.load_read_scan"

    def test_wrapped_improvement_direction(self):
        data = read_json(FIXTURES / "sample_wrapped_perf_results.json")
        types = data["metric_types"]

        assert types["api_read_load.concurrency=128.ops_per_sec"] == "throughput"
        assert types["api_read_load.concurrency=128.average_read_latency_us"] == "latency"


class TestTimeSeriesRows:
    def test_array_of_objects(self):
        rows = [
            {"timestamp": 1700000000, "cpu": 45.2, "mem": 72.1},
            {"timestamp": 1700000001, "cpu": 47.8, "mem": 73.5},
            {"timestamp": 1700000002, "cpu": 52.1, "mem": 71.0},
        ]
        data = read_json(io.StringIO(json.dumps(rows)))
        metrics = data["metrics"]

        assert metrics["cpu"] == [45.2, 47.8, 52.1]
        assert metrics["mem"] == [72.1, 73.5, 71.0]
        assert len(data["timestamps"]) == 3

    def test_auto_detects_timestamp_key(self):
        rows = [{"ts": 1700000000, "val": 1.0}, {"ts": 1700000001, "val": 2.0}]
        data = read_json(io.StringIO(json.dumps(rows)))

        assert "val" in data["metrics"]
        assert "ts" not in data["metrics"]

    def test_explicit_timestamp_key(self):
        rows = [
            {"my_time": 1700000000, "val": 1.0},
            {"my_time": 1700000001, "val": 2.0},
        ]
        data = read_json(io.StringIO(json.dumps(rows)), timestamp_key="my_time")

        assert "val" in data["metrics"]
        assert "my_time" not in data["metrics"]
        assert len(data["timestamps"]) == 2

    def test_time_range_computed(self):
        rows = [
            {"timestamp": 1700000000, "val": 1.0},
            {"timestamp": 1700000060, "val": 2.0},
        ]
        data = read_json(io.StringIO(json.dumps(rows)))
        tr = data["metadata"]["time_range"]

        assert tr is not None
        assert tr["duration_seconds"] == pytest.approx(60.0)
        assert tr["samples"] == 2

    def test_skips_non_numeric_values(self):
        rows = [
            {"timestamp": 1700000000, "val": 1.0, "label": "foo"},
            {"timestamp": 1700000001, "val": 2.0, "label": "bar"},
        ]
        data = read_json(io.StringIO(json.dumps(rows)))

        assert "val" in data["metrics"]
        assert "label" not in data["metrics"]


class TestMetricArrays:
    def test_dict_of_arrays(self):
        obj = {"cpu": [45, 47, 52], "mem": [72, 73, 71]}
        data = read_json(io.StringIO(json.dumps(obj)))
        metrics = data["metrics"]
        meta = data["metadata"]

        assert metrics["cpu"] == [45.0, 47.0, 52.0]
        assert metrics["mem"] == [72.0, 73.0, 71.0]
        assert meta["format"] == "metric_arrays"
        assert meta["sample_count"] == 3


class TestFlatObject:
    def test_single_values(self):
        obj = {"cpu": 45.2, "mem": 72.1, "disk_iops": 3000}
        data = read_json(io.StringIO(json.dumps(obj)))
        metrics = data["metrics"]
        meta = data["metadata"]

        assert metrics["cpu"] == [45.2]
        assert metrics["mem"] == [72.1]
        assert metrics["disk_iops"] == [3000.0]
        assert meta["format"] == "flat_object"
        assert meta["sample_count"] == 1

    def test_skips_non_numeric(self):
        obj = {"cpu": 45.2, "name": "my_host"}
        data = read_json(io.StringIO(json.dumps(obj)))

        assert "cpu" in data["metrics"]
        assert "name" not in data["metrics"]


class TestEdgeCases:
    def test_empty_json_object(self):
        data = read_json(io.StringIO("{}"))
        assert data["metrics"] == {}

    def test_empty_json_array(self):
        data = read_json(io.StringIO("[]"))
        assert data["metrics"] == {}

    def test_invalid_json(self):
        data = read_json(io.StringIO("not json at all"))
        assert data["metrics"] == {}
        assert "error" in data["metadata"]

    def test_file_path(self):
        data = read_json(FIXTURES / "sample_perf_test_items.json")
        assert "sample_perf_test_items.json" in data["metadata"]["source"]


class TestEndToEnd:
    def test_summary_from_perf_test_items(self):
        from core.report import generate_summary_report

        data = read_json(FIXTURES / "sample_perf_test_items.json")
        report = generate_summary_report(
            metrics=data["metrics"],
            metadata=data.get("metadata"),
            metric_types=data.get("metric_types"),
        )
        assert "# Performance Analysis Report" in report
        assert "ops_per_sec" in report
        assert "api_read_load" in report
