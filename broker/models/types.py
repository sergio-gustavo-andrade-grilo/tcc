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
