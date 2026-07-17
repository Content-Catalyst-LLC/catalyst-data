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
    "indicator_namespace", "indicator_code", "indicator_domain", "indicator_custodian", "indicator_status",
    "indicator_frequency", "indicator_aggregation", "unit_id", "unit_symbol", "unit_name", "unit_dimension",
    "unit_canonical_id", "unit_conversion_factor", "unit_conversion_offset", "methodology_id",
    "methodology_version", "methodology_status", "indicator_governance_json",
    "question_count", "instrument_count", "dataset_count", "batch_count", "observation_count",
    "transformation_count", "lineage_completeness_score", "observation_lineage_json",
    "created_at", "updated_at",
]


def flatten_record(record: Mapping[str, Any]) -> dict[str, Any]:
    entity, indicator, period = record["entity"], record["indicator"], record["period"]
    measurement, source = record["measurement"], record["source"]
    confidence, review, method = record["confidence"], record["review"], record["method"]
    evidence = record.get("evidence_chain", {})
    governance = record.get("indicator_governance", {})
    governed_unit = governance.get("unit", {})
    governed_method = governance.get("methodology", {})
    lineage = record.get("observation_lineage", {})
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
        "indicator_namespace": governance.get("namespace"), "indicator_code": governance.get("code"),
        "indicator_domain": governance.get("domain"), "indicator_custodian": governance.get("custodian"),
        "indicator_status": governance.get("status"), "indicator_frequency": governance.get("frequency"),
        "indicator_aggregation": governance.get("aggregation"), "unit_id": governed_unit.get("id"),
        "unit_symbol": governed_unit.get("symbol"), "unit_name": governed_unit.get("name"),
        "unit_dimension": governed_unit.get("dimension"), "unit_canonical_id": governed_unit.get("canonical_unit_id"),
        "unit_conversion_factor": governed_unit.get("conversion_factor"), "unit_conversion_offset": governed_unit.get("conversion_offset"),
        "methodology_id": governed_method.get("id"),
        "methodology_version": governed_method.get("version"), "methodology_status": governed_method.get("status"),
        "indicator_governance_json": json.dumps(governance, ensure_ascii=False, sort_keys=True),
        "question_count": len(lineage.get("questions", [])), "instrument_count": len(lineage.get("instruments", [])),
        "dataset_count": len(lineage.get("datasets", [])), "batch_count": len(lineage.get("batches", [])),
        "observation_count": len(lineage.get("observations", [])), "transformation_count": len(lineage.get("transformations", [])),
        "lineage_completeness_score": lineage.get("completeness_score"),
        "observation_lineage_json": json.dumps(lineage, ensure_ascii=False, sort_keys=True),
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
