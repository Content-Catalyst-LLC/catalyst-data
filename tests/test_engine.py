from pathlib import Path
import json, sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
from catalyst_data.engine import build_record, classify_record, percent_change

def test_percent_change():
    assert percent_change(100, 125) == 25.0
    assert percent_change(100, 80) == -20.0
    assert percent_change(0, 50) == 0.0

def test_classify_record():
    assert classify_record(72, 12, "higher") == "strong signal"
    assert classify_record(68, 12, "higher") == "reviewable with caution"
    assert classify_record(30, 12, "higher") == "needs evidence"

def test_build_record_from_sample():
    payload = json.loads((ROOT / "examples" / "sample_project.json").read_text())
    record = build_record(payload)
    assert record["entity"]["name"] == "Urban Tree Canopy Program"
    assert record["values"]["percent_change"] == 25.81
    assert "source" in record["trace_path"]
