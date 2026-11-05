import json

import pytest

from broker.src.injector.events import Action, Event, PodSpec, load_scenario
from broker.src.injector.replay import replay
from broker.src.injector.runner import pod_manifest


class FakeRunner:
    def __init__(self, fail_on: str | None = None) -> None:
        self.calls: list[tuple] = []
        self.fail_on = fail_on

    def apply(self, cluster, manifest):
        name = manifest["metadata"]["name"]
        if name == self.fail_on:
            raise RuntimeError("boom")
        self.calls.append(("apply", cluster, name))

    def delete(self, cluster, namespace, name):
        self.calls.append(("delete", cluster, name))


class FakeTime:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def create(at, name, cluster="tcc-a"):
    return Event(at, cluster, Action.CREATE, PodSpec(name, cpu_request_m=100, memory_request_mi=64))


def run(events, runner, speed=1.0):
    t = FakeTime()
    failures = replay(events, runner, speed, clock=t.clock, sleep=t.sleep, log=lambda _: None)
    return failures, t


def test_manifest_has_requests_and_usage():
    spec = PodSpec("p", cpu_request_m=500, memory_request_mi=256, cpu_usage_m=400, memory_usage_mi=200)
    manifest = pod_manifest(spec)
    assert manifest["metadata"]["annotations"] == {
        "kwok.x-k8s.io/usage-cpu": "400m",
        "kwok.x-k8s.io/usage-memory": "200Mi",
    }
    assert manifest["spec"]["containers"][0]["resources"]["requests"] == {
        "cpu": "500m",
        "memory": "256Mi",
    }


def test_manifest_without_usage_has_no_annotations():
    manifest = pod_manifest(PodSpec("p", cpu_request_m=100, memory_request_mi=64))
    assert not manifest["metadata"]["annotations"]


def test_replay_waits_for_scaled_time():
    failures, t = run([create(0, "a"), create(10, "b"), create(30, "c")], FakeRunner(), speed=2.0)
    assert failures == 0
    assert t.sleeps == [5.0, 10.0]


def test_replay_orders_events_by_time():
    runner = FakeRunner()
    run([create(10, "b"), create(0, "a")], runner)
    assert [c[2] for c in runner.calls] == ["a", "b"]


def test_replay_continues_after_a_failure():
    runner = FakeRunner(fail_on="a")
    failures, _ = run([create(0, "a"), create(1, "b")], runner)
    assert failures == 1
    assert runner.calls == [("apply", "tcc-a", "b")]


def test_delete_event_calls_delete():
    runner = FakeRunner()
    run([Event(0, "tcc-b", Action.DELETE, PodSpec("x"))], runner)
    assert runner.calls == [("delete", "tcc-b", "x")]


def test_load_scenario(tmp_path):
    path = tmp_path / "scenario.json"
    path.write_text(
        json.dumps(
            [
                {"at": 0, "cluster": "tcc-a", "action": "create", "pod": "x",
                 "cpu_request_m": 100, "memory_request_mi": 64, "cpu_usage_m": 50},
                {"at": 5, "cluster": "tcc-a", "action": "delete", "pod": "x"},
            ]
        )
    )
    events = load_scenario(path)
    assert [e.action for e in events] == [Action.CREATE, Action.DELETE]
    assert events[0].pod.cpu_usage_m == 50
    assert events[0].pod.memory_usage_mi is None


def test_load_scenario_rejects_unknown_action(tmp_path):
    path = tmp_path / "scenario.json"
    path.write_text(json.dumps([{"at": 0, "cluster": "c", "action": "explode", "pod": "x"}]))
    with pytest.raises(ValueError):
        load_scenario(path)