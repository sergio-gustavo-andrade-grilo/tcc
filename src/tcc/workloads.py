"""Replays a slice of the Kaggle Borg 2019 sample on a KWOK cluster.

Pod lifetimes come from the usage windows (first start_time to last end_time);
requests and usage come from the CSV, un-normalized with an assumed reference machine.
"""
import argparse
import ast
import json
import subprocess
import time
from dataclasses import dataclass
from enum import Enum
from statistics import fmean

import pandas as pd

REF_CORES = 64               # assumed machine behind the normalized CPU values
REF_MEMORY_MI = 256 * 1024   # assumed machine behind the normalized memory values
US = 1_000_000
WINDOW_US = 300 * US         # usage windows are 5 minutes long

COLUMNS = [
    "cluster", "collection_id", "instance_index", "alloc_collection_id",
    "resource_request", "start_time", "end_time", "average_usage",
]


class Action(str, Enum):
    CREATE = "create"
    DELETE = "delete"


@dataclass(frozen=True)
class Event:
    at_seconds: float            # offset from replay start, in trace time
    cluster: str                 # target KWOK cluster name (not the Borg cell)
    action: Action
    name: str                    # pod name, built from collection_id and instance_index
    cpu_request_m: int = 0       # millicores
    memory_request_mi: int = 0   # MiB
    cpu_usage_m: int | None = None
    memory_usage_mi: int | None = None


def load_rows(path: str, borg_cell: int | None = None) -> tuple[pd.DataFrame, int]:
    """Reads the CSV in chunks, keeping one Borg cell and plain jobs (no alloc)."""
    parts = []
    for chunk in pd.read_csv(path, usecols=COLUMNS, chunksize=200_000):
        if borg_cell is None:
            borg_cell = chunk["cluster"].mode().iloc[0]
            print(f"using borg cell {borg_cell} (most common in the first chunk)")
        chunk = chunk[(chunk["cluster"] == borg_cell) & (chunk["alloc_collection_id"] == 0)]
        chunk = chunk.dropna(subset=["resource_request", "start_time", "end_time"])
        parts.append(chunk)
    return pd.concat(parts, ignore_index=True), borg_cell


def _parse(value) -> dict:
    # The CSV stores Python dict reprs as strings, e.g. "{'cpus': 0.02, 'memory': 0.01}"
    return ast.literal_eval(value) if isinstance(value, str) else {}


def _cpu_m(ncu: float) -> int:
    return max(1, round(ncu * REF_CORES * 1000))


def _mem_mi(norm: float) -> int:
    return max(1, round(norm * REF_MEMORY_MI))


def to_events(rows: pd.DataFrame, cluster: str, t0_us: int, t1_us: int,
              max_pods: int) -> list[Event]:
    """One pod per (collection_id, instance_index) with usage windows in [t0, t1]."""
    pods = []
    for (cid, idx), group in rows.groupby(["collection_id", "instance_index"], sort=False):
        first = group.loc[group["start_time"].idxmin()]
        request = _parse(first["resource_request"])
        usage = [_parse(v) for v in group["average_usage"]]
        pods.append({
            "name": f"c{int(cid)}-i{int(idx)}",
            "start": max(int(group["start_time"].min()), t0_us),
            "end": int(group["end_time"].max()),
            "cpu_req": _cpu_m(request.get("cpus") or 0),
            "mem_req": _mem_mi(request.get("memory") or 0),
            "cpu_use": _cpu_m(fmean(u.get("cpus") or 0 for u in usage)),
            "mem_use": _mem_mi(fmean(u.get("memory") or 0 for u in usage)),
        })
    pods.sort(key=lambda p: p["start"])

    events = []
    for p in pods[:max_pods]:
        events.append(Event((p["start"] - t0_us) / US, cluster, Action.CREATE, p["name"],
                            p["cpu_req"], p["mem_req"], p["cpu_use"], p["mem_use"]))
        # Only delete pods whose usage ended clearly before the end of the window.
        if p["end"] < t1_us - WINDOW_US:
            events.append(Event((p["end"] - t0_us) / US, cluster, Action.DELETE, p["name"]))
    return sorted(events, key=lambda e: e.at_seconds)


def pod_manifest(event: Event) -> dict:
    annotations = {}
    if event.cpu_usage_m is not None:
        annotations["kwok.x-k8s.io/usage-cpu"] = f"{event.cpu_usage_m}m"
    if event.memory_usage_mi is not None:
        annotations["kwok.x-k8s.io/usage-memory"] = f"{event.memory_usage_mi}Mi"
    return {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {"name": event.name, "namespace": "default", "annotations": annotations},
        "spec": {"containers": [{
            "name": "app",
            "image": "nginx",
            "resources": {"requests": {
                "cpu": f"{event.cpu_request_m}m",
                "memory": f"{event.memory_request_mi}Mi",
            }},
        }]},
    }


def _kubectl(cluster: str, args: list[str], stdin: str | None = None) -> None:
    command = ["kubectl", "--context", f"kwok-{cluster}", *args]
    result = subprocess.run(command, input=stdin, text=True, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"kubectl exited with {result.returncode}")


def replay(events: list[Event], speed: float, dry_run: bool) -> int:
    """Runs events at at_seconds / speed. Returns the number of failures."""
    start = time.monotonic()
    failures = 0
    for e in events:
        wait = start + e.at_seconds / speed - time.monotonic()
        if wait > 0 and not dry_run:
            time.sleep(wait)
        label = f"[t={e.at_seconds:>8.0f}s] {e.action.value:<6} {e.name}"
        if dry_run:
            print(label)
            continue
        try:
            if e.action is Action.CREATE:
                _kubectl(e.cluster, ["apply", "-f", "-"], json.dumps(pod_manifest(e)))
            else:
                _kubectl(e.cluster, ["delete", "pod", e.name, "--ignore-not-found", "--wait=false"])
            print(label)
        except RuntimeError as error:
            failures += 1
            print(f"{label} FAILED: {error}")
    return failures


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("csv", help="path to borg_traces_data.csv")
    p.add_argument("--cluster", default="tcc-a", help="KWOK cluster name")
    p.add_argument("--borg-cell", type=int, help="value of the 'cluster' column to use")
    p.add_argument("--t-start-hours", type=float, help="window start, in trace hours")
    p.add_argument("--minutes", type=float, default=60, help="window length in trace minutes")
    p.add_argument("--speed", type=float, default=60, help="60 = one trace hour per wall minute")
    p.add_argument("--max-pods", type=int, default=100)
    p.add_argument("--info", action="store_true", help="describe the data and exit")
    p.add_argument("--dry-run", action="store_true", help="print the schedule only")
    args = p.parse_args()

    rows, cell = load_rows(args.csv, args.borg_cell)
    hours = rows["start_time"] / US / 3600
    if args.info:
        print(f"cell {cell}: {len(rows)} rows, "
              f"{rows.groupby(['collection_id', 'instance_index']).ngroups} instances")
        print(hours.describe())
        print("usage windows per 6h bucket (bucket start in trace hours):")
        print((hours // 6 * 6).value_counts().sort_index().head(40))
        return

    t0 = int(args.t_start_hours * 3600 * US) if args.t_start_hours is not None \
        else int(rows["start_time"].min())
    t1 = t0 + int(args.minutes * 60 * US)
    window = rows[(rows["end_time"] >= t0) & (rows["start_time"] <= t1)]
    events = to_events(window, args.cluster, t0, t1, args.max_pods)
    if not events:
        raise SystemExit("no events in this window; pick another with --info")

    creates = sum(e.action is Action.CREATE for e in events)
    wall = events[-1].at_seconds / args.speed
    print(f"{creates} pods, {len(events) - creates} deletes, ~{wall:.0f}s of wall time")
    failures = replay(events, args.speed, args.dry_run)
    print(f"done, {failures} failed event(s)")


if __name__ == "__main__":
    main()