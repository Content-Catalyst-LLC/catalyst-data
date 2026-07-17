from pathlib import Path
import csv
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

from catalyst_data.importer import ImportPipelineError, ImportService
from catalyst_data.repository import CatalystRepository


def write_json(path: Path, records):
    path.write_text(json.dumps({"records": records}), encoding="utf-8")


def sample_payload():
    return json.loads((ROOT / "examples/sample_project.json").read_text(encoding="utf-8"))


def test_json_import_is_idempotent(tmp_path):
    source = tmp_path / "records.json"
    write_json(source, [sample_payload()])
    repository = CatalystRepository(tmp_path / "data.db")
    service = ImportService(repository)
    first = service.run(source)
    second = service.run(source)
    assert (first.inserted, first.failed) == (1, 0)
    assert (second.skipped, second.failed) == (1, 0)
    assert repository.stats()["records"] == 1


def test_dry_run_rolls_back_all_changes(tmp_path):
    source = tmp_path / "records.json"
    write_json(source, [sample_payload()])
    repository = CatalystRepository(tmp_path / "data.db")
    summary = ImportService(repository).run(source, dry_run=True)
    assert summary.inserted == 1
    assert summary.rolled_back
    assert repository.stats()["records"] == 0
    assert repository.stats()["import_runs"] == 0


def test_atomic_import_rolls_back_valid_rows_when_any_row_fails(tmp_path):
    source = tmp_path / "records.json"
    write_json(source, [sample_payload(), {"not": "a record"}])
    repository = CatalystRepository(tmp_path / "data.db")
    try:
        ImportService(repository).run(source, continue_on_error=True, atomic=True)
    except ImportPipelineError as exc:
        assert exc.summary.failed == 1
        assert exc.summary.rolled_back
    else:
        raise AssertionError("atomic import should fail")
    assert repository.stats()["records"] == 0
    assert repository.stats()["import_runs"] == 1


def test_non_atomic_csv_import_commits_valid_rows_and_reports_errors(tmp_path):
    source = tmp_path / "records.csv"
    fields = ["entity_name", "entity_type", "indicator_name", "unit", "direction", "period_label", "baseline", "current", "source_name", "source_type", "confidence", "method_notes", "created_at", "updated_at"]
    with source.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerow({
            "entity_name": "Program A", "entity_type": "program", "indicator_name": "Participation",
            "unit": "%", "direction": "higher", "period_label": "2026", "baseline": "20", "current": "40",
            "source_name": "Program register", "source_type": "internal record", "confidence": "75",
            "method_notes": "Counted registered participants.", "created_at": "2026-07-16T12:00:00Z",
            "updated_at": "2026-07-16T12:00:00Z",
        })
        writer.writerow({"entity_name": "Broken"})
    repository = CatalystRepository(tmp_path / "data.db")
    summary = ImportService(repository).run(source, atomic=False, continue_on_error=True)
    assert summary.inserted == 1
    assert summary.failed == 1
    assert not summary.rolled_back
    assert repository.stats()["records"] == 1
    assert repository.stats()["import_runs"] == 1
