from agent_environment.core.models import (
    Classification,
    ClusterSummary,
    ContainerKey,
    Finding,
    Resource,
)
from agent_environment.core.reporter import (
    NO_DATA_REPORT,
    build_prompt,
    generate_report,
    summary_to_text,
)

FINDING = Finding(
    ContainerKey("default", "over-provisioned", "app"),
    Resource.CPU,
    0.05,
    Classification.OVER_PROVISIONED,
)

GIB = 1024**3

SUMMARY = ClusterSummary(
    node_count=1,
    cpu_capacity_cores=32.0,
    memory_capacity_bytes=256 * GIB,
    cpu_requested_cores=8.0,
    memory_requested_bytes=64 * GIB,
    cpu_usage_cores=3.2,
    memory_usage_bytes=32 * GIB,
    pending_pods=2,
)


class FakeClient:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return "fake report"


def test_summary_fractions():
    assert SUMMARY.requested_fraction(Resource.CPU) == 0.25
    assert SUMMARY.usage_fraction(Resource.CPU) == 0.1
    assert SUMMARY.usage_fraction(Resource.MEMORY) == 0.125


def test_summary_text_has_numbers_and_pending():
    text = summary_to_text(SUMMARY)
    assert "capacity 32.00 cores" in text
    assert "(25.0% of capacity)" in text
    assert "pending pods: 2" in text


def test_missing_values_are_marked_unavailable():
    assert "unavailable" in summary_to_text(ClusterSummary(node_count=1))


def test_prompt_contains_summary_and_finding():
    prompt = build_prompt(
        "tcc-a", [FINDING], SUMMARY, template="{cluster}\n{summary}\n---\n{findings}"
    )
    assert "tcc-a" in prompt
    assert "pending pods: 2" in prompt
    assert "default/over-provisioned/app | cpu | ratio=0.05 | over_provisioned" in prompt


def test_report_comes_from_client():
    client = FakeClient()
    assert generate_report("tcc-a", [FINDING], SUMMARY, client) == "fake report"
    assert len(client.prompts) == 1


def test_no_data_skips_the_model():
    client = FakeClient()
    assert generate_report("tcc-a", [], ClusterSummary(), client) == NO_DATA_REPORT
    assert client.prompts == []


def test_summary_without_findings_still_reports():
    client = FakeClient()
    assert generate_report("tcc-a", [], SUMMARY, client) == "fake report"