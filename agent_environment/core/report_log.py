import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class ReportRecord:
    timestamp: str
    cluster: str
    containers: int
    findings: int
    model: str | None
    latency_seconds: float | None
    prompt_tokens: int | None
    completion_tokens: int | None
    report: str


def append_record(path: str | Path, record: ReportRecord) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")