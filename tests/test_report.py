"""Tests for core.report -- structured markdown report generator."""

from pathlib import Path

import pytest

from adapters.json_adapter import read_json
from core.polarity import PolarityConfig
from core.report import generate_comparison_report, generate_summary_report

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def demo_config():
    return PolarityConfig(
        higher_is_better=["throughput."],
        lower_is_better=["latency.", "cpu."],
        neutral=[],
        priority_prefixes=["throughput.", "latency."],
        counter_prefixes=[],
    )


class TestSummaryReport:
    def test_generates_markdown(self):
        data = read_json(FIXTURES / "sample_perf_test_items.json")
        report = generate_summary_report(data["metrics"], metadata=data["metadata"])
        assert "# Performance Analysis Report" in report
        assert "schema_version" in report
        assert "llm-perf-result" in report

    def test_includes_metrics_table(self):
        data = read_json(FIXTURES / "sample_perf_test_items.json")
        report = generate_summary_report(data["metrics"], metadata=data["metadata"])
        assert "ops_per_sec" in report
        assert "| Metric | Type |" in report

    def test_includes_metadata(self):
        data = read_json(FIXTURES / "sample_perf_test_items.json")
        report = generate_summary_report(data["metrics"], metadata=data["metadata"])
        assert "## Metadata" in report
        assert "json" in report

    def test_no_config_all_neutral(self):
        data = read_json(FIXTURES / "sample_perf_test_items.json")
        report = generate_summary_report(data["metrics"])
        assert "# Performance Analysis Report" in report

    def test_with_polarity_config_shows_priority(self, demo_config):
        data = read_json(FIXTURES / "baseline.json")
        report = generate_summary_report(
            data["metrics"], config=demo_config, metadata=data["metadata"]
        )
        assert "Priority Metrics" in report

    def test_empty_metrics(self):
        report = generate_summary_report({})
        assert "Total metrics" in report
        assert "0" in report


class TestComparisonReport:
    def test_detects_regressions(self, demo_config):
        baseline = read_json(FIXTURES / "baseline.json")
        current = read_json(FIXTURES / "current.json")
        report = generate_comparison_report(
            baseline["metrics"],
            current["metrics"],
            config=demo_config,
            baseline_metadata=baseline["metadata"],
            current_metadata=current["metadata"],
        )
        assert "Regressions" in report
        assert "throughput.ops_per_sec" in report

    def test_detects_improvements(self, demo_config):
        baseline = read_json(FIXTURES / "baseline.json")
        current = read_json(FIXTURES / "current.json")
        report = generate_comparison_report(
            baseline["metrics"],
            current["metrics"],
            config=demo_config,
            baseline_metadata=baseline["metadata"],
            current_metadata=current["metadata"],
        )
        assert "REGRESSION" in report or "Regressions" in report

    def test_includes_verdict(self, demo_config):
        baseline = read_json(FIXTURES / "baseline.json")
        current = read_json(FIXTURES / "current.json")
        report = generate_comparison_report(
            baseline["metrics"],
            current["metrics"],
            config=demo_config,
        )
        assert "## Overall Verdict" in report

    def test_includes_schema_header(self, demo_config):
        baseline = read_json(FIXTURES / "baseline.json")
        current = read_json(FIXTURES / "current.json")
        report = generate_comparison_report(
            baseline["metrics"],
            current["metrics"],
            config=demo_config,
        )
        assert "schema_version" in report
        assert "comparison" in report

    def test_no_config_still_works(self):
        baseline = read_json(FIXTURES / "baseline.json")
        current = read_json(FIXTURES / "current.json")
        report = generate_comparison_report(
            baseline["metrics"],
            current["metrics"],
        )
        assert "# Performance Analysis Report" in report
        assert "Overall Verdict" in report

    def test_identical_data_no_regressions(self, demo_config):
        data = read_json(FIXTURES / "baseline.json")
        report = generate_comparison_report(
            data["metrics"],
            data["metrics"],
            config=demo_config,
        )
        assert "No significant change" in report

    def test_full_comparison_details_section(self, demo_config):
        baseline = read_json(FIXTURES / "baseline.json")
        current = read_json(FIXTURES / "current.json")
        report = generate_comparison_report(
            baseline["metrics"],
            current["metrics"],
            config=demo_config,
        )
        assert "Full comparison of all significant metrics" in report


class TestEndToEnd:
    """Test the full pipeline: JSON -> adapter -> report."""

    def test_summary_from_perf_test_items(self):
        data = read_json(FIXTURES / "sample_perf_test_items.json")
        report = generate_summary_report(
            data["metrics"], metadata=data["metadata"],
            metric_types=data.get("metric_types"),
        )
        lines = report.split("\n")
        assert any("Performance Analysis Report" in l for l in lines)
        assert any("ops_per_sec" in l for l in lines)

    def test_comparison_from_json_files(self):
        baseline = read_json(FIXTURES / "baseline.json")
        current = read_json(FIXTURES / "current.json")
        config = PolarityConfig(
            higher_is_better=["throughput."],
            lower_is_better=["latency.", "cpu."],
        )
        report = generate_comparison_report(
            baseline["metrics"],
            current["metrics"],
            config=config,
            baseline_metadata=baseline["metadata"],
            current_metadata=current["metadata"],
        )
        assert "throughput.ops_per_sec" in report
        assert "latency.p99_ms" in report
