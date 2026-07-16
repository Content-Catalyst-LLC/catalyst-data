from pathlib import Path
import json
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

from catalyst_data.engine import (
    build_record,
    classify_record,
    classify_review,
    classify_signal,
    percent_change,
)


def test_percent_change():
    assert percent_change(100, 125) == 25.0
    assert percent_change(100, 80) == -20.0
    assert percent_change(-100, -80) == 20.0
    assert percent_change(0, 50) is None


def test_review_classification_is_evidence_readiness_only():
    assert classify_review(72, "Named source") == "reviewable"
    assert classify_review(68, "Named source") == "reviewable with caution"
    assert classify_review(30, "Named source") == "needs evidence"
    assert classify_review(90, "") == "missing source"
    assert classify_record(72, 12, "higher") == "reviewable"


def test_signal_classification_is_separate():
    assert classify_signal(12, "higher") == "improving"
    assert classify_signal(-12, "higher") == "declining"
    assert classify_signal(-12, "lower") == "improving"
    assert classify_signal(0, "lower") == "unchanged"
    assert classify_signal(12, "neutral") == "descriptive"
    assert classify_signal(None, "higher") == "indeterminate"


def test_build_record_from_sample():
    payload = json.loads((ROOT / "examples" / "sample_project.json").read_text())
    record = build_record(payload)
    assert record["entity"]["name"] == "Urban Tree Canopy Program"
    assert record["values"]["percent_change"] == 25.81
    assert record["review_status"] == "reviewable"
    assert record["signal_status"] == "improving"
    assert "source" in record["trace_path"]


def test_build_record_zero_baseline_and_missing_source():
    payload = json.loads((ROOT / "examples" / "sample_project.json").read_text())
    payload["values"]["baseline"] = 0
    payload["source"]["name"] = ""
    payload["confidence"] = 95
    record = build_record(payload)
    assert record["values"]["percent_change"] is None
    assert record["review_status"] == "missing source"
    assert record["signal_status"] == "indeterminate"


@pytest.mark.parametrize("confidence", [-1, 101, float("inf")])
def test_invalid_confidence_is_rejected(confidence):
    payload = json.loads((ROOT / "examples" / "sample_project.json").read_text())
    payload["confidence"] = confidence
    with pytest.raises(ValueError, match="confidence"):
        build_record(payload)


def test_invalid_direction_is_rejected():
    payload = json.loads((ROOT / "examples" / "sample_project.json").read_text())
    payload["indicator"]["direction"] = "sideways"
    with pytest.raises(ValueError, match="direction"):
        build_record(payload)
