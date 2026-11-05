import pytest

from agent_environment.collectors.prometheus_client import (
    CPU_REQUEST,
    CPU_USAGE,
    build_metrics,
    scoped,
    window_seconds,
)
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

def test_scoped_adds_cluster_matcher():
    query = scoped(CPU_REQUEST, "tcc-a")
    assert 'cluster="tcc-a"' in query
    assert "<c>" not in query


def test_scoped_escapes_quotes():
    assert 'cluster="a\\"b"' in scoped(CPU_REQUEST, 'a"b')

def test_scoped_sets_rate_window():
    query = scoped(CPU_USAGE, "tcc-a", window="30s")
    assert "[30s]" in query
    assert "<w>" not in query


def test_scoped_rejects_invalid_window():
    with pytest.raises(ValueError):
        scoped(CPU_USAGE, "tcc-a", window="30 seconds")


def test_window_seconds():
    assert window_seconds("30s") == 30
    assert window_seconds("2m") == 120