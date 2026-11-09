"""Downloads a sampled slice of the Borg 2019 trace from BigQuery into data/.

Default is a dry run (prints estimated bytes). Use --run to execute.
Requires: gcloud auth application-default login, and BQ_PROJECT in .env.
"""
import argparse
import os
from pathlib import Path

from dotenv import load_dotenv
from google.cloud import bigquery

ROOT = Path(__file__).resolve().parent.parent
QUERIES = ROOT / "queries"
OUT = ROOT / "data"
TABLES = ["instance_events", "instance_usage", "machine_events"]
TRACE_OFFSET_US = 600_000_000  # trace time 0 is 600 s before the window starts
HOUR_US = 3_600_000_000


def render(table: str, cell: str, modulus: int, hours: float) -> str:
    template = (QUERIES / f"{table}.sql").read_text()
    return template.format(
        cell=cell,
        modulus=modulus,
        t_start=TRACE_OFFSET_US,
        t_end=TRACE_OFFSET_US + int(hours * HOUR_US),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cell", default="a", choices=list("abcdefgh"))
    parser.add_argument("--modulus", type=int, default=100,
                        help="keep 1/N of the collections (hash-based)")
    parser.add_argument("--hours", type=float, default=24)
    parser.add_argument("--max-gb", type=float, default=50,
                        help="abort any query estimated above this many GB")
    parser.add_argument("--run", action="store_true",
                        help="execute and save; default only estimates")
    args = parser.parse_args()

    load_dotenv()
    project = os.environ.get("BQ_PROJECT")
    if not project:
        raise SystemExit("BQ_PROJECT is not set (put it in .env)")
    client = bigquery.Client(project=project)
    OUT.mkdir(exist_ok=True)

    for table in TABLES:
        sql = render(table, args.cell, args.modulus, args.hours)

        # A dry run validates the query and reports bytes without running it.
        dry = client.query(sql, job_config=bigquery.QueryJobConfig(
            dry_run=True, use_query_cache=False))
        gb = dry.total_bytes_processed / 1e9
        print(f"{table}: would process {gb:.2f} GB")
        if gb > args.max_gb:
            raise SystemExit(f"{table}: above --max-gb ({args.max_gb}), aborting")
        if not args.run:
            continue

        # maximum_bytes_billed makes BigQuery refuse the job if it would exceed this.
        config = bigquery.QueryJobConfig(
            maximum_bytes_billed=int(args.max_gb * 1e9))
        df = client.query(sql, job_config=config).to_dataframe()
        path = OUT / f"{table}_{args.cell}_1in{args.modulus}_{args.hours:g}h.parquet"
        df.to_parquet(path)
        print(f"{table}: {len(df)} rows -> {path}")


if __name__ == "__main__":
    main()