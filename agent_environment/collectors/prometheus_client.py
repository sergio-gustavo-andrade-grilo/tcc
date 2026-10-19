import httpx

from agent_environment.config import PROMETHEUS_URL
from agent_environment.core.models import ContainerKey, ContainerMetrics, Resource

CPU_REQUEST = 'kube_pod_container_resource_requests{resource="cpu"}'
MEMORY_REQUEST = 'kube_pod_container_resource_requests{resource="memory"}'
CPU_USAGE = "rate(container_cpu_usage_seconds_total[2m])"
MEMORY_USAGE = "container_memory_working_set_bytes"


def build_metrics(
    cpu_request: dict[ContainerKey, float],
    cpu_usage: dict[ContainerKey, float],
    memory_request: dict[ContainerKey, float],
    memory_usage: dict[ContainerKey, float],
) -> list[ContainerMetrics]:
    """Join the four result sets by container. Missing values stay None."""
    keys = cpu_request.keys() | cpu_usage.keys() | memory_request.keys() | memory_usage.keys()
    return [
        ContainerMetrics(
            key=key,
            cpu_request_cores=cpu_request.get(key),
            cpu_usage_cores=cpu_usage.get(key),
            memory_request_bytes=memory_request.get(key),
            memory_usage_bytes=memory_usage.get(key),
        )
        for key in sorted(keys, key=str)
    ]


class PrometheusClient:
    def __init__(self, base_url: str = PROMETHEUS_URL) -> None:
        self.base_url = base_url

    def _query(self, promql: str) -> dict[ContainerKey, float]:
        response = httpx.get(
            f"{self.base_url}/api/v1/query",
            params={"query": promql},
            timeout=10,
        )
        response.raise_for_status()
        result: dict[ContainerKey, float] = {}
        for series in response.json()["data"]["result"]:
            labels = series["metric"]
            if not all(name in labels for name in ("namespace", "pod", "container")):
                continue
            key = ContainerKey(labels["namespace"], labels["pod"], labels["container"])
            result[key] = float(series["value"][1])
        return result

    def collect(self) -> list[ContainerMetrics]:
        return build_metrics(
            cpu_request=self._query(CPU_REQUEST),
            cpu_usage=self._query(CPU_USAGE),
            memory_request=self._query(MEMORY_REQUEST),
            memory_usage=self._query(MEMORY_USAGE),
        )


def main() -> None:
    def fmt(value: float | None) -> str:
        return "-" if value is None else f"{value:.2f}"

    for m in PrometheusClient().collect():
        print(f"{m.key!s:<45} cpu={fmt(m.ratio(Resource.CPU)):>6}  mem={fmt(m.ratio(Resource.MEMORY)):>6}")


if __name__ == "__main__":
    main()