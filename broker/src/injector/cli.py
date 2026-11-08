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