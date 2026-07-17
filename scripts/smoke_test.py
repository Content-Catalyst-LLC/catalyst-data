#!/usr/bin/env python3
"""Portable release smoke tests for installer environments."""
from __future__ import annotations

import json
import sqlite3
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

from catalyst_data import (
    RecordValidationError,
    build_record,
    classify_review,
    classify_signal,
    convert_legacy_record,
    percent_change,
    validate_record,
)


def check(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> int:
    check(percent_change(100, 125) == 25.0, "positive percent change failed")
    check(percent_change(0, 50) is None, "zero baseline must be indeterminate")
    check(percent_change(None, 50) is None, "missing baseline must be indeterminate")
    check(classify_review(90, "") == "missing source", "missing source precedence failed")
    check(classify_review(68, "Source") == "reviewable with caution", "caution threshold failed")
    check(classify_signal(-10, "lower") == "improving", "lower-is-better signal failed")

    payload = json.loads((ROOT / "examples/sample_project.json").read_text(encoding="utf-8"))
    record = build_record(payload)
    validate_record(record)
    check(record["schema_version"] == "catalyst-data-record/1.0", "record contract failed")
    check(record["producer"]["version"] == "1.1.0", "producer version failed")
    check(record["review"]["status"] == "reviewable", "sample review status failed")
    check(record["review"]["signal_status"] == "improving", "sample signal status failed")
    check(record["source"]["publisher"] == "Content Catalyst LLC", "source provenance failed")

    invalid = deepcopy(record)
    invalid["unexpected"] = True
    try:
        validate_record(invalid)
    except RecordValidationError:
        pass
    else:
        raise RuntimeError("unknown canonical fields must be rejected")

    legacy = json.loads((ROOT / "examples/sample_legacy_v1_0_record.json").read_text(encoding="utf-8"))
    upgraded = convert_legacy_record(
        legacy,
        now=datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc),
    )
    validate_record(upgraded)
    check(upgraded["producer"]["component"] == "migration-tool", "legacy producer failed")
    check(upgraded["measurement"]["percent_change"] == 25.0, "legacy derived value failed")

    database = sqlite3.connect(":memory:")
    database.executescript((ROOT / "schema.sql").read_text(encoding="utf-8"))
    database.executescript((ROOT / "queries.sql").read_text(encoding="utf-8"))
    count = database.execute("SELECT COUNT(*) FROM measurement_review").fetchone()[0]
    check(count == 2, f"expected 2 seeded measurements, found {count}")
    database.close()
    print("Portable release smoke tests passed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
