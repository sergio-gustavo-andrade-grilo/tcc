import json

from agent_environment.core.report_log import ReportRecord, append_record


def test_append_record_writes_one_json_line_per_report(tmp_path):
    path = tmp_path / "sub" / "reports.jsonl"
    record = ReportRecord("2026-11-05 03:41:12 UTC", "tcc-a", 3, 6, "m", 1.5, 10, 20, "relatório")
    append_record(path, record)
    append_record(path, record)
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["report"] == "relatório"