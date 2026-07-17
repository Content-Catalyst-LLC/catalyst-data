#!/usr/bin/env python3
"""Generate Catalyst Data record schema and runtime constants."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECORD_CONTRACT = ROOT / "contracts" / "record_contract.json"
REVIEW_CONTRACT = ROOT / "contracts" / "review_contract.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def nullable(type_name: str) -> dict:
    return {"type": [type_name, "null"]}


def schema(record: dict, review: dict) -> dict:
    id_pattern = record["id_pattern"]
    extension_pattern = record["extension_key_pattern"]
    checksum_pattern = record["source_checksum_pattern"]
    string_or_null = {"type": ["string", "null"]}
    date_or_null = {"type": ["string", "null"], "format": "date"}
    uri_or_null = {"type": ["string", "null"], "format": "uri"}
    datetime_or_null = {"type": ["string", "null"], "format": "date-time"}

    result = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://sustainablecatalyst.com/schemas/catalyst-data-record-1.0.json",
        "title": "Catalyst Data Record 1.0",
        "description": "Canonical Catalyst Data v1.1.0 measurement record with provenance, review, method, and extension metadata.",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "$schema", "schema_version", "record_id", "record_type", "created_at", "updated_at",
            "producer", "entity", "indicator", "period", "measurement", "source", "confidence",
            "review", "method", "extensions"
        ],
        "properties": {
            "$schema": {"const": "https://sustainablecatalyst.com/schemas/catalyst-data-record-1.0.json"},
            "schema_version": {"const": record["contract"]},
            "record_id": {"type": "string", "pattern": id_pattern},
            "record_type": {"enum": record["record_types"]},
            "created_at": {"type": "string", "format": "date-time"},
            "updated_at": {"type": "string", "format": "date-time"},
            "producer": {
                "type": "object", "additionalProperties": False,
                "required": ["name", "version", "component"],
                "properties": {
                    "name": {"type": "string", "minLength": 1},
                    "version": {"type": "string", "pattern": r"^\d+\.\d+\.\d+$"},
                    "component": {"enum": record["producer_components"]}
                }
            },
            "entity": {
                "type": "object", "additionalProperties": False,
                "required": ["id", "name", "type", "external_ids"],
                "properties": {
                    "id": {"type": "string", "pattern": id_pattern},
                    "name": {"type": "string", "minLength": 1},
                    "type": {"enum": record["entity_types"]},
                    "external_ids": {
                        "type": "object", "propertyNames": {"pattern": extension_pattern},
                        "additionalProperties": {"type": "string", "minLength": 1}
                    }
                }
            },
            "indicator": {
                "type": "object", "additionalProperties": False,
                "required": ["id", "name", "unit", "direction", "framework", "version"],
                "properties": {
                    "id": {"type": "string", "pattern": id_pattern},
                    "name": {"type": "string", "minLength": 1},
                    "unit": {"type": "string", "minLength": 1},
                    "direction": {"enum": review["directions"]},
                    "framework": string_or_null,
                    "version": {"type": "string", "minLength": 1}
                }
            },
            "period": {
                "type": "object", "additionalProperties": False,
                "required": ["id", "label", "start_date", "end_date"],
                "properties": {
                    "id": {"type": "string", "pattern": id_pattern},
                    "label": {"type": "string", "minLength": 1},
                    "start_date": date_or_null,
                    "end_date": date_or_null
                }
            },
            "measurement": {
                "type": "object", "additionalProperties": False,
                "required": ["baseline", "current", "percent_change"],
                "properties": {
                    "baseline": {"type": ["number", "null"]},
                    "current": {"type": "number"},
                    "percent_change": {"type": ["number", "null"]}
                }
            },
            "source": {
                "type": "object", "additionalProperties": False,
                "required": ["id", "name", "type", "url", "publisher", "license", "retrieved_at", "citation", "checksum", "access_notes"],
                "properties": {
                    "id": {"type": "string", "pattern": id_pattern},
                    "name": {"type": "string", "minLength": 1},
                    "type": {"enum": record["source_types"]},
                    "url": uri_or_null,
                    "publisher": string_or_null,
                    "license": string_or_null,
                    "retrieved_at": datetime_or_null,
                    "citation": string_or_null,
                    "checksum": {"type": ["string", "null"], "pattern": checksum_pattern},
                    "access_notes": string_or_null
                }
            },
            "confidence": {
                "type": "object", "additionalProperties": False,
                "required": ["score", "scale", "basis"],
                "properties": {
                    "score": {"type": "number", "minimum": review["confidence"]["minimum"], "maximum": review["confidence"]["maximum"]},
                    "scale": {"const": "0-100"},
                    "basis": string_or_null
                }
            },
            "review": {
                "type": "object", "additionalProperties": False,
                "required": ["status", "signal_status", "reviewer_notes"],
                "properties": {
                    "status": {"enum": review["review_statuses"]},
                    "signal_status": {"enum": review["signal_statuses"]},
                    "reviewer_notes": {"type": "string"}
                }
            },
            "method": {
                "type": "object", "additionalProperties": False,
                "required": ["notes", "assumptions", "limitations", "uncertainty", "quality_flags"],
                "properties": {
                    "notes": {"type": "string"},
                    "assumptions": {"type": "array", "items": {"type": "string", "minLength": 1}, "uniqueItems": True},
                    "limitations": {"type": "array", "items": {"type": "string", "minLength": 1}, "uniqueItems": True},
                    "uncertainty": string_or_null,
                    "quality_flags": {"type": "array", "items": {"enum": record["quality_flags"]}, "uniqueItems": True}
                }
            },
            "extensions": {
                "type": "object",
                "propertyNames": {"pattern": extension_pattern},
                "additionalProperties": True
            }
        }
    }
    return result


def python_constants(record: dict) -> str:
    return f'''"""Generated from contracts/record_contract.json. Do not edit by hand."""

RECORD_CONTRACT = {record["contract"]!r}
RECORD_SCHEMA_URI = 'https://sustainablecatalyst.com/schemas/catalyst-data-record-1.0.json'
RECORD_TYPES = {tuple(record["record_types"])!r}
ENTITY_TYPES = {tuple(record["entity_types"])!r}
SOURCE_TYPES = {tuple(record["source_types"])!r}
PRODUCER_COMPONENTS = {tuple(record["producer_components"])!r}
QUALITY_FLAGS = {tuple(record["quality_flags"])!r}
ID_PATTERN = {record["id_pattern"]!r}
EXTENSION_KEY_PATTERN = {record["extension_key_pattern"]!r}
SOURCE_CHECKSUM_PATTERN = {record["source_checksum_pattern"]!r}
LEGACY_CONTRACTS = {tuple(record["legacy_contracts"])!r}
'''


def javascript_constants(record: dict, review: dict) -> str:
    payload = {
        "contract": record["contract"],
        "release_version": (ROOT / "VERSION").read_text(encoding="utf-8").strip(),
        "schema_uri": "https://sustainablecatalyst.com/schemas/catalyst-data-record-1.0.json",
        "record_types": record["record_types"],
        "entity_types": record["entity_types"],
        "source_types": record["source_types"],
        "producer_components": record["producer_components"],
        "quality_flags": record["quality_flags"],
        "id_pattern": record["id_pattern"],
        "extension_key_pattern": record["extension_key_pattern"],
        "review_statuses": review["review_statuses"],
        "signal_statuses": review["signal_statuses"]
    }
    compact = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    return (
        "/* Generated from contracts/record_contract.json. Do not edit by hand. */\n"
        "(function(root){\n"
        f"  root.CatalystDataRecordContract = Object.freeze({compact});\n"
        "})(typeof globalThis !== 'undefined' ? globalThis : this);\n"
    )


def export_alias(canonical: dict) -> dict:
    alias = json.loads(json.dumps(canonical))
    alias["$id"] = "https://sustainablecatalyst.com/schemas/catalyst-data-export-1.1.0.json"
    alias["title"] = "Catalyst Data Export 1.1.0"
    alias["description"] = "Compatibility export schema for the canonical catalyst-data-record/1.0 contract."
    alias["properties"]["$schema"]["const"] = "https://sustainablecatalyst.com/schemas/catalyst-data-record-1.0.json"
    return alias


def rendered_outputs() -> dict[Path, str]:
    record = load(RECORD_CONTRACT)
    review = load(REVIEW_CONTRACT)
    canonical = schema(record, review)
    canonical_text = json.dumps(canonical, indent=2, ensure_ascii=False) + "\n"
    return {
        ROOT / "schemas" / "catalyst_data_record_1_0.schema.json": canonical_text,
        ROOT / "schemas" / "catalyst_data_export.schema.json": json.dumps(export_alias(canonical), indent=2, ensure_ascii=False) + "\n",
        ROOT / "python" / "catalyst_data" / "schemas" / "catalyst_data_record_1_0.schema.json": canonical_text,
        ROOT / "python" / "catalyst_data" / "_record_contract.py": python_constants(record),
        ROOT / "wordpress" / "catalyst-data-demo" / "assets" / "catalyst-data-record-contract.js": javascript_constants(record, review),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    stale: list[str] = []
    for path, content in rendered_outputs().items():
        if path.exists() and path.read_text(encoding="utf-8") == content:
            continue
        if args.check:
            stale.append(str(path.relative_to(ROOT)))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            print(f"wrote {path.relative_to(ROOT)}")
    if stale:
        print("Generated record contract artifacts are stale:")
        for item in stale:
            print(f"- {item}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
