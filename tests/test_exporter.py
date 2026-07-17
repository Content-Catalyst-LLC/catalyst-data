from pathlib import Path
import csv
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

from catalyst_data.engine import build_record
from catalyst_data.exporter import export_repository
from catalyst_data.repository import CatalystRepository


def test_repository_exports_json_and_csv(tmp_path):
    repository = CatalystRepository(tmp_path / "data.db")
    repository.initialize()
    payload = json.loads((ROOT / "examples/sample_project.json").read_text(encoding="utf-8"))
    repository.upsert_record(build_record(payload))
    json_path = tmp_path / "records.json"
    csv_path = tmp_path / "records.csv"
    assert export_repository(repository, json_path, format_name="json") == 1
    assert export_repository(repository, csv_path, format_name="csv") == 1
    assert json.loads(json_path.read_text(encoding="utf-8"))["record_count"] == 1
    with csv_path.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["entity_name"] == "Urban Tree Canopy Program"
