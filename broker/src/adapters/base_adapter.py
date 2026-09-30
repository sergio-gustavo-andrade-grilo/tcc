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
