---
name: perf-analysis
description: >-
  Analyze performance metrics, detect regressions, and generate structured
  reports from JSON or Prometheus data. Use when the user provides metric files,
  asks about performance regressions, wants to compare baseline vs candidate
  runs, or needs help interpreting observability data.
when_to_use: performance analysis, regression detection, metric comparison, observability data interpretation
license: Apache-2.0
---

# Performance Analysis Skill

Analyze observability metrics and detect performance regressions using
`llm-perf-analyzer`. This skill transforms raw metrics into structured
reports and guides you through interpreting the results.

## Prerequisites

- Python 3.10+
- `pip install numpy pyyaml` (or `pip install -r requirements.txt`)
- The `llm-perf-analyzer` repo cloned locally

## Workflow

### Step 1 -- Identify the data

Determine what the user has:

| User has | Action |
|---|---|
| Nested perf-test JSON (array of `info` + `metrics` items) | Use JSON adapter directly (default) |
| Generic JSON metrics | Use JSON adapter directly (auto-detects format) |
| Prometheus metrics.txt | Use `--adapter prometheus` |
| Two metric files (baseline + candidate) | Run comparison mode |
| A directory of metric files | Ask which files to analyze |
| No data yet, just questions | Help them export metrics (see Appendix) |

### Step 2 -- Generate the report

**Summary (single dataset):**

```bash
python3 analyze.py summary perf_results.json
python3 analyze.py summary --adapter prometheus /path/to/metrics.txt
```

**Comparison (regression detection):**

```bash
python3 analyze.py compare baseline.json candidate.json --threshold 5.0
```

**With polarity config (teaches the tool which direction is "good"):**

```bash
python3 analyze.py summary data.json --polarity-config configs/my_app.yaml
python3 analyze.py compare baseline.json candidate.json --polarity-config configs/my_app.yaml
```

If no polarity config is provided, all metrics are treated as neutral
(changes are reported but not classified as regressions or improvements).

### Step 3 -- Interpret the report

The generated report has predictable sections. Here is how to reason
about each one:

#### Schema (always present)

Confirms the report format and version. Use `schema_version` to know
which fields to expect.

#### Overall Verdict (comparison only)

Start here. It tells you:
- How many metrics regressed vs improved
- Whether action is needed

If `regressions > 0`, dig into the Regressions table.
If `No significant change`, the candidate is safe.

#### Regressions table

Each row shows a metric that moved in the **wrong** direction:
- THROUGHPUT metrics that **decreased** (less work done)
- COST metrics that **increased** (more latency, memory, CPU)

Focus on:
1. **Change %** -- how big is the regression?
2. **P95 Change** -- is the tail latency affected?
3. **Category** -- throughput regressions are usually more urgent than cost increases
4. **Priority flag** -- priority metrics are the most important to the workload
5. **Metric type** -- nested perf-test JSON may include declared types (throughput/latency)

#### Improvements table

Metrics that moved in the **right** direction. Useful for confirming
that an optimization worked, but don't let improvements mask regressions
in other areas.

#### Stable Priority Metrics

Key metrics that did NOT change. This is important context -- it tells
you what the candidate did NOT break.

### Step 4 -- Create a polarity config (if needed)

If the user's metrics don't have a polarity config yet, help them
create one. The format is YAML:

```yaml
higher_is_better:
  - requests_per_second
  - throughput.
  - ops_per_sec

lower_is_better:
  - latency.
  - error_rate
  - p99_ms
  - cpu.usage

neutral:
  - connections.current
  - version

priority_prefixes:
  - requests_per_second
  - latency.
  - error_rate

counter_prefixes:
  - requests_total
  - bytes_sent_total
```

Rules:
- Prefixes are matched left-to-right; first match wins
- Use trailing dots for prefix matching (e.g., `latency.` matches `latency.p99`, `latency.mean`)
- `counter_prefixes` identify cumulative counters that need rate conversion (per-sample deltas)
- `priority_prefixes` boost severity ranking in comparison reports

Save as `configs/<your_app>.yaml` and pass via `--polarity-config`.

### Step 5 -- Provide actionable analysis

After generating the report, **proactively** surface problems. Do not
wait for the user to ask -- scan the metrics and flag anything alarming.

#### Proactive red flags (always check these)

Scan all metrics for these patterns and call them out immediately:

| Pattern | What it means |
|---|---|
| CPU > 80% sustained | CPU saturation -- throughput is likely capped |
| CPU > 95% any sample | Hard ceiling hit, likely causing latency spikes |
| Memory monotonically increasing | Possible memory leak |
| Latency p99 >> p50 (10x+) | Severe tail latency -- a few requests are very slow |
| Latency p99 > SLA threshold | SLA risk even if mean looks fine |
| Throughput coefficient of variation > 20% | Unstable performance, investigate periodic drops |
| Disk I/O wait > 10% of wall time | Storage bottleneck |
| Error rate > 0 | Any errors during a perf test are abnormal |
| Cache hit ratio dropping | Working set exceeding cache, expect latency cliff |
| Connection count near limit | Connection pool exhaustion risk |
| Any metric at exactly 0 for full run | Possible instrumentation failure |
| Throughput drops mid-run then recovers | GC pauses, compaction storms, or resource contention |

Present these at the top of your analysis, before the regression
summary, using a "Red Flags" or "Warnings" heading.

#### Regression analysis

1. **Is there a regression?** Yes/no, with specific metrics
2. **How severe?** Minor (<10%), moderate (10-30%), severe (>30%)
3. **What's the likely cause?** Correlate metrics:
   - Throughput down + latency up = likely contention or resource exhaustion
   - CPU up + throughput flat = efficiency regression
   - Memory up + everything else flat = possible leak
   - Latency spikes + disk I/O up = storage-bound
   - All latencies up proportionally = upstream dependency or network issue
4. **What should they investigate?** Specific areas to look at
5. **Is the candidate safe to ship?** Clear recommendation

## Input Format Reference

### JSON (default adapter)

Auto-detects the JSON structure:

**Nested perf-test format** (CI or benchmark harness exports):
- Array of test items with `info.test_name` and `metrics[{name, value}]`
- `improvement_direction` ("up"/"down") maps to throughput/latency types
- Test name + arguments are included in metric keys for disambiguation

**Time-series rows** (array of flat objects):
- Each object is one timestamped sample
- Timestamp key auto-detected (`timestamp`, `ts`, `time`, `epoch`, etc.)

**Metric-keyed arrays**: `{"metric_name": [val1, val2, ...]}`

**Flat object**: `{"metric_name": single_value}`

### Prometheus (`--adapter prometheus`)

Parses standard Prometheus exposition format directly:
- Uses `# TYPE` annotations to classify counters vs gauges
- Handles labeled metrics and histogram families
- Skips `_bucket` lines by default

## Appendix: Exporting Metrics

### From Prometheus

```bash
# Export raw metrics endpoint directly
curl -s http://localhost:9090/metrics > metrics.txt
python3 analyze.py summary --adapter prometheus metrics.txt
```

### From CI or load-test harnesses

Export JSON in the nested perf-test shape (array of objects with `info` and
`metrics`, or a top-level `{"results": [...]}` wrapper), then run:

```bash
python3 analyze.py summary perf_results.json
python3 analyze.py compare baseline.json candidate.json
```

### From Splunk / Datadog / Grafana

Most tools support JSON export from their API. Export the query result
as JSON, then feed it to `analyze.py`. The adapter handles arrays of
timestamped objects and flat metric dictionaries.
