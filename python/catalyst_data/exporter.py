from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from .repository import CatalystRepository


CSV_FIELDS = [
    "record_id", "schema_version", "entity_id", "entity_name", "entity_type",
    "indicator_id", "indicator_name", "unit", "direction", "framework", "indicator_version",
    "period_id", "period_label", "start_date", "end_date", "baseline", "current", "percent_change",
    "source_id", "source_name", "source_type", "source_url", "publisher", "license", "retrieved_at",
    "citation", "checksum", "confidence", "confidence_basis", "review_status", "signal_status",
    "method_notes", "assumptions", "limitations", "uncertainty", "quality_flags", "reviewer_notes",
    "evidence_source_count", "evidence_completeness_score", "evidence_gap_codes", "evidence_chain_json",
    "created_at", "updated_at",
]


def flatten_record(record: Mapping[str, Any]) -> dict[str, Any]:
    entity, indicator, period = record["entity"], record["indicator"], record["period"]
    measurement, source = record["measurement"], record["source"]
    confidence, review, method = record["confidence"], record["review"], record["method"]
    evidence = record.get("evidence_chain", {})
    return {
        "record_id": record["record_id"], "schema_version": record["schema_version"],
        "entity_id": entity["id"], "entity_name": entity["name"], "entity_type": entity["type"],
        "indicator_id": indicator["id"], "indicator_name": indicator["name"], "unit": indicator["unit"],
        "direction": indicator["direction"], "framework": indicator.get("framework"),
        "indicator_version": indicator["version"], "period_id": period["id"], "period_label": period["label"],
        "start_date": period.get("start_date"), "end_date": period.get("end_date"),
        "baseline": measurement.get("baseline"), "current": measurement["current"],
        "percent_change": measurement.get("percent_change"), "source_id": source["id"],
        "source_name": source["name"], "source_type": source["type"], "source_url": source.get("url"),
        "publisher": source.get("publisher"), "license": source.get("license"),
        "retrieved_at": source.get("retrieved_at"), "citation": source.get("citation"),
        "checksum": source.get("checksum"), "confidence": confidence["score"],
        "confidence_basis": confidence.get("basis"), "review_status": review["status"],
        "signal_status": review["signal_status"], "method_notes": method.get("notes"),
        "assumptions": " | ".join(method.get("assumptions", [])),
        "limitations": " | ".join(method.get("limitations", [])), "uncertainty": method.get("uncertainty"),
        "quality_flags": " | ".join(method.get("quality_flags", [])),
        "reviewer_notes": review.get("reviewer_notes"),
        "evidence_source_count": len(evidence.get("sources", [])),
        "evidence_completeness_score": evidence.get("completeness_score"),
        "evidence_gap_codes": " | ".join(item.get("code", "") for item in evidence.get("gaps", [])),
        "evidence_chain_json": json.dumps(evidence, ensure_ascii=False, sort_keys=True),
        "created_at": record["created_at"], "updated_at": record["updated_at"],
    }


def export_repository(repository: CatalystRepository, destination: str | Path, *, format_name: str = "json") -> int:
    path = Path(destination)
    records = repository.list_records(limit=1_000_000)
    path.parent.mkdir(parents=True, exist_ok=True)
    if format_name == "json":
        payload = {"schema_version": "catalyst-data-export/1.0", "record_count": len(records), "records": records}
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    elif format_name == "csv":
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
            writer.writeheader()
            for record in records:
                writer.writerow(flatten_record(record))
    else:
        raise ValueError("format must be json or csv")
    return len(records)
