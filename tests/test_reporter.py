from agent_environment.core.models import (
    Classification,
    ContainerKey,
    Finding,
    Resource,
)
from agent_environment.core.reporter import NO_DATA_REPORT, build_prompt, generate_report

FINDING = Finding(
    ContainerKey("default", "over-provisioned", "app"),
    Resource.CPU,
    0.05,
    Classification.OVER_PROVISIONED,
)


class FakeClient:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return "fake report"


def test_prompt_contains_finding():
    prompt = build_prompt([FINDING], template="Findings:\n{findings}")
    assert "default/over-provisioned/app | cpu | ratio=0.05 | over_provisioned" in prompt


def test_report_comes_from_client():
    client = FakeClient()
    assert generate_report([FINDING], client) == "fake report"
    assert len(client.prompts) == 1


def test_no_findings_skips_the_model():
    client = FakeClient()
    assert generate_report([], client) == NO_DATA_REPORT
    assert client.prompts == []