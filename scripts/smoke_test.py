#!/usr/bin/env python3
"""Standard-library release smoke tests for installer environments."""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

from catalyst_data.engine import build_record, classify_review, classify_signal, percent_change


def check(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> int:
    check(percent_change(100, 125) == 25.0, "positive percent change failed")
    check(percent_change(0, 50) is None, "zero baseline must be indeterminate")
    check(classify_review(90, "") == "missing source", "missing source precedence failed")
    check(classify_review(68, "Source") == "reviewable with caution", "caution threshold failed")
    check(classify_signal(-10, "lower") == "improving", "lower-is-better signal failed")

    payload = json.loads((ROOT / "examples/sample_project.json").read_text(encoding="utf-8"))
    record = build_record(payload)
    check(record["review_status"] == "reviewable", "sample review status failed")
    check(record["signal_status"] == "improving", "sample signal status failed")

    database = sqlite3.connect(":memory:")
    database.executescript((ROOT / "schema.sql").read_text(encoding="utf-8"))
    database.executescript((ROOT / "queries.sql").read_text(encoding="utf-8"))
    count = database.execute("SELECT COUNT(*) FROM measurement_review").fetchone()[0]
    check(count == 2, f"expected 2 seeded measurements, found {count}")
    database.close()
    print("Standard-library release smoke tests passed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
