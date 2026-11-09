# Directory Dump: `tcc-repo`

## Directory Tree

```
tcc-repo/
├── agent_environment/
│   ├── collectors/
│   │   └── prometheus_client.py
│   ├── config.py
│   ├── core/
│   │   ├── analyzer.py
│   │   ├── models.py
│   │   ├── openrouter_client.py
│   │   ├── report_log.py
│   │   └── reporter.py
│   ├── main.py
│   └── prompts/
│       └── report.txt
├── broker/
│   ├── models/
│   │   ├── __init__.py
│   │   └── types.py
│   ├── scenarios/
│   │   └── basic.json
│   └── src/
│       ├── adapters/
│       │   ├── __init__.py
│       │   ├── base_adapter.py
│       │   └── synthetic_adapter.py
│       └── injector/
│           ├── __init__.py
│           ├── cli.py
│           ├── events.py
│           ├── replay.py
│           └── runner.py
├── infra/
│   └── kwok/
│       ├── config/
│       │   ├── metrics-usage.yaml
│       │   ├── nodes.yaml
│       │   └── prometheus.yaml
│       ├── create_cluster.sh
│       ├── destroy_cluster.sh
│       ├── docker-compose.ksm.yaml
│       ├── docker-compose.yaml
│       └── examples/
│           ├── test-pod.yaml
│           ├── unschedulable-pod.yaml
│           └── workload.yaml
├── main.py
├── README.md
├── repo.md
├── scripts/
│   ├── check_event_codes.py
│   └── inspect_borg.py
└── tests/
    ├── test_analyzer.py
    ├── test_collector.py
    ├── test_injector.py
    ├── test_models.py
    ├── test_openrouter_client.py
    ├── test_report_log.py
    └── test_reporter.py
```

## File Contents

### `tcc-repo/agent_environment/collectors/prometheus_client.py`

```python
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
PENDING_POD_NAMES = 'kube_pod_status_phase{phase="Pending", <c>} == 1'

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


def _pending_names(self, cluster: str) -> tuple[str, ...]:
    names = {
        f"{s['metric']['namespace']}/{s['metric']['pod']}"
        for s in self._result(scoped(PENDING_POD_NAMES, cluster))
        if "namespace" in s["metric"] and "pod" in s["metric"]
    }
    return tuple(sorted(names))


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
            pending_pod_names=self._pending_names(cluster),
        )

    def snapshot(self, cluster: str) -> ClusterSnapshot:
        return ClusterSnapshot(
            name=cluster,
            summary=self.collect_summary(cluster),
            containers=self.collect(cluster),
        )
```

### `tcc-repo/agent_environment/config.py`

```python
import os

from dotenv import load_dotenv

load_dotenv()

PROMETHEUS_URL = os.environ.get("PROMETHEUS_URL", "http://localhost:9090")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL")
CPU_RATE_WINDOW = os.environ.get("CPU_RATE_WINDOW", "1m")
MIN_POD_AGE_SECONDS = float(os.environ.get("MIN_POD_AGE_SECONDS", "120"))
REPORT_LOG_PATH = os.environ.get("REPORT_LOG_PATH", "data/processed/reports.jsonl")
```

### `tcc-repo/agent_environment/core/analyzer.py`

```python
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


```

### `tcc-repo/agent_environment/core/models.py`

```python
from dataclasses import dataclass
from enum import Enum


class Resource(str, Enum):
    CPU = "cpu"
    MEMORY = "memory"


class Classification(str, Enum):
    OVER_PROVISIONED = "over_provisioned"
    WELL_SIZED = "well_sized"
    UNDER_PROVISIONED = "under_provisioned"


@dataclass(frozen=True)
class ContainerKey:
    namespace: str
    pod: str
    container: str

    def __str__(self) -> str:
        return f"{self.namespace}/{self.pod}/{self.container}"


@dataclass(frozen=True)
class ContainerMetrics:
    """Raw values for one container. None means Prometheus had no data."""

    key: ContainerKey
    cpu_request_cores: float | None = None
    cpu_usage_cores: float | None = None
    memory_request_bytes: float | None = None
    memory_usage_bytes: float | None = None
    age_seconds: float | None = None

    def ratio(self, resource: Resource) -> float | None:
        """usage / request, or None if either value is missing or the request is 0."""
        if resource is Resource.CPU:
            usage, request = self.cpu_usage_cores, self.cpu_request_cores
        else:
            usage, request = self.memory_usage_bytes, self.memory_request_bytes
        if usage is None or request is None or request <= 0:
            return None
        return usage / request


@dataclass(frozen=True)
class Finding:
    key: ContainerKey
    resource: Resource
    ratio: float
    classification: Classification

def _fraction(part: float | None, whole: float | None) -> float | None:
    if part is None or whole is None or whole <= 0:
        return None
    return part / whole


@dataclass(frozen=True)
class ClusterSummary:
    """Cluster-wide numbers. None means Prometheus had no data for that value."""

    node_count: int | None = None
    cpu_capacity_cores: float | None = None
    memory_capacity_bytes: float | None = None
    cpu_requested_cores: float | None = None
    memory_requested_bytes: float | None = None
    cpu_usage_cores: float | None = None
    memory_usage_bytes: float | None = None
    pending_pods: int | None = None,
    pending_pod_names: tuple[str, ...] = ()

    def has_data(self) -> bool:
        return bool(self.node_count)

    def requested_fraction(self, resource: Resource) -> float | None:
        """Share of the cluster capacity reserved by pods placed on nodes."""
        if resource is Resource.CPU:
            return _fraction(self.cpu_requested_cores, self.cpu_capacity_cores)
        return _fraction(self.memory_requested_bytes, self.memory_capacity_bytes)

    def usage_fraction(self, resource: Resource) -> float | None:
        """Share of the cluster capacity actually used."""
        if resource is Resource.CPU:
            return _fraction(self.cpu_usage_cores, self.cpu_capacity_cores)
        return _fraction(self.memory_usage_bytes, self.memory_capacity_bytes)

@dataclass(frozen=True)
class ClusterSnapshot:
    name: str
    summary: ClusterSummary
    containers: list[ContainerMetrics]
```

### `tcc-repo/agent_environment/core/openrouter_client.py`

```python
import time
from dataclasses import dataclass

import httpx

from agent_environment.config import OPENROUTER_API_KEY, OPENROUTER_MODEL, OPENROUTER_URL


@dataclass(frozen=True)
class CallStats:
    model: str | None
    latency_seconds: float
    prompt_tokens: int | None
    completion_tokens: int | None


class OpenRouterClient:
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        url: str = OPENROUTER_URL,
        http: httpx.Client | None = None,
        temperature: float = 0.0,
    ) -> None:
        self.api_key = api_key if api_key is not None else OPENROUTER_API_KEY
        self.model = model if model is not None else OPENROUTER_MODEL
        if not self.api_key:
            raise ValueError("OPENROUTER_API_KEY is not set")
        if not self.model:
            raise ValueError("OPENROUTER_MODEL is not set")
        self.url = url
        self.temperature = temperature
        self._http = http or httpx.Client()
        self.last_stats: CallStats | None = None

    def complete(self, prompt: str) -> str:
        start = time.perf_counter()
        response = self._http.post(
            self.url,
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "temperature": self.temperature,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=60,
        )
        latency = time.perf_counter() - start
        response.raise_for_status()
        data = response.json()
        usage = data.get("usage") or {}
        self.last_stats = CallStats(
            model=data.get("model"),
            latency_seconds=latency,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
        )
        return data["choices"][0]["message"]["content"]
```

### `tcc-repo/agent_environment/core/report_log.py`

```python
import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class ReportRecord:
    timestamp: str
    cluster: str
    containers: int
    findings: int
    model: str | None
    latency_seconds: float | None
    prompt_tokens: int | None
    completion_tokens: int | None
    report: str


def append_record(path: str | Path, record: ReportRecord) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")
```

### `tcc-repo/agent_environment/core/reporter.py`

```python
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from agent_environment.core.models import ClusterSummary, Finding, Resource

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "report.txt"

NO_DATA_REPORT = "No report: Prometheus returned no usable data yet."

GIB = 1024**3


class LLMClient(Protocol):
    def complete(self, prompt: str) -> str: ...


def _pct(value: float | None) -> str:
    return "unavailable" if value is None else f"{value * 100:.1f}%"


def _num(value: float | None, unit: str, scale: float = 1.0) -> str:
    return "unavailable" if value is None else f"{value / scale:.2f} {unit}"


def summary_to_text(summary: ClusterSummary) -> str:
    cpu, mem = Resource.CPU, Resource.MEMORY
    pending = (
        "unavailable" if summary.pending_pods is None else str(summary.pending_pods)
    )
    if summary.pending_pod_names:
        pending += f" ({', '.join(summary.pending_pod_names)})"
    nodes = "unavailable" if summary.node_count is None else str(summary.node_count)
    return "\n".join(
        [
            f"- nodes: {nodes}",
            (f"- cpu: capacity {_num(summary.cpu_capacity_cores, 'cores')}, "
            f"requested {_num(summary.cpu_requested_cores, 'cores')} "
            f"({_pct(summary.requested_fraction(cpu))} of capacity), "
            f"used {_num(summary.cpu_usage_cores, 'cores')} "
            f"({_pct(summary.usage_fraction(cpu))} of capacity)"),
            (f"- memory: capacity {_num(summary.memory_capacity_bytes, 'GiB', GIB)}, "
            f"requested {_num(summary.memory_requested_bytes, 'GiB', GIB)} "
            f"({_pct(summary.requested_fraction(mem))} of capacity), "
            f"used {_num(summary.memory_usage_bytes, 'GiB', GIB)} "
            f"({_pct(summary.usage_fraction(mem))} of capacity)"),
            f"- pending pods: {pending}",
        ]
    )


def findings_to_text(findings: list[Finding]) -> str:
    if not findings:
        return "(no per-container findings)"
    return "\n".join(
        f"- {f.key} | {f.resource.value} | ratio={f.ratio:.2f} | {f.classification.value}"
        for f in sorted(findings, key=lambda f: (str(f.key), f.resource.value))
    )


def skipped_to_text(skipped: Sequence[str]) -> str:
    return ", ".join(skipped) if skipped else "none"


def build_prompt(cluster, findings, summary, template=None, skipped: Sequence[str] = ()) -> str:
    if template is None:
        template = PROMPT_PATH.read_text(encoding="utf-8")
    return (
        template.replace("{cluster}", cluster)
        .replace("{summary}", summary_to_text(summary))
        .replace("{findings}", findings_to_text(findings))
        .replace("{skipped}", skipped_to_text(skipped))
    )


def generate_report(cluster, findings, summary, client, skipped: Sequence[str] = ()) -> str:
    if not findings and not summary.has_data():
        return NO_DATA_REPORT
    return client.complete(build_prompt(cluster, findings, summary, skipped=skipped))
```

### `tcc-repo/agent_environment/main.py`

```python
import argparse
import time
from datetime import datetime, timezone
from functools import cache

import httpx

from agent_environment.collectors.prometheus_client import (
    PrometheusClient,
    window_seconds,
)
from agent_environment.config import (
    CPU_RATE_WINDOW,
    MIN_POD_AGE_SECONDS,
    REPORT_LOG_PATH,
)
from agent_environment.core.analyzer import Thresholds, analyze, is_mature
from agent_environment.core.models import Classification, Finding
from agent_environment.core.openrouter_client import OpenRouterClient
from agent_environment.core.report_log import ReportRecord, append_record
from agent_environment.core.reporter import generate_report, summary_to_text


@cache
def get_client() -> OpenRouterClient:
    """Created on first use, so the tables work even without an API key."""
    return OpenRouterClient()


def format_findings(findings: list[Finding]) -> str:
    if not findings:
        return "No findings: Prometheus returned no usable data yet."
    lines = [f"{'container':<45}{'resource':<9}{'ratio':>7}  classification"]
    for f in sorted(findings, key=lambda f: (str(f.key), f.resource.value)):
        lines.append(
            f"{f.key!s:<45}{f.resource.value:<9}{f.ratio:>7.2f}  {f.classification.value}"
        )
    over = sum(f.classification is Classification.OVER_PROVISIONED for f in findings)
    under = sum(f.classification is Classification.UNDER_PROVISIONED for f in findings)
    lines.append(f"\n{len(findings)} findings: {over} over-provisioned, {under} under-provisioned")
    return "\n".join(lines)


def run_once(
    prometheus: PrometheusClient,
    requested_clusters: list[str] | None,
    thresholds: Thresholds,
    use_llm: bool,
    keep_going: bool,
) -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    clusters = requested_clusters or prometheus.list_clusters()
    if not clusters:
        print(f"[{stamp}] No clusters found in Prometheus. Is the infra up?\n")
        return

    for name in clusters:
        try:
            snapshot = prometheus.snapshot(name)
            findings = analyze(snapshot.containers, thresholds)
            young = [m for m in snapshot.containers if not is_mature(m, thresholds)]

            print("=" * 60)
            print(f"Cluster: {name}   [{stamp}]")
            print("=" * 60)
            print(summary_to_text(snapshot.summary))
            print()
            print(format_findings(findings))
            if young:
                skipped = sorted({f"{m.key.namespace}/{m.key.pod}" for m in young})
                if skipped:
                    print(f"\nSkipped (younger than {thresholds.min_age_seconds:.0f}s): {', '.join(skipped)}")

            if use_llm:
                client = get_client()
                client.last_stats = None  # otherwise a skipped call would log stale numbers
                report = generate_report(name, findings, snapshot.summary, client, skipped=skipped)
                print("\n--- report ---\n")
                print(report)
                stats = client.last_stats
                if stats:
                    print(
                        f"\n(model={stats.model} latency={stats.latency_seconds:.1f}s "
                        f"tokens in/out={stats.prompt_tokens}/{stats.completion_tokens})"
                    )
                append_record(
                    REPORT_LOG_PATH,
                    ReportRecord(
                        timestamp=stamp,
                        cluster=name,
                        containers=len(snapshot.containers),
                        findings=len(findings),
                        model=stats.model if stats else None,
                        latency_seconds=stats.latency_seconds if stats else None,
                        prompt_tokens=stats.prompt_tokens if stats else None,
                        completion_tokens=stats.completion_tokens if stats else None,
                        report=report,
                    ),
                )
            print()
        except httpx.HTTPError as error:
            if not keep_going:
                raise
            print(f"[{stamp}] {name}: request failed: {error}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Cluster resource usage report")
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="print only the findings tables, without calling the LLM",
    )
    parser.add_argument(
        "--cluster",
        action="append",
        help="cluster to report on (repeatable); default: all clusters in Prometheus",
    )
    parser.add_argument(
        "--interval",
        type=float,
        help="generate reports every N seconds until interrupted; default: run once",
    )
    args = parser.parse_args()
    if MIN_POD_AGE_SECONDS < window_seconds(CPU_RATE_WINDOW):
        print(
            f"warning: MIN_POD_AGE_SECONDS ({MIN_POD_AGE_SECONDS:g}) is shorter than "
            f"CPU_RATE_WINDOW ({CPU_RATE_WINDOW}); new pods may be misclassified"
        )

    if args.interval is not None and args.interval <= 0:
        parser.error("--interval must be positive")

    prometheus = PrometheusClient()
    thresholds = Thresholds(min_age_seconds=MIN_POD_AGE_SECONDS)
    use_llm = not args.no_llm

    if args.interval is None:
        run_once(prometheus, args.cluster, thresholds, use_llm, keep_going=False)
        return

    print(f"Reporting every {args.interval:g}s. Ctrl+C to stop.\n")
    next_run = time.monotonic()
    try:
        while True:
            try:
                run_once(prometheus, args.cluster, thresholds, use_llm, keep_going=True)
            except httpx.HTTPError as error:
                print(f"[error] {error}\n")
            next_run += args.interval
            time.sleep(max(0.0, next_run - time.monotonic()))
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
```

### `tcc-repo/agent_environment/prompts/report.txt`

```
You are analyzing the state of the Kubernetes cluster "{cluster}" from Prometheus metrics.

Cluster overview (computed from the metrics):

{summary}

Per-container findings. Each line gives a container, a resource, the ratio of
actual usage to requested resources, and a classification:

{findings}

Pods skipped because they are too young to be classified reliably:

{skipped}

Write a short report in Portuguese with these sections:
1. Cluster overview: the cluster name, number of nodes, CPU and memory capacity, 
   how much of the capacity is requested (allocated) and how much is actually used,
   and whether there are pending pods. Mention the skipped pods, if any.
2. Over-provisioned containers and under-provisioned containers, from the findings.
3. A note that the findings are only as reliable as the metrics behind them.

Rules:
- Use only the data above. Do not invent numbers or containers.
- Report numbers exactly as given; do not recompute them.
- If a value says "unavailable", say that it is unavailable.
- Do not make recommendations; only describe what was observed.
```

### `tcc-repo/broker/models/__init__.py`

```python

```

### `tcc-repo/broker/models/types.py`

```python
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Machine(BaseModel):
    """
    The capacity of a physical machine/node.
    Can represent, for example, a Kubernetes or Slurm node.
    """

    id: str = Field(
        ..., title="ID", description="The source machine's unique identifier."
    )
    cpu_cores: float = Field(
        ...,
        gt=0,
        description="The amount of CPU cores the machine can offer."
        "This value may be an absolute value or a percentage."
        "Percentage values need a reference constant in order to"
        "be converted to absolute values.",
    )
    mem_capacity: float = Field(
        ...,
        gt=0,
        description="The amount of memory the machine can offer."
        "This value may be an absolute value or a percentage."
        "Percentage values need a reference constant in order to"
        "be converted to absolute values.",
    )
    disk_capacity: float | None = Field(
        default=None,
        gt=0,
        description="The amount of disk the machine can offer."
        "This value may be an absolute value or a percentage."
        "Percentage values need a reference constant in order to"
        "be converted to absolute values.",
    )
    extra_fields: dict[str, Any] = Field(
        default_factory=dict,
        description="Extra fields from the dataset that do not"
        "represent any of the fields above.",
    )


class Workload(BaseModel):
    """
    A unit of work for the machine.
    Can represent, for example, a Kubernetes pod or a Slurm job.
    """

    model_config = ConfigDict(frozen=True)

    id: str = Field(
        ...,
    )
    cpu_request: float = Field(
        ...,
        gt=0,
        description="The amount of CPU cores the workload requests."
        "This value may be an absolute value or a percentage."
        "Percentage values need a reference constant in order to"
        "be converted to absolute values.",
    )
    mem_request: float = Field(
        ...,
        gt=0,
        description="The amount of memory the workload requests."
        "This value may be an absolute value or a percentage."
        "Percentage values need a reference constant in order to"
        "be converted to absolute values.",
    )
    machine_id: str | None = Field(
        default=None,
        description="The ID of the machine where this workload runs."
        "Defaults to None while unallocated.",
    )
    depends_on: list[str] = Field(
        default_factory=list,
        description="IDs of other workloads that need to be completed"
        "before this one starts.",
    )
    extra_fields: dict[str, Any] = Field(
        default_factory=dict,
        description="Extra fields from the dataset that do not"
        "represent any of the fields above.",
    )


class UsageSample(BaseModel):
    """
    An actual resource usage measurement in a given instant.
    """

    model_config = ConfigDict(frozen=True)

    entity_id: str = Field(
        ..., description="Points to a machine ID or to a workload ID."
    )
    timestamp: datetime = Field(
        ...,
        description="The instant of the measurement, in UTC format."
        "It's an absolute measurement, not relative to the start of"
        "the workflow.",
    )
    cpu_util: float = Field(
        ...,
        ge=0,
        le=100,
        description="Percentage of the total CPU capacity used by the workload",
    )
    mem_util: float = Field(
        ...,
        ge=0,
        le=100,
        description="Percentage of the total memory capacity used by the workload",
    )
    extra_fields: dict[str, Any] = Field(
        default_factory=dict,
        description="Extra fields from the dataset that do not"
        "represent any of the fields above.",
    )

```

### `tcc-repo/broker/scenarios/basic.json`

```json
[
  {"at": 0, "cluster": "tcc-a", "action": "create", "pod": "well-sized", "cpu_request_m": 500, "memory_request_mi": 256, "cpu_usage_m": 400, "memory_usage_mi": 200},
  {"at": 0, "cluster": "tcc-a", "action": "create", "pod": "over-provisioned", "cpu_request_m": 2000, "memory_request_mi": 2048, "cpu_usage_m": 100, "memory_usage_mi": 128},
  {"at": 0, "cluster": "tcc-a", "action": "create", "pod": "under-provisioned", "cpu_request_m": 200, "memory_request_mi": 128, "cpu_usage_m": 800, "memory_usage_mi": 512},
  {"at": 0, "cluster": "tcc-b", "action": "create", "pod": "busy-app", "cpu_request_m": 500, "memory_request_mi": 512, "cpu_usage_m": 450, "memory_usage_mi": 400},
  {"at": 0, "cluster": "tcc-b", "action": "create", "pod": "idle-app", "cpu_request_m": 2000, "memory_request_mi": 4096, "cpu_usage_m": 50, "memory_usage_mi": 100},
  {"at": 420, "cluster": "tcc-b", "action": "create", "pod": "too-big", "cpu_request_m": 1000000, "memory_request_mi": 1024},
  {"at": 600, "cluster": "tcc-a", "action": "delete", "pod": "over-provisioned"},
  {"at": 720, "cluster": "tcc-b", "action": "delete", "pod": "too-big"}
]
```

### `tcc-repo/broker/src/adapters/__init__.py`

```python

```

### `tcc-repo/broker/src/adapters/base_adapter.py`

```python
from abc import ABC, abstractmethod
from collections.abc import Iterator

from broker.models.types import Machine, UsageSample, Workload


class DataAdapter(ABC):
    @abstractmethod
    def get_machines(self) -> Iterator[Machine]:
        """Reads and returns the available machines of the cluster."""

    @abstractmethod
    def get_workloads(self) -> Iterator[Workload]:
        """Reads and returns the jobs/pods to be executed as workloads."""

    @abstractmethod
    def get_usage_samples(self) -> Iterator[UsageSample]:
        """Reads and returns the resource usage temporal series."""

```

### `tcc-repo/broker/src/adapters/synthetic_adapter.py`

```python
# broker/src/adapters/synthetic_adapter.py
import time
from collections.abc import Iterator

from broker.models.types import Machine, UsageSample, Workload
from broker.src.adapters.base_adapter import DataAdapter


class SyntheticAdapter(DataAdapter):
    def get_machines(self) -> Iterator[Machine]:
        # Create two K8S test nodes
        yield Machine(
            id="node-1", cpu_cores=4.0, mem_capacity=16.0, disk_capacity=100.0
        )
        yield Machine(
            id="node-2", cpu_cores=8.0, mem_capacity=32.0, disk_capacity=200.0
        )

    def get_workloads(self) -> Iterator[Workload]:
        # Create two pods
        yield Workload(
            id="pod-web", cpu_request=2.0, mem_request=4.0, machine_id="node-1"
        )
        yield Workload(
            id="pod-db", cpu_request=4.0, mem_request=16.0, machine_id="node-2"
        )

    def get_usage_samples(self) -> Iterator[UsageSample]:
        # Simulate usage in current time
        now = time.time()

        # pod-web is idle
        yield UsageSample(
            entity_id="pod-web", timestamp=now, cpu_util=0.1, mem_util=0.5
        )

        # pod-db is a bottleneck
        yield UsageSample(
            entity_id="pod-db", timestamp=now, cpu_util=0.95, mem_util=0.98
        )

```

### `tcc-repo/broker/src/injector/__init__.py`

```python

```

### `tcc-repo/broker/src/injector/cli.py`

```python
import argparse

from broker.src.injector.events import load_scenario
from broker.src.injector.replay import replay
from broker.src.injector.runner import KubectlRunner


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay a scenario on KWOK clusters")
    parser.add_argument("scenario", help="path to a scenario JSON file")
    parser.add_argument(
        "--speed",
        type=float,
        default=1.0,
        help="speed factor: 2 plays the scenario twice as fast (default: 1)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the schedule without touching the clusters",
    )
    args = parser.parse_args()
    if args.speed <= 0:
        parser.error("--speed must be positive")

    events = load_scenario(args.scenario)

    if args.dry_run:
        for e in sorted(events, key=lambda e: e.at_seconds):
            print(f"t={e.at_seconds / args.speed:>6.0f}s  {e.cluster}  {e.action.value}  {e.pod.namespace}/{e.pod.name}")
        return

    try:
        failures = replay(events, KubectlRunner(), speed=args.speed)
    except KeyboardInterrupt:
        print("\ninterrupted; pods already created were left in the clusters")
        raise SystemExit(130)
    
    print(f"done, {failures} failed event(s)")
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
```

### `tcc-repo/broker/src/injector/events.py`

```python
import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class Action(str, Enum):
    CREATE = "create"
    DELETE = "delete"


@dataclass(frozen=True)
class PodSpec:
    """For DELETE events only name and namespace matter."""

    name: str
    namespace: str = "default"
    cpu_request_m: int = 0
    memory_request_mi: int = 0
    cpu_usage_m: int | None = None  # None: no simulated usage (e.g. a pod that never runs)
    memory_usage_mi: int | None = None


@dataclass(frozen=True)
class Event:
    at_seconds: float  # offset from the start of the replay, in scenario time
    cluster: str
    action: Action
    pod: PodSpec


def load_scenario(path: str | Path) -> list[Event]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    events: list[Event] = []
    for index, item in enumerate(raw):
        try:
            action = Action(item["action"])
            creating = action is Action.CREATE
            pod = PodSpec(
                name=item["pod"],
                namespace=item.get("namespace", "default"),
                cpu_request_m=item["cpu_request_m"] if creating else 0,
                memory_request_mi=item["memory_request_mi"] if creating else 0,
                cpu_usage_m=item.get("cpu_usage_m"),
                memory_usage_mi=item.get("memory_usage_mi"),
            )
            events.append(Event(float(item["at"]), item["cluster"], action, pod))
        except (KeyError, ValueError) as error:
            raise ValueError(f"invalid event #{index} in {path}: {error!r}") from error
    return events
```

### `tcc-repo/broker/src/injector/replay.py`

```python
import time
from collections.abc import Callable

from broker.src.injector.events import Action, Event
from broker.src.injector.runner import Runner, pod_manifest


def replay(
    events: list[Event],
    runner: Runner,
    speed: float = 1.0,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    log: Callable[[str], None] = print,
) -> int:
    """Run the events at their scaled times. Returns how many of them failed."""
    if speed <= 0:
        raise ValueError("speed must be positive")

    start = clock()
    failures = 0
    for event in sorted(events, key=lambda e: e.at_seconds):  # stable: ties keep file order
        wait = start + event.at_seconds / speed - clock()
        if wait > 0:
            sleep(wait)

        label = f"[t={event.at_seconds:>6.0f}s] {event.cluster} {event.action.value} {event.pod.namespace}/{event.pod.name}"
        try:
            if event.action is Action.CREATE:
                runner.apply(event.cluster, pod_manifest(event.pod))
            else:
                runner.delete(event.cluster, event.pod.namespace, event.pod.name)
            log(label)
        except RuntimeError as error:
            failures += 1
            log(f"{label} FAILED: {error}")
    return failures
```

### `tcc-repo/broker/src/injector/runner.py`

```python
import json
import subprocess
from typing import Protocol

from broker.src.injector.events import PodSpec


class Runner(Protocol):
    def apply(self, cluster: str, manifest: dict) -> None: ...
    def delete(self, cluster: str, namespace: str, name: str) -> None: ...


def pod_manifest(spec: PodSpec) -> dict:
    annotations: dict[str, str] = {}
    if spec.cpu_usage_m is not None:
        annotations["kwok.x-k8s.io/usage-cpu"] = f"{spec.cpu_usage_m}m"
    if spec.memory_usage_mi is not None:
        annotations["kwok.x-k8s.io/usage-memory"] = f"{spec.memory_usage_mi}Mi"
    return {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": spec.name,
            "namespace": spec.namespace,
            "annotations": annotations,
        },
        "spec": {
            "containers": [
                {
                    "name": "app",
                    "image": "nginx",
                    "resources": {
                        "requests": {
                            "cpu": f"{spec.cpu_request_m}m",
                            "memory": f"{spec.memory_request_mi}Mi",
                        }
                    },
                }
            ]
        },
    }


def _kubectl(cluster: str, args: list[str], stdin: str | None = None) -> None:
    command = ["kubectl", "--context", f"kwok-{cluster}", *args]
    result = subprocess.run(command, input=stdin, text=True, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"kubectl exited with {result.returncode}")


class KubectlRunner:
    def apply(self, cluster: str, manifest: dict) -> None:
        _kubectl(cluster, ["apply", "-f", "-"], json.dumps(manifest))

    def delete(self, cluster: str, namespace: str, name: str) -> None:
        _kubectl(
            cluster,
            ["delete", "pod", name, "-n", namespace, "--ignore-not-found", "--wait=false"],
        )
```

### `tcc-repo/infra/kwok/config/metrics-usage.yaml`

```yaml
apiVersion: kwok.x-k8s.io/v1alpha1
kind: ClusterResourceUsage
metadata:
  name: usage-from-annotation
spec:
  usages:
    - usage:
        cpu:
          expression: |
            "kwok.x-k8s.io/usage-cpu" in pod.metadata.annotations
            ? Quantity(pod.metadata.annotations["kwok.x-k8s.io/usage-cpu"])
            : Quantity("1m")
        memory:
          expression: |
            "kwok.x-k8s.io/usage-memory" in pod.metadata.annotations
            ? Quantity(pod.metadata.annotations["kwok.x-k8s.io/usage-memory"])
            : Quantity("1Mi")
---
apiVersion: kwok.x-k8s.io/v1alpha1
kind: Metric
metadata:
  name: metrics-resource
spec:
  metrics:
    - dimension: node
      help: |
        [ALPHA] 1 if there was an error while getting metrics from the node, 0 otherwise
      kind: gauge
      name: scrape_error
      value: "0"
    - dimension: container
      help: |
        [ALPHA] Start time of the container since unix epoch in seconds
      kind: gauge
      labels:
        - name: container
          value: container.name
        - name: namespace
          value: pod.metadata.namespace
        - name: pod
          value: pod.metadata.name
      name: container_start_time_seconds
      value: pod.SinceSecond()
    - dimension: container
      help: |
        [ALPHA] Cumulative cpu time consumed by the container in core-seconds
      kind: counter
      labels:
        - name: container
          value: container.name
        - name: namespace
          value: pod.metadata.namespace
        - name: pod
          value: pod.metadata.name
      name: container_cpu_usage_seconds_total
      value: pod.CumulativeUsage("cpu", container.name)
    - dimension: container
      help: |
        [ALPHA] Current working set of the container in bytes
      kind: gauge
      labels:
        - name: container
          value: container.name
        - name: namespace
          value: pod.metadata.namespace
        - name: pod
          value: pod.metadata.name
      name: container_memory_working_set_bytes
      value: pod.Usage("memory", container.name)
    - dimension: pod
      help: |
        [ALPHA] Cumulative cpu time consumed by the pod in core-seconds
      kind: counter
      labels:
        - name: namespace
          value: pod.metadata.namespace
        - name: pod
          value: pod.metadata.name
      name: pod_cpu_usage_seconds_total
      value: pod.CumulativeUsage("cpu")
    - dimension: pod
      help: |
        [ALPHA] Current working set of the pod in bytes
      kind: gauge
      labels:
        - name: namespace
          value: pod.metadata.namespace
        - name: pod
          value: pod.metadata.name
      name: pod_memory_working_set_bytes
      value: pod.Usage("memory")
    - dimension: node
      help: |
        [ALPHA] Cumulative cpu time consumed by the node in core-seconds
      kind: counter
      name: node_cpu_usage_seconds_total
      value: node.CumulativeUsage("cpu")
    - dimension: node
      help: |
        [ALPHA] Current working set of the node in bytes
      kind: gauge
      name: node_memory_working_set_bytes
      value: node.Usage("memory")
  path: /metrics/nodes/{nodeName}/metrics/resource

```

### `tcc-repo/infra/kwok/config/nodes.yaml`

```yaml
apiVersion: v1
kind: Node
metadata:
  name: kwok-node-1
  annotations:
    node.alpha.kubernetes.io/ttl: "0"
    kwok.x-k8s.io/node: fake
  labels:
    type: kwok
    kubernetes.io/hostname: kwok-node-1
status:
  allocatable:
    cpu: "32"
    memory: 256Gi
    pods: "110"
  capacity:
    cpu: "32"
    memory: 256Gi
    pods: "110"

```

### `tcc-repo/infra/kwok/config/prometheus.yaml`

```yaml
global:
  scrape_interval: 5s

scrape_configs:
  - job_name: kube-state-metrics
    file_sd_configs:
      - files: ["/etc/prometheus/targets/ksm-*.json"]

  - job_name: kwok-usage
    scheme: https
    tls_config:
      insecure_skip_verify: true
    file_sd_configs:
      - files: ["/etc/prometheus/targets/usage-*.json"]
```

### `tcc-repo/infra/kwok/create_cluster.sh`

```bash
#!/usr/bin/env bash
# Usage: create_cluster.sh [cluster-name ...]   (default: tcc-a tcc-b)
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GEN="$DIR/.generated"
KSM_BASE_PORT=8080

CLUSTERS=("$@")
if [ ${#CLUSTERS[@]} -eq 0 ]; then
  CLUSTERS=(tcc-a tcc-b)
fi

# ===== Cleanup =====
docker compose -f "$DIR/docker-compose.yaml" down --remove-orphans 2>/dev/null || true
for name in "${CLUSTERS[@]}"; do
  CLUSTER="$name" docker compose -p "ksm-$name" -f "$DIR/docker-compose.ksm.yaml" down 2>/dev/null || true
  kwokctl delete cluster --name "$name" 2>/dev/null || true
done
rm -rf "$GEN"
mkdir -p "$GEN/targets"

# ===== Clusters =====
index=0
for name in "${CLUSTERS[@]}"; do
  ctx="kwok-$name"
  ksm_port=$((KSM_BASE_PORT + 10 * index))

  echo ">> creating cluster $name"
  kwokctl create cluster --name "$name" --runtime docker --wait 120s \
    --enable metrics-server -c "$DIR/config/metrics-usage.yaml"

  kubectl --context "$ctx" get --raw=/readyz && echo
  kubectl --context "$ctx" apply -f "$DIR/config/nodes.yaml"

  mkdir -p "$GEN/$name"
  kubectl config view --raw --minify --flatten --context "$ctx" > "$GEN/$name/kubeconfig"

  # kube-state-metrics for this cluster
  CLUSTER="$name" KSM_PORT="$ksm_port" KSM_TELEMETRY_PORT=$((ksm_port + 1)) \
    docker compose -p "ksm-$name" -f "$DIR/docker-compose.ksm.yaml" up -d

  # Prometheus targets for this cluster
  echo "[{\"targets\": [\"localhost:${ksm_port}\"], \"labels\": {\"cluster\": \"$name\"}}]" \
    > "$GEN/targets/ksm-$name.json"

  kwok_ip=$(docker inspect "kwok-${name}-kwok-controller" \
    --format "{{(index .NetworkSettings.Networks \"kwok-${name}\").IPAddress}}")
  entries=()
  for node in $(kubectl --context "$ctx" get nodes -o jsonpath='{.items[*].metadata.name}'); do
    entries+=("{\"targets\": [\"${kwok_ip}:10247\"], \"labels\": {\"cluster\": \"$name\", \"node\": \"$node\", \"__metrics_path__\": \"/metrics/nodes/$node/metrics/resource\"}}")
  done
  echo "[$(IFS=,; echo "${entries[*]}")]" > "$GEN/targets/usage-$name.json"

  index=$((index + 1))
done

# ===== Monitoring =====
docker compose -f "$DIR/docker-compose.yaml" up -d
```

### `tcc-repo/infra/kwok/destroy_cluster.sh`

```bash
#!/usr/bin/env bash
# Usage: destroy_cluster.sh [cluster-name ...]   (default: tcc-a tcc-b)
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

CLUSTERS=("$@")
if [ ${#CLUSTERS[@]} -eq 0 ]; then
  CLUSTERS=(tcc-a tcc-b)
fi

docker compose -f "$DIR/docker-compose.yaml" down --remove-orphans 2>/dev/null || true
for name in "${CLUSTERS[@]}"; do
  CLUSTER="$name" docker compose -p "ksm-$name" -f "$DIR/docker-compose.ksm.yaml" down 2>/dev/null || true
  kwokctl delete cluster --name "$name" 2>/dev/null || true
done
rm -rf "$DIR/.generated"
echo "done"
```

### `tcc-repo/infra/kwok/docker-compose.ksm.yaml`

```yaml
services:
  kube-state-metrics:
    image: registry.k8s.io/kube-state-metrics/kube-state-metrics:v2.13.0
    container_name: ksm-${CLUSTER}
    network_mode: host
    volumes:
      - ./.generated/${CLUSTER}/kubeconfig:/kubeconfig:ro
    command:
      - --kubeconfig=/kubeconfig
      - --port=${KSM_PORT:-8080}
      - --telemetry-port=${KSM_TELEMETRY_PORT:-8081}
```

### `tcc-repo/infra/kwok/docker-compose.yaml`

```yaml
services:
  prometheus:
    image: prom/prometheus:v2.55.1
    container_name: tcc-prometheus
    network_mode: host
    volumes:
      - ./config/prometheus.yaml:/etc/prometheus/prometheus.yml:ro
      - ./.generated/targets:/etc/prometheus/targets:ro
```

### `tcc-repo/infra/kwok/examples/test-pod.yaml`

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: test-pod
  annotations:
    kwok.x-k8s.io/usage-cpu: "250m"
    kwok.x-k8s.io/usage-memory: "128Mi"
spec:
  containers:
    - name: app
      image: nginx
      resources:
        requests:
          cpu: "1"
          memory: 512Mi

```

### `tcc-repo/infra/kwok/examples/unschedulable-pod.yaml`

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: unschedulable-pod
spec:
  containers:
    - name: app
      image: nginx
      resources:
        requests:
          cpu: "1000"

```

### `tcc-repo/infra/kwok/examples/workload.yaml`

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: well-sized
  annotations:
    kwok.x-k8s.io/usage-cpu: "400m"
    kwok.x-k8s.io/usage-memory: "200Mi"
spec:
  containers:
    - name: app
      image: nginx
      resources:
        requests: { cpu: "500m", memory: 256Mi }
---
apiVersion: v1
kind: Pod
metadata:
  name: over-provisioned
  annotations:
    kwok.x-k8s.io/usage-cpu: "100m"
    kwok.x-k8s.io/usage-memory: "128Mi"
spec:
  containers:
    - name: app
      image: nginx
      resources:
        requests: { cpu: "2", memory: 2Gi }
---
apiVersion: v1
kind: Pod
metadata:
  name: under-provisioned
  annotations:
    kwok.x-k8s.io/usage-cpu: "800m"
    kwok.x-k8s.io/usage-memory: "512Mi"
spec:
  containers:
    - name: app
      image: nginx
      resources:
        requests: { cpu: "200m", memory: 128Mi }

```

### `tcc-repo/main.py`

```python
# broker/src/main.py
from broker.src.adapters.synthetic_adapter import SyntheticAdapter


def main():
    adapter = SyntheticAdapter()
    
    print("--- MÁQUINAS ---")
    for machine in adapter.get_machines():
        print(machine)
        
    print("\n--- WORKLOADS ---")
    for workload in adapter.get_workloads():
        print(workload)
        
    print("\n--- USO ---")
    for usage in adapter.get_usage_samples():
        print(usage)

if __name__ == "__main__":
    main()
```

### `tcc-repo/README.md`

```markdown
# tcc
TCC

```

### `tcc-repo/repo.md`

```markdown

```

### `tcc-repo/scripts/check_event_codes.py`

```python
import os
import sys
from collections import defaultdict

import pandas as pd

if len(sys.argv) != 2:
    sys.exit("usage: python scripts/check_event_codes.py PATH_TO_FILE")

COLS = ["instance_events_type", "event", "time", "start_time", "end_time"]
stats = defaultdict(lambda: {"n": 0, "zero": 0, "before": 0, "after": 0, "label": ""})

for chunk in pd.read_csv(sys.argv[1], usecols=COLS, chunksize=500_000):
    for code, g in chunk.groupby("instance_events_type"):
        s = stats[code]
        s["n"] += len(g)
        s["zero"] += int((g["time"] == 0).sum())
        s["before"] += int((g["time"] <= g["start_time"]).sum())
        s["after"] += int((g["time"] >= g["end_time"]).sum())
        s["label"] = str(g["event"].iloc[0])

lines = [f"{'code':>4}  {'file label':<16}{'rows':>8}  {'time=0':>7}  {'<=usage start':>13}  {'>=usage end':>11}"]
for code in sorted(stats):
    s = stats[code]
    pct = lambda x: f"{100 * x / s['n']:.1f}%"
    lines.append(f"{code:>4}  {s['label']:<16}{s['n']:>8}  {pct(s['zero']):>7}  {pct(s['before']):>13}  {pct(s['after']):>11}")

text = "\n".join(lines)
os.makedirs("data/processed", exist_ok=True)
with open("data/processed/event_codes.txt", "w") as out:
    out.write(text)
print(text)

```

### `tcc-repo/scripts/inspect_borg.py`

```python
import os
import sys
from collections import Counter

import pandas as pd

if len(sys.argv) != 2:
    sys.exit("usage: python scripts/inspect_borg.py PATH_TO_FILE")

path = sys.argv[1]

with open(path, encoding="utf-8") as file:
    header_line = file.readline()
sep = max(["\t", ",", ";"], key=header_line.count)
header = [name.strip().strip('"') for name in header_line.rstrip("\r\n").split(sep)]
print(f"separator: {sep!r}, {len(header)} columns", file=sys.stderr)

COLS = ["instance_events_type", "event", "collection_type", "cluster", "collection_id", "instance_index"]
missing = [c for c in COLS if c not in header]
if missing:
    print("missing columns:", missing)
    print("columns found:", header)
    sys.exit(1)

rows = 0
codes, clusters, ctypes, per_instance = Counter(), Counter(), Counter(), Counter()

for number, chunk in enumerate(pd.read_csv(path, sep=sep, usecols=COLS, chunksize=500_000), start=1):
    rows += len(chunk)
    codes.update(zip(chunk["instance_events_type"], chunk["event"]))
    clusters.update(chunk["cluster"])
    ctypes.update(chunk["collection_type"])
    sample = chunk[chunk["collection_id"] % 100 == 0]  # 1% of collections
    per_instance.update(zip(sample["cluster"], sample["collection_id"], sample["instance_index"]))
    if number % 10 == 0:
        print(f"{rows} rows read...", file=sys.stderr)

sizes = pd.Series(list(per_instance.values()))
lines = [f"rows: {rows}", "", "code -> event"]
lines += [f"  {c} -> {e}: {n}" for (c, e), n in sorted(codes.items(), key=lambda kv: str(kv[0]))]
lines += ["", "rows per cluster"] + [f"  {k}: {v}" for k, v in sorted(clusters.items())]
lines += ["", "rows per collection_type"] + [f"  {k}: {v}" for k, v in sorted(ctypes.items())]
lines += ["", "rows per instance (1% sample of collections)", sizes.describe().to_string()]

text = "\n".join(lines)
os.makedirs("data/processed", exist_ok=True)
with open("data/processed/borg_summary.txt", "w") as out:
    out.write(text)
print(text)

```