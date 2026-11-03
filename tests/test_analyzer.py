from agent_environment.core.analyzer import Thresholds, analyze, classify
from agent_environment.core.models import (
    Classification,
    ContainerKey,
    ContainerMetrics,
    Resource,
)

MI = 1024 * 1024


def pod(name, cpu_req, cpu_use, mem_req_mi, mem_use_mi):
    return ContainerMetrics(
        ContainerKey("default", name, "app"),
        cpu_request_cores=cpu_req,
        cpu_usage_cores=cpu_use,
        memory_request_bytes=mem_req_mi * MI,
        memory_usage_bytes=mem_use_mi * MI,
    )


def test_three_reference_pods():
    metrics = [
        pod("well-sized", 0.5, 0.4, 256, 200),
        pod("over-provisioned", 2.0, 0.1, 2048, 128),
        pod("under-provisioned", 0.2, 0.8, 128, 512),
    ]
    result = {(f.key.pod, f.resource): f.classification for f in analyze(metrics)}

    assert result[("well-sized", Resource.CPU)] is Classification.WELL_SIZED
    assert result[("over-provisioned", Resource.CPU)] is Classification.OVER_PROVISIONED
    assert result[("over-provisioned", Resource.MEMORY)] is Classification.OVER_PROVISIONED
    assert result[("under-provisioned", Resource.CPU)] is Classification.UNDER_PROVISIONED


def test_missing_data_is_skipped():
    only_requests = ContainerMetrics(ContainerKey("default", "x", "app"), cpu_request_cores=1.0)
    assert analyze([only_requests]) == []


def test_boundaries_are_well_sized():
    t = Thresholds(over_provisioned_below=0.3, under_provisioned_above=1.0)
    assert classify(0.3, t) is Classification.WELL_SIZED
    assert classify(1.0, t) is Classification.WELL_SIZED

def test_young_container_is_skipped():
    young = ContainerMetrics(
        ContainerKey("default", "new", "app"),
        cpu_request_cores=2.0,
        cpu_usage_cores=0.1,
        age_seconds=60.0,
    )
    assert analyze([young], Thresholds(min_age_seconds=300.0)) == []


def test_container_at_the_age_limit_is_analyzed():
    edge = ContainerMetrics(
        ContainerKey("default", "edge", "app"),
        cpu_request_cores=2.0,
        cpu_usage_cores=0.1,
        age_seconds=300.0,
    )
    assert len(analyze([edge], Thresholds(min_age_seconds=300.0))) == 1


def test_unknown_age_is_analyzed():
    unknown = ContainerMetrics(
        ContainerKey("default", "unknown", "app"),
        cpu_request_cores=2.0,
        cpu_usage_cores=0.1,
    )
    assert len(analyze([unknown], Thresholds(min_age_seconds=300.0))) == 1