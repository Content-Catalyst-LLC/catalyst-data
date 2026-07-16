#!/usr/bin/env python3
"""Generate runtime contract artifacts from the canonical review contract."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "contracts" / "review_contract.json"
VERSION_PATH = ROOT / "VERSION"


def load_contract() -> dict:
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    required = {
        "contract",
        "confidence",
        "directions",
        "review_statuses",
        "signal_statuses",
        "missing_source_names",
        "trace_path",
    }
    missing = sorted(required - set(contract))
    if missing:
        raise ValueError(f"Review contract is missing fields: {', '.join(missing)}")
    confidence = contract["confidence"]
    if not (
        confidence["minimum"]
        <= confidence["needs_evidence_below"]
        < confidence["caution_below"]
        <= confidence["maximum"]
    ):
        raise ValueError("Confidence thresholds are not ordered")
    return contract


def version() -> str:
    value = VERSION_PATH.read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+", value):
        raise ValueError(f"Invalid VERSION value: {value!r}")
    return value


def python_contract(contract: dict) -> str:
    c = contract["confidence"]
    return f'''"""Generated from contracts/review_contract.json. Do not edit by hand."""

CONTRACT_ID = {contract["contract"]!r}
CONFIDENCE_MINIMUM = {c["minimum"]!r}
CONFIDENCE_MAXIMUM = {c["maximum"]!r}
NEEDS_EVIDENCE_BELOW = {c["needs_evidence_below"]!r}
CAUTION_BELOW = {c["caution_below"]!r}
DIRECTIONS = {tuple(contract["directions"])!r}
REVIEW_STATUSES = {tuple(contract["review_statuses"])!r}
SIGNAL_STATUSES = {tuple(contract["signal_statuses"])!r}
MISSING_SOURCE_NAMES = {tuple(contract["missing_source_names"])!r}
TRACE_PATH = {tuple(contract["trace_path"])!r}
'''


def javascript_contract(contract: dict) -> str:
    payload = json.dumps(contract, separators=(",", ":"), ensure_ascii=False)
    return (
        "/* Generated from contracts/review_contract.json. Do not edit by hand. */\n"
        "(function(root){\n"
        f"  root.CatalystDataReviewContract = Object.freeze({payload});\n"
        "})(typeof globalThis !== 'undefined' ? globalThis : this);\n"
    )


def generated_sql(contract: dict) -> str:
    c = contract["confidence"]
    return f'''-- BEGIN GENERATED REVIEW CONTRACT
DROP VIEW IF EXISTS low_confidence_measurements;
DROP VIEW IF EXISTS provenance_gaps;
DROP VIEW IF EXISTS measurement_review;

CREATE VIEW measurement_review AS
SELECT
    m.id AS measurement_id,
    e.name AS entity,
    e.entity_type,
    i.name AS indicator,
    i.framework,
    i.unit,
    i.direction,
    p.label AS period,
    m.baseline_value,
    m.value,
    CASE
        WHEN m.baseline_value IS NULL OR m.baseline_value = 0 THEN NULL
        ELSE ROUND(((m.value - m.baseline_value) / ABS(m.baseline_value)) * 100.0, 2)
    END AS percent_change,
    s.name AS source,
    s.source_type,
    m.confidence,
    CASE
        WHEN m.source_id IS NULL THEN 'missing source'
        WHEN m.confidence < {c["needs_evidence_below"]} THEN 'needs evidence'
        WHEN m.confidence < {c["caution_below"]} THEN 'reviewable with caution'
        ELSE 'reviewable'
    END AS review_status,
    CASE
        WHEN m.baseline_value IS NULL OR m.baseline_value = 0 THEN 'indeterminate'
        WHEN m.value = m.baseline_value THEN 'unchanged'
        WHEN i.direction = 'neutral' THEN 'descriptive'
        WHEN i.direction = 'higher' AND m.value > m.baseline_value THEN 'improving'
        WHEN i.direction = 'lower' AND m.value < m.baseline_value THEN 'improving'
        ELSE 'declining'
    END AS signal_status,
    m.method,
    m.assumptions
FROM measurements m
JOIN entities e ON e.id = m.entity_id
JOIN indicators i ON i.id = m.indicator_id
JOIN periods p ON p.id = m.period_id
LEFT JOIN sources s ON s.id = m.source_id;

CREATE VIEW provenance_gaps AS
SELECT * FROM measurement_review
WHERE source IS NULL
   OR confidence < {c["needs_evidence_below"]}
   OR method IS NULL
   OR LENGTH(TRIM(COALESCE(method, ''))) = 0;

CREATE VIEW low_confidence_measurements AS
SELECT * FROM measurement_review
WHERE confidence < {c["caution_below"]};
-- END GENERATED REVIEW CONTRACT'''


def replace_sql_region(current: str, generated: str) -> str:
    pattern = re.compile(
        r"-- BEGIN GENERATED REVIEW CONTRACT.*?-- END GENERATED REVIEW CONTRACT",
        re.DOTALL,
    )
    if pattern.search(current):
        return pattern.sub(generated, current)
    legacy_start = current.find("CREATE VIEW IF NOT EXISTS measurement_review AS")
    if legacy_start < 0:
        return current.rstrip() + "\n\n" + generated + "\n"
    return current[:legacy_start].rstrip() + "\n\n" + generated + "\n"


def outputs(contract: dict) -> dict[Path, str]:
    schema_path = ROOT / "schema.sql"
    schema = replace_sql_region(schema_path.read_text(encoding="utf-8"), generated_sql(contract))
    return {
        ROOT / "python" / "catalyst_data" / "_contract.py": python_contract(contract),
        ROOT / "python" / "catalyst_data" / "_version.py": (
            '"""Generated from VERSION. Do not edit by hand."""\n\n'
            f"__version__ = {version()!r}\n"
        ),
        ROOT / "wordpress" / "catalyst-data-demo" / "assets" / "catalyst-data-contract.js": javascript_contract(contract),
        schema_path: schema,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="fail if generated files are stale")
    args = parser.parse_args()
    contract = load_contract()
    stale: list[str] = []
    for path, content in outputs(contract).items():
        if path.exists() and path.read_text(encoding="utf-8") == content:
            continue
        if args.check:
            stale.append(str(path.relative_to(ROOT)))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            print(f"wrote {path.relative_to(ROOT)}")
    if stale:
        print("Generated contract artifacts are stale:")
        for item in stale:
            print(f"- {item}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
