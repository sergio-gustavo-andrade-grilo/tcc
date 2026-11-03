import httpx

from agent_environment.config import PROMETHEUS_URL
from agent_environment.core.models import (
    ClusterSummary,
    ContainerKey,
    ContainerMetrics,
    Resource,
)

CPU_REQUEST = 'kube_pod_container_resource_requests{resource="cpu"}'
MEMORY_REQUEST = 'kube_pod_container_resource_requests{resource="memory"}'
CPU_USAGE = "rate(container_cpu_usage_seconds_total[2m])"
MEMORY_USAGE = "container_memory_working_set_bytes"

NODE_COUNT = "count(kube_node_info)"
CPU_CAPACITY = 'sum(kube_node_status_allocatable{resource="cpu"})'
MEMORY_CAPACITY = 'sum(kube_node_status_allocatable{resource="memory"})'
CPU_REQUESTED = 'sum(kube_pod_container_resource_requests{resource="cpu", node!=""})'
MEMORY_REQUESTED = 'sum(kube_pod_container_resource_requests{resource="memory", node!=""})'
CLUSTER_CPU_USAGE = "sum(rate(container_cpu_usage_seconds_total[2m]))"
CLUSTER_MEMORY_USAGE = "sum(container_memory_working_set_bytes)"
PENDING_PODS = 'count(kube_pod_status_phase{phase="Pending"} == 1) or vector(0)'

POD_AGE = "time() - kube_pod_start_time"

def build_metrics(
    cpu_request: dict[ContainerKey, float],
    cpu_usage: dict[ContainerKey, float],
    memory_request: dict[ContainerKey, float],
    memory_usage: dict[ContainerKey, float],
    pod_age: dict[tuple[str, str], float] | None = None,
) -> list[ContainerMetrics]:
    """Join the result sets by container. Missing values stay None."""
    pod_age = pod_age or {}
    keys = cpu_request.keys() | cpu_usage.keys() | memory_request.keys() | memory_usage.keys()
    return [
        ContainerMetrics(
            key=key,
            cpu_request_cores=cpu_request.get(key),
            cpu_usage_cores=cpu_usage.get(key),
            memory_request_bytes=memory_request.get(key),
            memory_usage_bytes=memory_usage.get(key),
            age_seconds=pod_age.get((key.namespace, key.pod)),
        )
        for key in sorted(keys, key=str)
    ]


class PrometheusClient:
    def __init__(self, base_url: str = PROMETHEUS_URL) -> None:
        self.base_url = base_url

    def _result(self, promql: str) -> list[dict]:
        response = httpx.get(
            f"{self.base_url}/api/v1/query",
            params={"query": promql},
            timeout=10,
        )
        response.raise_for_status()
        return response.json()["data"]["result"]

    def _query(self, promql: str) -> dict[ContainerKey, float]:
        result: dict[ContainerKey, float] = {}
        for series in self._result(promql):
            labels = series["metric"]
            if not all(name in labels for name in ("namespace", "pod", "container")):
                continue
            key = ContainerKey(labels["namespace"], labels["pod"], labels["container"])
            result[key] = float(series["value"][1])
        return result

    def _scalar(self, promql: str) -> float | None:
        result = self._result(promql)
        if not result:
            return None
        return float(result[0]["value"][1])

    def _pod_ages(self) -> dict[tuple[str, str], float]:
        ages: dict[tuple[str, str], float] = {}
        for series in self._result(POD_AGE):
            labels = series["metric"]
            if "namespace" in labels and "pod" in labels:
                ages[(labels["namespace"], labels["pod"])] = float(series["value"][1])
        return ages

    def collect(self) -> list[ContainerMetrics]:
        return build_metrics(
            cpu_request=self._query(CPU_REQUEST),
            cpu_usage=self._query(CPU_USAGE),
            memory_request=self._query(MEMORY_REQUEST),
            memory_usage=self._query(MEMORY_USAGE),
            pod_age=self._pod_ages(),
        )

    def collect_summary(self) -> ClusterSummary:
        nodes = self._scalar(NODE_COUNT)
        pending = self._scalar(PENDING_PODS)
        return ClusterSummary(
            node_count=None if nodes is None else int(nodes),
            cpu_capacity_cores=self._scalar(CPU_CAPACITY),
            memory_capacity_bytes=self._scalar(MEMORY_CAPACITY),
            cpu_requested_cores=self._scalar(CPU_REQUESTED),
            memory_requested_bytes=self._scalar(MEMORY_REQUESTED),
            cpu_usage_cores=self._scalar(CLUSTER_CPU_USAGE),
            memory_usage_bytes=self._scalar(CLUSTER_MEMORY_USAGE),
            pending_pods=None if pending is None else int(pending),
        )


def main() -> None:
    def fmt(value: float | None) -> str:
        return "-" if value is None else f"{value:.2f}"

    for m in PrometheusClient().collect():
        print(f"{m.key!s:<45} cpu={fmt(m.ratio(Resource.CPU)):>6}  mem={fmt(m.ratio(Resource.MEMORY)):>6}")


if __name__ == "__main__":
    main()