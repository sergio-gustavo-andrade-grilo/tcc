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