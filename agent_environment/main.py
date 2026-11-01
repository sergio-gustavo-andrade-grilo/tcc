import argparse

from agent_environment.collectors.prometheus_client import PrometheusClient
from agent_environment.core.analyzer import analyze
from agent_environment.core.models import Classification, Finding
from agent_environment.core.openrouter_client import OpenRouterClient
from agent_environment.core.reporter import generate_report


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


def main() -> None:
    parser = argparse.ArgumentParser(description="Cluster resource usage report")
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="print only the findings table, without calling the LLM",
    )
    args = parser.parse_args()

    findings = analyze(PrometheusClient().collect())
    print(format_findings(findings))

    if args.no_llm:
        return

    client = OpenRouterClient()
    
    print("\n" + "=" * 60 + "\n")
    print(generate_report(findings, client))
    stats = client.last_stats
    if stats:
        print(
            f"\n(model={stats.model} latency={stats.latency_seconds:.1f}s "
            f"tokens in/out={stats.prompt_tokens}/{stats.completion_tokens})"
        )


if __name__ == "__main__":
    main()