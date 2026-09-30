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
