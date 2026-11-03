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
    pending_pods: int | None = None

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