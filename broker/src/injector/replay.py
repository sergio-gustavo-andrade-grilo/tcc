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