# llm-perf-analyzer

Transform raw observability metrics into structured, LLM-consumable performance reports.

Most observability data -- Prometheus exports, JSON test results, diagnostic captures -- is designed for human eyes, not for LLMs to analyze. This tool bridges that gap by computing statistics, classifying metric polarity, detecting regressions, and producing structured markdown reports that dramatically improve AI-assisted performance analysis.

## Quick start

```bash
git clone <repository-url>
cd llm-perf-analyzer
pip install -r requirements.txt

# Summarize JSON (auto-detects nested perf-test vs time-series vs other shapes)
python3 analyze.py summary tests/fixtures/sample_perf_test_items.json

# Summarize Prometheus metrics
python3 analyze.py summary --adapter prometheus /path/to/metrics.txt

# Compare baseline vs current for regression detection
python3 analyze.py compare baseline.json current.json

# With a polarity config (teaches the tool which direction is "good")
python3 analyze.py compare --polarity-config configs/web_app.yaml \
  tests/fixtures/baseline.json tests/fixtures/current.json -o /tmp/compare.md
```

Inspect the generated markdown for the **schema** header, **Overall Verdict** (in compare mode), and **Regressions** tables. For agent-oriented usage, see `SKILL.md`.

## What it does

1. **Reads** metric data through **pluggable adapters** (JSON and Prometheus are built in; others can follow the same `dict[str, list[float]]` contract)
2. **Computes** statistics: mean, median, p95, p99, stddev, min, max
3. **Classifies** each metric's polarity: higher-is-better (throughput) vs lower-is-better (latency/cost)
4. **Detects** regressions and improvements by comparing baseline vs current
5. **Generates** a structured markdown report with schema version, tables, verdicts, sample counts, and coefficient of variation for confidence assessment

The output is designed for LLM consumption: predictable sections, consistent table formats, and explicit polarity annotations so the AI knows what "worse" means for each metric.

## Architecture

```
Input Adapters (pluggable)        Core Engine (generic)              Output
json_adapter.py            -->    metrics.py   (stats)          -->  Structured markdown
prometheus_adapter.py             polarity.py  (classification)
(future adapters)                 compare.py   (regression detection)
                                  report.py    (report generator)
```

All core engine code operates on a common format: `dict[str, list[float]]` mapping metric names to value arrays. Adapters convert source-specific formats into this common representation. New formats belong in `adapters/` plus a CLI hook in `analyze.py`; the core engine stays unchanged.

Adapters that natively know metric types (like Prometheus `# TYPE` annotations or JSON `improvement_direction` fields) pass that information through so the engine uses declared types instead of heuristic counter detection.

## Polarity configs

A polarity config tells the tool which direction is "good" for each metric. Without one, all metrics are treated as neutral (changes are reported but not classified as regressions or improvements).

```yaml
higher_is_better:
  - throughput.
  - ops_per_sec

lower_is_better:
  - latency.
  - error_rate
  - cpu.usage

priority_prefixes:
  - throughput.
  - latency.

counter_prefixes:
  - requests_total
```

Example config in this repository: `configs/web_app.yaml` -- typical HTTP / service metrics

Create your own by listing metric name prefixes under each category. First matching prefix wins.

## Input formats

### JSON (`--adapter json`, default)

Auto-detects the JSON structure and normalizes it:

**Nested perf-test format** (array of scenarios, each with `info.test_name` and a `metrics` array):

```json
[
  {
    "info": {"test_name": "api_read_load", "args": {"concurrency": 128}},
    "metrics": [
      {"name": "ops_per_sec", "value": 2912.88, "improvement_direction": "up"},
      {"name": "average_read_latency_us", "value": 43903.47, "improvement_direction": "down"}
    ]
  }
]
```

- Reads `improvement_direction` to classify throughput vs latency (no guessing)
- Includes test name and arguments in the metric key for disambiguation
- Supports both top-level arrays and `{"results": [...]}` wrappers, with optional top-level `id` metadata merged into the report metadata

**Time-series rows** (array of flat objects):

```json
[
  {"timestamp": 1700000000, "cpu": 45.2, "mem": 72.1},
  {"timestamp": 1700000060, "cpu": 47.8, "mem": 73.5}
]
```

**Metric-keyed arrays**:

```json
{"cpu": [45, 47, 52], "mem": [72, 73, 71]}
```

**Flat object** (single sample per metric):

```json
{"cpu": 45.2, "mem": 72.1}
```

### Prometheus (`--adapter prometheus`)

Parses the standard [Prometheus exposition format](https://prometheus.io/docs/instrumenting/exposition_formats/) directly. No conversion step needed.

- Reads `# TYPE` annotations to classify counters vs gauges (no heuristic guessing)
- Reads `# HELP` annotations into metadata
- Handles labeled metrics: `metric{label="value"} 42 1700000000000`
- Skips histogram `_bucket` lines by default (keeps `_sum` and `_count`)
- Timestamps in epoch milliseconds are auto-converted to seconds

## CLI reference

```bash
# Summary mode
python3 analyze.py summary <file> [--adapter json|prometheus] [--polarity-config <yaml>] [--top N] [-o output.md]

# Comparison mode
python3 analyze.py compare <baseline> <current> [--adapter json|prometheus] [--polarity-config <yaml>] [--threshold 5.0] [--top N] [-o output.md]
```

| Flag | Default | Description |
|---|---|---|
| `--adapter` | json | Input format: `json` or `prometheus` |
| `--polarity-config` | none | YAML file defining metric directions |
| `--threshold` | 5.0 | Minimum % change to flag as significant (embedded in report schema) |
| `--top` | 50 | Max metrics per report section |
| `-o` | stdout | Output file path |

## Agent skill

The repo includes a `SKILL.md` that teaches AI coding agents (Cursor, Claude Code, etc.) how to use the tool and interpret its output. Install it as a skill in your AI tool to get guided performance analysis.

## Running tests

```bash
pip install -r requirements.txt pytest pyyaml
python3 -m pytest tests/ -v
```

## Requirements

- Python 3.10+
- numpy (statistics computation)
- pyyaml (polarity config loading, optional if using `PolarityConfig.from_dict()`)

## License

Apache-2.0. See [LICENSE](LICENSE).
