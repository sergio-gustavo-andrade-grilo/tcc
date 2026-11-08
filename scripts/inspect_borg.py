import os
import sys
from collections import Counter

import pandas as pd

if len(sys.argv) != 2:
    sys.exit("usage: python scripts/inspect_borg.py PATH_TO_FILE")

path = sys.argv[1]

with open(path, encoding="utf-8") as file:
    header_line = file.readline()
sep = max(["\t", ",", ";"], key=header_line.count)
header = [name.strip().strip('"') for name in header_line.rstrip("\r\n").split(sep)]
print(f"separator: {sep!r}, {len(header)} columns", file=sys.stderr)

COLS = ["instance_events_type", "event", "collection_type", "cluster", "collection_id", "instance_index"]
missing = [c for c in COLS if c not in header]
if missing:
    print("missing columns:", missing)
    print("columns found:", header)
    sys.exit(1)

rows = 0
codes, clusters, ctypes, per_instance = Counter(), Counter(), Counter(), Counter()

for number, chunk in enumerate(pd.read_csv(path, sep=sep, usecols=COLS, chunksize=500_000), start=1):
    rows += len(chunk)
    codes.update(zip(chunk["instance_events_type"], chunk["event"]))
    clusters.update(chunk["cluster"])
    ctypes.update(chunk["collection_type"])
    sample = chunk[chunk["collection_id"] % 100 == 0]  # 1% of collections
    per_instance.update(zip(sample["cluster"], sample["collection_id"], sample["instance_index"]))
    if number % 10 == 0:
        print(f"{rows} rows read...", file=sys.stderr)

sizes = pd.Series(list(per_instance.values()))
lines = [f"rows: {rows}", "", "code -> event"]
lines += [f"  {c} -> {e}: {n}" for (c, e), n in sorted(codes.items(), key=lambda kv: str(kv[0]))]
lines += ["", "rows per cluster"] + [f"  {k}: {v}" for k, v in sorted(clusters.items())]
lines += ["", "rows per collection_type"] + [f"  {k}: {v}" for k, v in sorted(ctypes.items())]
lines += ["", "rows per instance (1% sample of collections)", sizes.describe().to_string()]

text = "\n".join(lines)
os.makedirs("data/processed", exist_ok=True)
with open("data/processed/borg_summary.txt", "w") as out:
    out.write(text)
print(text)
