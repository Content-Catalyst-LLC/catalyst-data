from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any, Mapping

from ._record_contract import (
    DATASET_ACCESS_LEVELS,
    INSTRUMENT_TYPES,
    OBSERVATION_LINEAGE_CONTRACT,
    OBSERVATION_QUALITY_STATUSES,
    OBSERVATION_ROLES,
    QUESTION_STATUSES,
    QUESTION_TYPES,
)


def _text(value: Any) -> str | None:
    if value is None:
        return None
    result = str(value).strip()
    return result or None


def _list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        items = [part.strip() for part in value.replace(";", "|").split("|")]
    else:
        items = [str(part).strip() for part in value]
    return list(dict.fromkeys(item for item in items if item))


def _id(kind: str, *parts: Any) -> str:
    normalized = "|".join(str(part or "").strip().lower() for part in parts)
    anchor = re_slug(next((str(part) for part in parts if str(part or "").strip()), kind))
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
    return f"{kind}:{anchor}:{digest}"


def re_slug(value: str) -> str:
    import re
    result = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return (result or "unspecified")[:64]


def _instrument_type(source_type: str) -> str:
    mapping = {
        "survey": "survey", "sensor": "sensor", "api": "api", "model estimate": "model",
        "public registry": "administrative", "internal record": "administrative",
        "third-party dataset": "administrative", "publication": "manual",
    }
    return mapping.get(source_type, "other")


def _observation(
    *, record_id: str, role: str, value: float | None, observed_at: str,
    unit_id: str, entity_id: str, period_id: str, batch_id: str,
) -> dict[str, Any]:
    quality = "missing" if value is None else "valid"
    return {
        "id": _id("observation", record_id, role),
        "batch_id": batch_id,
        "role": role,
        "observed_at": observed_at,
        "value": value,
        "value_text": None,
        "unit_id": unit_id,
        "quality_status": quality,
        "missing_reason": "baseline not supplied" if value is None else None,
        "censoring": None,
        "outlier": False,
        "imputation": None,
        "dimensions": {"entity_id": entity_id, "period_id": period_id},
        "raw_payload": {},
    }


def normalize_observation_lineage(record: Mapping[str, Any], raw: Mapping[str, Any] | None = None) -> dict[str, Any]:
    raw = deepcopy(dict(raw or {}))
    entity = record["entity"]; indicator = record["indicator"]; period = record["period"]
    source = record["source"]; measurement = record["measurement"]
    unit = record["indicator_governance"]["unit"]
    method = record["indicator_governance"]["methodology"]
    updated_at = record["updated_at"]

    question_id = _id("question", entity["id"], indicator["id"])
    default_question = {
        "id": question_id,
        "text": f"What is the value of {indicator['name']} for {entity['name']} during {period['label']}?",
        "type": "monitoring",
        "decision_context": None,
        "status": "active",
        "owner": record["producer"]["name"],
    }
    questions = raw.get("questions") or [default_question]

    instrument_id = _id("instrument", source["id"], source["type"])
    default_instrument = {
        "id": instrument_id,
        "name": f"{source['name']} collection instrument",
        "type": _instrument_type(source["type"]),
        "version": "1.0",
        "description": source.get("access_notes") or f"Collection instrument associated with {source['name']}.",
        "protocol": method.get("description") or record["method"].get("notes") or None,
        "provider": source.get("publisher"),
        "calibration": None,
        "fields": [
            {"name": "value", "data_type": "number", "unit_id": unit["id"], "description": indicator["name"], "required": True},
            {"name": "observed_at", "data_type": "datetime", "unit_id": None, "description": "Observation timestamp", "required": True},
        ],
    }
    instruments = raw.get("instruments") or [default_instrument]

    dataset_id = _id("dataset", source["id"], indicator["id"])
    default_dataset = {
        "id": dataset_id,
        "name": source["name"],
        "version": source.get("checksum") or source.get("retrieved_at") or "1.0",
        "description": source.get("citation") or f"Dataset supporting {indicator['name']}.",
        "license": source.get("license"),
        "access": "restricted" if "restricted" in record["method"].get("quality_flags", []) else "public",
        "checksum": source.get("checksum"),
        "fields": [
            {"name": "value", "data_type": "number", "unit_id": unit["id"], "description": indicator["name"], "nullable": False},
            {"name": "entity_id", "data_type": "string", "unit_id": None, "description": "Canonical entity identifier", "nullable": False},
            {"name": "period_id", "data_type": "string", "unit_id": None, "description": "Canonical reporting period identifier", "nullable": False},
        ],
    }
    datasets = raw.get("datasets") or [default_dataset]

    batch_id = _id("batch", record["record_id"], updated_at)
    default_batch = {
        "id": batch_id,
        "dataset_id": datasets[0]["id"],
        "instrument_id": instruments[0]["id"],
        "collected_at": period.get("end_date") + "T00:00:00Z" if period.get("end_date") else updated_at,
        "received_at": source.get("retrieved_at") or updated_at,
        "collector": source.get("publisher") or record["producer"]["name"],
        "protocol": record["method"].get("notes") or None,
        "record_count": 2 if measurement.get("baseline") is not None else 1,
        "notes": None,
    }
    batches = raw.get("batches") or [default_batch]

    default_observations = []
    if measurement.get("baseline") is not None:
        default_observations.append(_observation(record_id=record["record_id"], role="baseline", value=measurement["baseline"], observed_at=period.get("start_date") + "T00:00:00Z" if period.get("start_date") else updated_at, unit_id=unit["id"], entity_id=entity["id"], period_id=period["id"], batch_id=batches[0]["id"]))
    default_observations.append(_observation(record_id=record["record_id"], role="current", value=measurement["current"], observed_at=period.get("end_date") + "T00:00:00Z" if period.get("end_date") else updated_at, unit_id=unit["id"], entity_id=entity["id"], period_id=period["id"], batch_id=batches[0]["id"]))
    observations = raw.get("observations") or default_observations

    transformation_id = _id("transformation", record["record_id"], method["id"], method["version"])
    transformations = raw.get("transformations") or [{
        "id": transformation_id,
        "operation": "identity" if len(observations) == 1 else "baseline-current comparison",
        "description": record["method"].get("notes") or "Map governed observations to the canonical measurement.",
        "software": record["producer"]["name"],
        "parameters": {"methodology_id": method["id"], "methodology_version": method["version"]},
        "input_observation_ids": [item["id"] for item in observations],
        "output_measurement_fields": ["measurement.baseline", "measurement.current", "measurement.percent_change"],
        "occurred_at": updated_at,
    }]

    result = {
        "schema_version": OBSERVATION_LINEAGE_CONTRACT,
        "questions": questions,
        "instruments": instruments,
        "datasets": datasets,
        "batches": batches,
        "observations": observations,
        "transformations": transformations,
        "completeness_score": 0,
    }
    result["completeness_score"] = lineage_completeness(result)
    validate_observation_lineage(result, record)
    return result


def lineage_completeness(lineage: Mapping[str, Any]) -> int:
    score = 0
    score += 15 if lineage.get("questions") else 0
    score += 15 if lineage.get("instruments") else 0
    score += 15 if lineage.get("datasets") else 0
    score += 15 if lineage.get("batches") else 0
    score += 20 if lineage.get("observations") else 0
    score += 15 if lineage.get("transformations") else 0
    observations = lineage.get("observations") or []
    score += 5 if observations and all(item.get("dimensions") for item in observations) else 0
    return min(score, 100)


def validate_observation_lineage(lineage: Mapping[str, Any], record: Mapping[str, Any]) -> None:
    if lineage.get("schema_version") != OBSERVATION_LINEAGE_CONTRACT:
        raise ValueError("observation_lineage schema version is invalid")
    if not lineage.get("questions"):
        raise ValueError("observation_lineage requires at least one question")
    if not lineage.get("instruments"):
        raise ValueError("observation_lineage requires at least one instrument")
    if not lineage.get("datasets"):
        raise ValueError("observation_lineage requires at least one dataset")
    if not lineage.get("batches"):
        raise ValueError("observation_lineage requires at least one batch")
    if not lineage.get("observations"):
        raise ValueError("observation_lineage requires at least one observation")
    question_ids = {item["id"] for item in lineage["questions"]}
    instrument_ids = {item["id"] for item in lineage["instruments"]}
    dataset_ids = {item["id"] for item in lineage["datasets"]}
    batch_ids = {item["id"] for item in lineage["batches"]}
    observation_ids = {item["id"] for item in lineage["observations"]}
    if len(question_ids) != len(lineage["questions"]): raise ValueError("question IDs must be unique")
    if len(instrument_ids) != len(lineage["instruments"]): raise ValueError("instrument IDs must be unique")
    if len(dataset_ids) != len(lineage["datasets"]): raise ValueError("dataset IDs must be unique")
    if len(batch_ids) != len(lineage["batches"]): raise ValueError("batch IDs must be unique")
    if len(observation_ids) != len(lineage["observations"]): raise ValueError("observation IDs must be unique")
    for question in lineage["questions"]:
        if question["type"] not in QUESTION_TYPES or question["status"] not in QUESTION_STATUSES:
            raise ValueError("question type or status is invalid")
    for instrument in lineage["instruments"]:
        if instrument["type"] not in INSTRUMENT_TYPES:
            raise ValueError("instrument type is invalid")
    for dataset in lineage["datasets"]:
        if dataset["access"] not in DATASET_ACCESS_LEVELS:
            raise ValueError("dataset access level is invalid")
    for batch in lineage["batches"]:
        if batch["dataset_id"] not in dataset_ids or batch["instrument_id"] not in instrument_ids:
            raise ValueError("batch references an unknown dataset or instrument")
    for observation in lineage["observations"]:
        if observation["batch_id"] not in batch_ids:
            raise ValueError("observation references an unknown batch")
        if observation["role"] not in OBSERVATION_ROLES or observation["quality_status"] not in OBSERVATION_QUALITY_STATUSES:
            raise ValueError("observation role or quality status is invalid")
        if observation["quality_status"] == "missing" and not observation.get("missing_reason"):
            raise ValueError("missing observation requires missing_reason")
    for transformation in lineage["transformations"]:
        unknown = set(transformation["input_observation_ids"]) - observation_ids
        if unknown:
            raise ValueError("transformation references unknown observations: " + ", ".join(sorted(unknown)))
    expected = lineage_completeness(lineage)
    if lineage.get("completeness_score") != expected:
        raise ValueError(f"observation_lineage.completeness_score must be {expected}")
    roles = {item["role"] for item in lineage["observations"]}
    if "current" not in roles:
        raise ValueError("observation_lineage requires a current observation")
    current_values = [item["value"] for item in lineage["observations"] if item["role"] == "current" and item["quality_status"] != "missing"]
    if current_values and float(current_values[-1]) != float(record["measurement"]["current"]):
        raise ValueError("current observation must match measurement.current")
