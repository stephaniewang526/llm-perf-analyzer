#!/usr/bin/env python3
"""
llm-perf-analyzer CLI: generate LLM-consumable performance reports.

Usage:
  # Summary from a JSON metrics file
  python3 analyze.py summary perf_results.json

  # Summary from Prometheus metrics
  python3 analyze.py summary --adapter prometheus /path/to/metrics.txt

  # Compare baseline vs current (JSON or Prometheus)
  python3 analyze.py compare baseline.json current.json

  # With custom polarity config
  python3 analyze.py summary --polarity-config configs/web_app.yaml data.json

  # Output to file
  python3 analyze.py summary -o report.md data.json
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _load_adapter(adapter_name: str):
    """Import and return the appropriate adapter module."""
    if adapter_name == "json":
        from adapters.json_adapter import read_json
        return read_json
    if adapter_name == "prometheus":
        from adapters.prometheus_adapter import read_prometheus
        return read_prometheus
    raise ValueError(f"Unknown adapter: {adapter_name}. Supported: json, prometheus")


def _load_polarity_config(path: str | None):
    """Load a PolarityConfig from YAML, or return None for default."""
    if path is None:
        return None
    from core.polarity import PolarityConfig
    return PolarityConfig.from_yaml(path)


def _check_file(path: str) -> None:
    if not Path(path).exists():
        print(f"Error: file not found: {path}", file=sys.stderr)
        sys.exit(1)


def cmd_summary(args: argparse.Namespace) -> None:
    _check_file(args.path)
    read_fn = _load_adapter(args.adapter)
    config = _load_polarity_config(args.polarity_config)

    from core.report import generate_summary_report

    data = read_fn(args.path)
    report = generate_summary_report(
        metrics=data["metrics"],
        config=config,
        metadata=data.get("metadata"),
        top_n=args.top,
        metric_types=data.get("metric_types"),
    )

    _output(report, args.output)


def cmd_compare(args: argparse.Namespace) -> None:
    _check_file(args.baseline)
    _check_file(args.current)
    read_fn = _load_adapter(args.adapter)
    config = _load_polarity_config(args.polarity_config)

    from core.report import generate_comparison_report

    baseline_data = read_fn(args.baseline)
    current_data = read_fn(args.current)

    combined_types = {
        **(baseline_data.get("metric_types") or {}),
        **(current_data.get("metric_types") or {}),
    }

    report = generate_comparison_report(
        baseline=baseline_data["metrics"],
        current=current_data["metrics"],
        config=config,
        threshold=args.threshold,
        baseline_metadata=baseline_data.get("metadata"),
        current_metadata=current_data.get("metadata"),
        top_n=args.top,
        metric_types=combined_types if combined_types else None,
    )

    _output(report, args.output)


def _output(report: str, output_path: str | None) -> None:
    if output_path:
        Path(output_path).write_text(report, encoding="utf-8")
        print(f"Report written to {output_path}", file=sys.stderr)
    else:
        print(report)


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    """Add shared options to a subcommand parser."""
    parser.add_argument(
        "--adapter",
        choices=["json", "prometheus"],
        default="json",
        help="Input data adapter (default: json)",
    )
    parser.add_argument(
        "--polarity-config",
        type=str,
        default=None,
        help="Path to YAML polarity config (default: all metrics neutral)",
    )
    parser.add_argument(
        "-o", "--output",
        type=str,
        default=None,
        help="Output file path (default: stdout)",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=50,
        help="Max metrics per section (default: 50)",
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate LLM-consumable performance analysis reports.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    sp = subparsers.add_parser("summary", help="Summarize a single dataset")
    sp.add_argument("path", help="Path to metrics file")
    _add_common_args(sp)

    cp = subparsers.add_parser("compare", help="Compare baseline vs current")
    cp.add_argument("baseline", help="Path to baseline metrics file")
    cp.add_argument("current", help="Path to current metrics file")
    cp.add_argument(
        "--threshold",
        type=float,
        default=5.0,
        help="Min %% change to flag as significant (default: 5.0)",
    )
    _add_common_args(cp)

    args = parser.parse_args()

    if args.command == "summary":
        cmd_summary(args)
    elif args.command == "compare":
        cmd_compare(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
