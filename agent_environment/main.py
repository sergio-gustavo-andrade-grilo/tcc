import argparse
import time
from datetime import datetime, timezone
from functools import cache

import httpx

from agent_environment.collectors.prometheus_client import PrometheusClient
from agent_environment.config import MIN_POD_AGE_SECONDS
from agent_environment.core.analyzer import Thresholds, analyze, is_mature
from agent_environment.core.models import Classification, Finding
from agent_environment.core.openrouter_client import OpenRouterClient
from agent_environment.core.reporter import generate_report, summary_to_text


@cache
def get_client() -> OpenRouterClient:
    """Created on first use, so the tables work even without an API key."""
    return OpenRouterClient()


def format_findings(findings: list[Finding]) -> str:
    if not findings:
        return "No findings: Prometheus returned no usable data yet."
    lines = [f"{'container':<45}{'resource':<9}{'ratio':>7}  classification"]
    for f in sorted(findings, key=lambda f: (str(f.key), f.resource.value)):
        lines.append(
            f"{f.key!s:<45}{f.resource.value:<9}{f.ratio:>7.2f}  {f.classification.value}"
        )
    over = sum(f.classification is Classification.OVER_PROVISIONED for f in findings)
    under = sum(f.classification is Classification.UNDER_PROVISIONED for f in findings)
    lines.append(f"\n{len(findings)} findings: {over} over-provisioned, {under} under-provisioned")
    return "\n".join(lines)


def run_once(
    prometheus: PrometheusClient,
    requested_clusters: list[str] | None,
    thresholds: Thresholds,
    use_llm: bool,
    keep_going: bool,
) -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    clusters = requested_clusters or prometheus.list_clusters()
    if not clusters:
        print(f"[{stamp}] No clusters found in Prometheus. Is the infra up?\n")
        return

    for name in clusters:
        try:
            snapshot = prometheus.snapshot(name)
            findings = analyze(snapshot.containers, thresholds)
            young = [m for m in snapshot.containers if not is_mature(m, thresholds)]

            print("=" * 60)
            print(f"Cluster: {name}   [{stamp}]")
            print("=" * 60)
            print(summary_to_text(snapshot.summary))
            print()
            print(format_findings(findings))
            if young:
                pods = ", ".join(sorted({f"{m.key.namespace}/{m.key.pod}" for m in young}))
                print(f"\nSkipped (younger than {thresholds.min_age_seconds:.0f}s): {pods}")

            if use_llm:
                client = get_client()
                print("\n--- report ---\n")
                print(generate_report(name, findings, snapshot.summary, client))
                stats = client.last_stats
                if stats:
                    print(
                        f"\n(model={stats.model} latency={stats.latency_seconds:.1f}s "
                        f"tokens in/out={stats.prompt_tokens}/{stats.completion_tokens})"
                    )
            print()
        except httpx.HTTPError as error:
            if not keep_going:
                raise
            print(f"[{stamp}] {name}: request failed: {error}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Cluster resource usage report")
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="print only the findings tables, without calling the LLM",
    )
    parser.add_argument(
        "--cluster",
        action="append",
        help="cluster to report on (repeatable); default: all clusters in Prometheus",
    )
    parser.add_argument(
        "--interval",
        type=float,
        help="generate reports every N seconds until interrupted; default: run once",
    )
    args = parser.parse_args()

    if args.interval is not None and args.interval <= 0:
        parser.error("--interval must be positive")

    prometheus = PrometheusClient()
    thresholds = Thresholds(min_age_seconds=MIN_POD_AGE_SECONDS)
    use_llm = not args.no_llm

    if args.interval is None:
        run_once(prometheus, args.cluster, thresholds, use_llm, keep_going=False)
        return

    print(f"Reporting every {args.interval:g}s. Ctrl+C to stop.\n")
    next_run = time.monotonic()
    try:
        while True:
            try:
                run_once(prometheus, args.cluster, thresholds, use_llm, keep_going=True)
            except httpx.HTTPError as error:
                print(f"[error] {error}\n")
            next_run += args.interval
            time.sleep(max(0.0, next_run - time.monotonic()))
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()