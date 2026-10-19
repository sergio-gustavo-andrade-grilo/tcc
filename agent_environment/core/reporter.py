from pathlib import Path
from typing import Protocol

from agent_environment.core.models import Finding

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "report.txt"

NO_DATA_REPORT = "No report: there are no findings yet (Prometheus returned no usable data)."


class LLMClient(Protocol):
    def complete(self, prompt: str) -> str: ...


def findings_to_text(findings: list[Finding]) -> str:
    return "\n".join(
        f"- {f.key} | {f.resource.value} | ratio={f.ratio:.2f} | {f.classification.value}"
        for f in sorted(findings, key=lambda f: (str(f.key), f.resource.value))
    )


def build_prompt(findings: list[Finding], template: str | None = None) -> str:
    if template is None:
        template = PROMPT_PATH.read_text(encoding="utf-8")
    return template.replace("{findings}", findings_to_text(findings))


def generate_report(findings: list[Finding], client: LLMClient) -> str:
    if not findings:
        return NO_DATA_REPORT  # nothing to describe, so don't call the model
    return client.complete(build_prompt(findings))