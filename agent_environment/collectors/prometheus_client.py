import re

import httpx

from agent_environment.config import CPU_RATE_WINDOW, PROMETHEUS_URL
from agent_environment.core.models import (
    ClusterSnapshot,
    ClusterSummary,
    ContainerKey,
    ContainerMetrics,
)

CPU_REQUEST = 'kube_pod_container_resource_requests{resource="cpu", <c>}'
MEMORY_REQUEST = 'kube_pod_container_resource_requests{resource="memory", <c>}'
CPU_USAGE = "rate(container_cpu_usage_seconds_total{<c>}[<w>])"
MEMORY_USAGE = "container_memory_working_set_bytes{<c>}"
POD_AGE = "time() - kube_pod_start_time{<c>}"

NODE_COUNT = "count(kube_node_info{<c>})"
CPU_CAPACITY = 'sum(kube_node_status_allocatable{resource="cpu", <c>})'
MEMORY_CAPACITY = 'sum(kube_node_status_allocatable{resource="memory", <c>})'
CPU_REQUESTED = 'sum(kube_pod_container_resource_requests{resource="cpu", node!="", <c>})'
MEMORY_REQUESTED = 'sum(kube_pod_container_resource_requests{resource="memory", node!="", <c>})'
CLUSTER_CPU_USAGE = "sum(rate(container_cpu_usage_seconds_total{<c>}[<w>]))"
CLUSTER_MEMORY_USAGE = "sum(container_memory_working_set_bytes{<c>})"
PENDING_PODS = 'count(kube_pod_status_phase{phase="Pending", <c>} == 1) or vector(0)'

CLUSTERS = "count by (cluster) (kube_node_info)"


_WINDOW = re.compile(r"\d+[smhd]")
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def window_seconds(window: str) -> int:
    if not _WINDOW.fullmatch(window):
        raise ValueError(f"invalid rate window: {window!r} (expected e.g. 30s or 2m)")
    return int(window[:-1]) * _UNIT_SECONDS[window[-1]]


def scoped(template: str, cluster: str, window: str = CPU_RATE_WINDOW) -> str:
    """Restrict a query template to one cluster and set its rate window."""
    window_seconds(window)  # validates the format
    escaped = cluster.replace("\\", "\\\\").replace('"', '\\"')
    return template.replace("<c>", f'cluster="{escaped}"').replace("<w>", window)


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

    def _pod_ages(self, cluster: str) -> dict[tuple[str, str], float]:
        ages: dict[tuple[str, str], float] = {}
        for series in self._result(scoped(POD_AGE, cluster)):
            labels = series["metric"]
            if "namespace" in labels and "pod" in labels:
                ages[(labels["namespace"], labels["pod"])] = float(series["value"][1])
        return ages

    def list_clusters(self) -> list[str]:
        names = {
            s["metric"]["cluster"]
            for s in self._result(CLUSTERS)
            if "cluster" in s["metric"]
        }
        return sorted(names)

    def collect(self, cluster: str) -> list[ContainerMetrics]:
        return build_metrics(
            cpu_request=self._query(scoped(CPU_REQUEST, cluster)),
            cpu_usage=self._query(scoped(CPU_USAGE, cluster)),
            memory_request=self._query(scoped(MEMORY_REQUEST, cluster)),
            memory_usage=self._query(scoped(MEMORY_USAGE, cluster)),
            pod_age=self._pod_ages(cluster),
        )

    def collect_summary(self, cluster: str) -> ClusterSummary:
        def scalar(template: str) -> float | None:
            return self._scalar(scoped(template, cluster))

        nodes = scalar(NODE_COUNT)
        pending = scalar(PENDING_PODS)
        return ClusterSummary(
            node_count=None if nodes is None else int(nodes),
            cpu_capacity_cores=scalar(CPU_CAPACITY),
            memory_capacity_bytes=scalar(MEMORY_CAPACITY),
            cpu_requested_cores=scalar(CPU_REQUESTED),
            memory_requested_bytes=scalar(MEMORY_REQUESTED),
            cpu_usage_cores=scalar(CLUSTER_CPU_USAGE),
            memory_usage_bytes=scalar(CLUSTER_MEMORY_USAGE),
            pending_pods=None if pending is None else int(pending),
        )

    def snapshot(self, cluster: str) -> ClusterSnapshot:
        return ClusterSnapshot(
            name=cluster,
            summary=self.collect_summary(cluster),
            containers=self.collect(cluster),
        )