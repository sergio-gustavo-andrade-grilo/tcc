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
