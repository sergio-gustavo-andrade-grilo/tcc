from dataclasses import dataclass

from agent_environment.core.models import (
    Classification,
    ContainerMetrics,
    Finding,
    Resource,
)


@dataclass(frozen=True)
class Thresholds:
    over_provisioned_below: float = 0.3
    under_provisioned_above: float = 1.0
    min_age_seconds: float = 300.0


def classify(ratio: float, thresholds: Thresholds) -> Classification:
    if ratio < thresholds.over_provisioned_below:
        return Classification.OVER_PROVISIONED
    if ratio > thresholds.under_provisioned_above:
        return Classification.UNDER_PROVISIONED
    return Classification.WELL_SIZED

def is_mature(container: ContainerMetrics, thresholds: Thresholds) -> bool:
    """Skip only what we know is young: an unknown age counts as mature."""
    return container.age_seconds is None or container.age_seconds >= thresholds.min_age_seconds

def analyze(
    metrics: list[ContainerMetrics],
    thresholds: Thresholds = Thresholds(),
) -> list[Finding]:
    """One finding per container and resource. Missing data is skipped, not guessed."""
    findings: list[Finding] = []
    for container in metrics:
        if not is_mature(container, thresholds):
            continue
        for resource in Resource:
            ratio = container.ratio(resource)
            if ratio is None:
                continue
            findings.append(
                Finding(container.key, resource, ratio, classify(ratio, thresholds))
            )
    return findings

