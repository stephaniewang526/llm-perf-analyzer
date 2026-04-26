"""Test loading the bundled example YAML polarity config."""

from pathlib import Path

from core.polarity import PolarityConfig, get_polarity, is_priority

CONFIGS_DIR = Path(__file__).parent.parent / "configs"


class TestWebAppConfig:
    def setup_method(self):
        self.config = PolarityConfig.from_yaml(CONFIGS_DIR / "web_app.yaml")

    def test_loads_all_sections(self):
        assert len(self.config.higher_is_better) > 0
        assert len(self.config.lower_is_better) > 0
        assert len(self.config.neutral) > 0
        assert len(self.config.priority_prefixes) > 0
        assert len(self.config.counter_prefixes) > 0

    def test_throughput_higher_is_better(self):
        assert get_polarity("throughput.global_rps", self.config) == "higher_is_better"
        assert get_polarity("ops_per_sec", self.config) == "higher_is_better"

    def test_latency_lower_is_better(self):
        assert get_polarity("latency.p99_ms", self.config) == "lower_is_better"

    def test_memory_lower_is_better(self):
        assert get_polarity("memory_bytes.heap", self.config) == "lower_is_better"

    def test_connections_neutral(self):
        assert get_polarity("connections.current", self.config) == "neutral"

    def test_priority_metrics(self):
        assert is_priority("throughput.requests", self.config)
        assert is_priority("http_requests_total", self.config)
        assert not is_priority("some.unknown.metric", self.config)
