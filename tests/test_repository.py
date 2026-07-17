from copy import deepcopy
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

from catalyst_data.engine import build_record, percent_change, classify_signal
from catalyst_data.repository import CatalystRepository


def sample_record():
    payload = json.loads((ROOT / "examples/sample_project.json").read_text(encoding="utf-8"))
    return build_record(payload)


def test_repository_upsert_is_idempotent_and_updates_changed_payload(tmp_path):
    repository = CatalystRepository(tmp_path / "data.sqlite3")
    repository.initialize()
    record = sample_record()
    assert repository.upsert_record(record) == "inserted"
    assert repository.upsert_record(record) == "skipped"
    changed = deepcopy(record)
    changed["measurement"]["current"] = 80.0
    changed["measurement"]["percent_change"] = percent_change(changed["measurement"]["baseline"], 80.0)
    changed["review"]["signal_status"] = classify_signal(changed["measurement"]["percent_change"], changed["indicator"]["direction"])
    changed["updated_at"] = "2026-07-16T13:00:00Z"
    assert repository.upsert_record(changed) == "updated"
    stored = repository.get_record(record["record_id"])
    assert stored is not None
    assert stored["measurement"]["current"] == 80.0
    assert repository.stats()["records"] == 1
    assert len(repository.review_queue()) == 1
