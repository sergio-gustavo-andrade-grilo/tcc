from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from agent_environment.core.models import ClusterSummary, Finding, Resource

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "report.txt"

NO_DATA_REPORT = "No report: Prometheus returned no usable data yet."

GIB = 1024**3


class LLMClient(Protocol):
    def complete(self, prompt: str) -> str: ...


def _pct(value: float | None) -> str:
    return "unavailable" if value is None else f"{value * 100:.1f}%"


def _num(value: float | None, unit: str, scale: float = 1.0) -> str:
    return "unavailable" if value is None else f"{value / scale:.2f} {unit}"


def summary_to_text(summary: ClusterSummary) -> str:
    cpu, mem = Resource.CPU, Resource.MEMORY
    pending = (
        "unavailable" if summary.pending_pods is None else str(summary.pending_pods)
    )
    if summary.pending_pod_names:
        pending += f" ({', '.join(summary.pending_pod_names)})"
    nodes = "unavailable" if summary.node_count is None else str(summary.node_count)
    return "\n".join(
        [
            f"- nodes: {nodes}",
            (f"- cpu: capacity {_num(summary.cpu_capacity_cores, 'cores')}, "
            f"requested {_num(summary.cpu_requested_cores, 'cores')} "
            f"({_pct(summary.requested_fraction(cpu))} of capacity), "
            f"used {_num(summary.cpu_usage_cores, 'cores')} "
            f"({_pct(summary.usage_fraction(cpu))} of capacity)"),
            (f"- memory: capacity {_num(summary.memory_capacity_bytes, 'GiB', GIB)}, "
            f"requested {_num(summary.memory_requested_bytes, 'GiB', GIB)} "
            f"({_pct(summary.requested_fraction(mem))} of capacity), "
            f"used {_num(summary.memory_usage_bytes, 'GiB', GIB)} "
            f"({_pct(summary.usage_fraction(mem))} of capacity)"),
            f"- pending pods: {pending}",
        ]
    )


def findings_to_text(findings: list[Finding]) -> str:
    if not findings:
        return "(no per-container findings)"
    return "\n".join(
        f"- {f.key} | {f.resource.value} | ratio={f.ratio:.2f} | {f.classification.value}"
        for f in sorted(findings, key=lambda f: (str(f.key), f.resource.value))
    )


def skipped_to_text(skipped: Sequence[str]) -> str:
    return ", ".join(skipped) if skipped else "none"


def build_prompt(cluster, findings, summary, template=None, skipped: Sequence[str] = ()) -> str:
    if template is None:
        template = PROMPT_PATH.read_text(encoding="utf-8")
    return (
        template.replace("{cluster}", cluster)
        .replace("{summary}", summary_to_text(summary))
        .replace("{findings}", findings_to_text(findings))
        .replace("{skipped}", skipped_to_text(skipped))
    )


def generate_report(cluster, findings, summary, client, skipped: Sequence[str] = ()) -> str:
    if not findings and not summary.has_data():
        return NO_DATA_REPORT
    return client.complete(build_prompt(cluster, findings, summary, skipped=skipped))