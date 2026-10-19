from agent_environment.core.models import ContainerKey, ContainerMetrics, Resource

KEY = ContainerKey("default", "over-provisioned", "app")


def test_cpu_ratio():
    metrics = ContainerMetrics(KEY, cpu_request_cores=2.0, cpu_usage_cores=0.1)
    assert metrics.ratio(Resource.CPU) == 0.05


def test_missing_usage_gives_none():
    metrics = ContainerMetrics(KEY, cpu_request_cores=2.0)
    assert metrics.ratio(Resource.CPU) is None


def test_zero_request_gives_none():
    metrics = ContainerMetrics(KEY, cpu_request_cores=0.0, cpu_usage_cores=0.1)
    assert metrics.ratio(Resource.CPU) is None