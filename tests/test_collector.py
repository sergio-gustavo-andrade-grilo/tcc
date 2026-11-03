from agent_environment.collectors.prometheus_client import build_metrics
from agent_environment.core.models import ContainerKey, Resource

A = ContainerKey("default", "a", "app")
B = ContainerKey("default", "b", "app")


def test_join_by_container():
    result = build_metrics(
        cpu_request={A: 1.0, B: 2.0},
        cpu_usage={A: 0.5},
        memory_request={A: 100.0},
        memory_usage={A: 50.0},
    )
    by_key = {m.key: m for m in result}
    assert by_key[A].ratio(Resource.CPU) == 0.5
    assert by_key[A].ratio(Resource.MEMORY) == 0.5
    assert by_key[B].ratio(Resource.CPU) is None

def test_age_is_joined_by_pod():
    result = build_metrics(
        cpu_request={A: 1.0},
        cpu_usage={},
        memory_request={},
        memory_usage={},
        pod_age={("default", "a"): 42.0},
    )
    assert result[0].age_seconds == 42.0