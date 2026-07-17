#!/usr/bin/env python3
"""Generate Catalyst Data record, evidence, and indicator-governance artifacts."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECORD_CONTRACT = ROOT / "contracts" / "record_contract.json"
REVIEW_CONTRACT = ROOT / "contracts" / "review_contract.json"
SCHEMA_URI = "https://sustainablecatalyst.com/schemas/catalyst-data-record-1.0.json"
EVIDENCE_SCHEMA_URI = "https://sustainablecatalyst.com/schemas/catalyst-data-evidence-chain-1.0.json"
GOVERNANCE_SCHEMA_URI = "https://sustainablecatalyst.com/schemas/catalyst-data-indicator-governance-1.0.json"
LINEAGE_SCHEMA_URI = "https://sustainablecatalyst.com/schemas/catalyst-data-observation-lineage-1.0.json"
REVIEW_WORKFLOW_SCHEMA_URI = "https://sustainablecatalyst.com/schemas/catalyst-data-review-workflow-1.0.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def source_schema(record: dict) -> dict:
    string_or_null = {"type": ["string", "null"]}
    return {
        "type": "object", "additionalProperties": False,
        "required": ["id", "name", "type", "url", "publisher", "license", "retrieved_at", "citation", "checksum", "access_notes"],
        "properties": {
            "id": {"type": "string", "pattern": record["id_pattern"]},
            "name": {"type": "string", "minLength": 1},
            "type": {"enum": record["source_types"]},
            "url": {"type": ["string", "null"], "format": "uri"},
            "publisher": string_or_null,
            "license": string_or_null,
            "retrieved_at": {"type": ["string", "null"], "format": "date-time"},
            "citation": string_or_null,
            "checksum": {"type": ["string", "null"], "pattern": record["source_checksum_pattern"]},
            "access_notes": string_or_null,
        },
    }


def evidence_chain_schema(record: dict) -> dict:
    string_or_null = {"type": ["string", "null"]}
    link = {
        "type": "object", "additionalProperties": False,
        "required": ["role", "source", "locator", "supports", "notes"],
        "properties": {
            "role": {"enum": record["evidence_roles"]},
            "source": source_schema(record),
            "locator": {
                "type": "object", "additionalProperties": False,
                "required": ["page", "section", "quote", "fragment"],
                "properties": {"page": string_or_null, "section": string_or_null, "quote": string_or_null, "fragment": string_or_null},
            },
            "supports": {"type": "array", "items": {"type": "string", "minLength": 1}, "uniqueItems": True},
            "notes": string_or_null,
        },
    }
    relationship = {
        "type": "object", "additionalProperties": False,
        "required": ["subject_source_id", "predicate", "object_source_id", "notes"],
        "properties": {
            "subject_source_id": {"type": "string", "pattern": record["id_pattern"]},
            "predicate": {"enum": record["source_relationships"]},
            "object_source_id": {"type": "string", "pattern": record["id_pattern"]},
            "notes": string_or_null,
        },
    }
    transformation = {
        "type": "object", "additionalProperties": False,
        "required": ["id", "operation", "description", "software", "parameters", "occurred_at"],
        "properties": {
            "id": {"type": "string", "pattern": record["id_pattern"]},
            "operation": {"type": "string", "minLength": 1},
            "description": {"type": "string", "minLength": 1},
            "software": string_or_null,
            "parameters": {"type": "object", "additionalProperties": True},
            "occurred_at": {"type": ["string", "null"], "format": "date-time"},
        },
    }
    gap = {
        "type": "object", "additionalProperties": False,
        "required": ["code", "severity", "description"],
        "properties": {
            "code": {"enum": record["evidence_gap_codes"]},
            "severity": {"enum": record["evidence_gap_severities"]},
            "description": {"type": "string", "minLength": 1},
        },
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": EVIDENCE_SCHEMA_URI,
        "title": "Catalyst Data Evidence Chain 1.0",
        "description": "Multiple-source evidence links, relationships, transformations, gaps, and completeness metadata.",
        "type": "object", "additionalProperties": False,
        "required": ["schema_version", "sources", "relationships", "transformations", "gaps", "completeness_score"],
        "properties": {
            "schema_version": {"const": record["evidence_contract"]},
            "sources": {"type": "array", "minItems": 1, "items": link},
            "relationships": {"type": "array", "items": relationship},
            "transformations": {"type": "array", "items": transformation},
            "gaps": {"type": "array", "items": gap},
            "completeness_score": {"type": "integer", "minimum": 0, "maximum": 100},
        },
    }


def indicator_governance_schema(record: dict) -> dict:
    string_or_null = {"type": ["string", "null"]}
    date_time_or_null = {"type": ["string", "null"], "format": "date-time"}
    component = {
        "type": ["object", "null"], "additionalProperties": False,
        "required": ["name", "unit_id", "description"],
        "properties": {
            "name": {"type": "string", "minLength": 1},
            "unit_id": {"type": ["string", "null"], "pattern": record["id_pattern"]},
            "description": string_or_null,
        },
    }
    unit = {
        "type": "object", "additionalProperties": False,
        "required": ["id", "symbol", "name", "dimension", "canonical_unit_id", "conversion_factor", "conversion_offset"],
        "properties": {
            "id": {"type": "string", "pattern": record["id_pattern"]},
            "symbol": {"type": "string", "minLength": 1},
            "name": {"type": "string", "minLength": 1},
            "dimension": {"type": "string", "minLength": 1},
            "canonical_unit_id": {"type": "string", "pattern": record["id_pattern"]},
            "conversion_factor": {"type": "number", "exclusiveMinimum": 0},
            "conversion_offset": {"type": "number"},
        },
    }
    methodology = {
        "type": "object", "additionalProperties": False,
        "required": ["id", "version", "title", "description", "formula", "references", "status", "approved_by", "approved_at", "revision_notes"],
        "properties": {
            "id": {"type": "string", "pattern": record["id_pattern"]},
            "version": {"type": "string", "minLength": 1},
            "title": {"type": "string", "minLength": 1},
            "description": {"type": "string"},
            "formula": string_or_null,
            "references": {"type": "array", "items": {"type": "string", "minLength": 1}, "uniqueItems": True},
            "status": {"enum": record["methodology_statuses"]},
            "approved_by": string_or_null,
            "approved_at": date_time_or_null,
            "revision_notes": string_or_null,
        },
    }
    mapping = {
        "type": "object", "additionalProperties": False,
        "required": ["framework", "code", "relationship", "notes"],
        "properties": {
            "framework": {"type": "string", "minLength": 1},
            "code": {"type": "string", "minLength": 1},
            "relationship": {"enum": record["framework_mapping_relationships"]},
            "notes": string_or_null,
        },
    }
    compatibility = {
        "type": "object", "additionalProperties": False,
        "required": ["comparable_versions", "required_dimensions", "methodology_equivalence", "notes"],
        "properties": {
            "comparable_versions": {"type": "array", "items": {"type": "string", "minLength": 1}, "uniqueItems": True},
            "required_dimensions": {"type": "array", "items": {"type": "string", "minLength": 1}, "uniqueItems": True},
            "methodology_equivalence": {"type": "array", "items": {"type": "string", "pattern": record["id_pattern"]}, "uniqueItems": True},
            "notes": string_or_null,
        },
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": GOVERNANCE_SCHEMA_URI,
        "title": "Catalyst Data Indicator Governance 1.0",
        "description": "Versioned indicator definitions, units, methodologies, mappings, and comparability constraints.",
        "type": "object", "additionalProperties": False,
        "required": ["schema_version", "namespace", "code", "domain", "custodian", "status", "aliases", "definition", "frequency", "aggregation", "disaggregation_dimensions", "numerator", "denominator", "unit", "methodology", "framework_mappings", "compatibility"],
        "properties": {
            "schema_version": {"const": record["indicator_governance_contract"]},
            "namespace": {"type": "string", "pattern": "^[a-z][a-z0-9.-]{1,63}$"},
            "code": {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9._:-]{1,127}$"},
            "domain": {"type": "string", "minLength": 1},
            "custodian": {"type": "string", "minLength": 1},
            "status": {"enum": record["indicator_statuses"]},
            "aliases": {"type": "array", "items": {"type": "string", "minLength": 1}, "uniqueItems": True},
            "definition": {"type": "string", "minLength": 1},
            "frequency": {"enum": record["indicator_frequencies"]},
            "aggregation": {"enum": record["indicator_aggregations"]},
            "disaggregation_dimensions": {"type": "array", "items": {"type": "string", "minLength": 1}, "uniqueItems": True},
            "numerator": component,
            "denominator": component,
            "unit": unit,
            "methodology": methodology,
            "framework_mappings": {"type": "array", "items": mapping},
            "compatibility": compatibility,
        },
    }



def observation_lineage_schema(record: dict) -> dict:
    string_or_null = {"type": ["string", "null"]}
    datetime_or_null = {"type": ["string", "null"], "format": "date-time"}
    field = {
        "type": "object", "additionalProperties": False,
        "required": ["name", "data_type", "unit_id", "description"],
        "properties": {
            "name": {"type": "string", "minLength": 1},
            "data_type": {"enum": ["string", "number", "integer", "boolean", "date", "datetime", "object", "array"]},
            "unit_id": {"type": ["string", "null"], "pattern": record["id_pattern"]},
            "description": string_or_null,
            "required": {"type": "boolean"},
            "nullable": {"type": "boolean"},
        },
        "anyOf": [{"required": ["required"]}, {"required": ["nullable"]}],
    }
    question = {
        "type": "object", "additionalProperties": False,
        "required": ["id", "text", "type", "decision_context", "status", "owner"],
        "properties": {
            "id": {"type": "string", "pattern": record["id_pattern"]},
            "text": {"type": "string", "minLength": 1},
            "type": {"enum": record["question_types"]},
            "decision_context": string_or_null,
            "status": {"enum": record["question_statuses"]},
            "owner": string_or_null,
        },
    }
    instrument = {
        "type": "object", "additionalProperties": False,
        "required": ["id", "name", "type", "version", "description", "protocol", "provider", "calibration", "fields"],
        "properties": {
            "id": {"type": "string", "pattern": record["id_pattern"]},
            "name": {"type": "string", "minLength": 1},
            "type": {"enum": record["instrument_types"]},
            "version": {"type": "string", "minLength": 1},
            "description": string_or_null,
            "protocol": string_or_null,
            "provider": string_or_null,
            "calibration": string_or_null,
            "fields": {"type": "array", "items": field},
        },
    }
    dataset_field = {
        "type": "object", "additionalProperties": False,
        "required": ["name", "data_type", "unit_id", "description", "nullable"],
        "properties": {
            "name": {"type": "string", "minLength": 1},
            "data_type": {"enum": ["string", "number", "integer", "boolean", "date", "datetime", "object", "array"]},
            "unit_id": {"type": ["string", "null"], "pattern": record["id_pattern"]},
            "description": string_or_null,
            "nullable": {"type": "boolean"},
        },
    }
    dataset = {
        "type": "object", "additionalProperties": False,
        "required": ["id", "name", "version", "description", "license", "access", "checksum", "fields"],
        "properties": {
            "id": {"type": "string", "pattern": record["id_pattern"]},
            "name": {"type": "string", "minLength": 1},
            "version": {"type": "string", "minLength": 1},
            "description": string_or_null,
            "license": string_or_null,
            "access": {"enum": record["dataset_access_levels"]},
            "checksum": {"type": ["string", "null"], "pattern": record["source_checksum_pattern"]},
            "fields": {"type": "array", "items": dataset_field},
        },
    }
    batch = {
        "type": "object", "additionalProperties": False,
        "required": ["id", "dataset_id", "instrument_id", "collected_at", "received_at", "collector", "protocol", "record_count", "notes"],
        "properties": {
            "id": {"type": "string", "pattern": record["id_pattern"]},
            "dataset_id": {"type": "string", "pattern": record["id_pattern"]},
            "instrument_id": {"type": "string", "pattern": record["id_pattern"]},
            "collected_at": datetime_or_null,
            "received_at": datetime_or_null,
            "collector": string_or_null,
            "protocol": string_or_null,
            "record_count": {"type": "integer", "minimum": 0},
            "notes": string_or_null,
        },
    }
    observation = {
        "type": "object", "additionalProperties": False,
        "required": ["id", "batch_id", "role", "observed_at", "value", "value_text", "unit_id", "quality_status", "missing_reason", "censoring", "outlier", "imputation", "dimensions", "raw_payload"],
        "properties": {
            "id": {"type": "string", "pattern": record["id_pattern"]},
            "batch_id": {"type": "string", "pattern": record["id_pattern"]},
            "role": {"enum": record["observation_roles"]},
            "observed_at": datetime_or_null,
            "value": {"type": ["number", "null"]},
            "value_text": string_or_null,
            "unit_id": {"type": ["string", "null"], "pattern": record["id_pattern"]},
            "quality_status": {"enum": record["observation_quality_statuses"]},
            "missing_reason": string_or_null,
            "censoring": string_or_null,
            "outlier": {"type": "boolean"},
            "imputation": string_or_null,
            "dimensions": {"type": "object", "additionalProperties": {"type": "string"}},
            "raw_payload": {"type": "object", "additionalProperties": True},
        },
    }
    transformation = {
        "type": "object", "additionalProperties": False,
        "required": ["id", "operation", "description", "software", "parameters", "input_observation_ids", "output_measurement_fields", "occurred_at"],
        "properties": {
            "id": {"type": "string", "pattern": record["id_pattern"]},
            "operation": {"type": "string", "minLength": 1},
            "description": {"type": "string", "minLength": 1},
            "software": string_or_null,
            "parameters": {"type": "object", "additionalProperties": True},
            "input_observation_ids": {"type": "array", "items": {"type": "string", "pattern": record["id_pattern"]}, "uniqueItems": True},
            "output_measurement_fields": {"type": "array", "items": {"type": "string", "minLength": 1}, "uniqueItems": True},
            "occurred_at": datetime_or_null,
        },
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": LINEAGE_SCHEMA_URI,
        "title": "Catalyst Data Observation Lineage 1.0",
        "description": "Research questions, collection instruments, dataset versions, observation batches, observations, and transformations linked to a governed measurement.",
        "type": "object", "additionalProperties": False,
        "required": ["schema_version", "questions", "instruments", "datasets", "batches", "observations", "transformations", "completeness_score"],
        "properties": {
            "schema_version": {"const": record["observation_lineage_contract"]},
            "questions": {"type": "array", "minItems": 1, "items": question},
            "instruments": {"type": "array", "minItems": 1, "items": instrument},
            "datasets": {"type": "array", "minItems": 1, "items": dataset},
            "batches": {"type": "array", "minItems": 1, "items": batch},
            "observations": {"type": "array", "minItems": 1, "items": observation},
            "transformations": {"type": "array", "items": transformation},
            "completeness_score": {"type": "integer", "minimum": 0, "maximum": 100},
        },
    }


def review_workflow_schema(record: dict) -> dict:
    string_or_null = {"type": ["string", "null"]}
    datetime_or_null = {"type": ["string", "null"], "format": "date-time"}
    decision = {
        "type": "object", "additionalProperties": False,
        "required": ["id", "type", "actor", "reason", "notes", "occurred_at"],
        "properties": {
            "id": {"type": "string", "pattern": record["id_pattern"]},
            "type": {"enum": record["review_decision_types"]},
            "actor": {"type": "string", "minLength": 1},
            "reason": string_or_null,
            "notes": string_or_null,
            "occurred_at": {"type": "string", "format": "date-time"},
        },
    }
    comment = {
        "type": "object", "additionalProperties": False,
        "required": ["id", "actor", "body", "visibility", "occurred_at"],
        "properties": {
            "id": {"type": "string", "pattern": record["id_pattern"]},
            "actor": {"type": "string", "minLength": 1},
            "body": {"type": "string", "minLength": 1},
            "visibility": {"enum": record["review_comment_visibilities"]},
            "occurred_at": {"type": "string", "format": "date-time"},
        },
    }
    quality_properties = {name: {"type": "integer", "minimum": 0, "maximum": 100} for name in record["quality_dimensions"]}
    quality_properties.update({
        "overall": {"type": "integer", "minimum": 0, "maximum": 100},
        "basis": {"type": "object", "additionalProperties": {"type": "string"}},
        "assessed_by": {"type": "string", "minLength": 1},
        "assessed_at": {"type": "string", "format": "date-time"},
    })
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": REVIEW_WORKFLOW_SCHEMA_URI,
        "title": "Catalyst Data Review Workflow 1.0",
        "description": "Human review states, quality assessments, publication gates, revision metadata, decisions, and comments.",
        "type": "object", "additionalProperties": False,
        "required": ["schema_version", "state", "priority", "assigned_reviewers", "quality", "publication_gate", "revision", "decisions", "comments"],
        "properties": {
            "schema_version": {"const": record["review_workflow_contract"]},
            "state": {"enum": record["review_states"]},
            "priority": {"enum": record["review_priorities"]},
            "assigned_reviewers": {"type": "array", "items": {"type": "string", "minLength": 1}, "uniqueItems": True},
            "quality": {"type": "object", "additionalProperties": False, "required": [*record["quality_dimensions"], "overall", "basis", "assessed_by", "assessed_at"], "properties": quality_properties},
            "publication_gate": {
                "type": "object", "additionalProperties": False,
                "required": ["status", "reasons", "approved_by", "approved_at"],
                "properties": {
                    "status": {"enum": record["publication_gate_statuses"]},
                    "reasons": {"type": "array", "items": {"type": "string", "minLength": 1}, "uniqueItems": True},
                    "approved_by": string_or_null,
                    "approved_at": datetime_or_null,
                },
            },
            "revision": {
                "type": "object", "additionalProperties": False,
                "required": ["number", "action", "change_summary", "reason", "changed_by", "compared_to_sha256"],
                "properties": {
                    "number": {"type": "integer", "minimum": 1},
                    "action": {"enum": ["inserted", "updated", "corrected", "superseded"]},
                    "change_summary": {"type": "string", "minLength": 1},
                    "reason": string_or_null,
                    "changed_by": {"type": "string", "minLength": 1},
                    "compared_to_sha256": {"type": ["string", "null"], "pattern": "^[0-9a-f]{64}$"},
                },
            },
            "decisions": {"type": "array", "items": decision},
            "comments": {"type": "array", "items": comment},
        },
    }

def record_schema(record: dict, review: dict) -> dict:
    string_or_null = {"type": ["string", "null"]}
    date_or_null = {"type": ["string", "null"], "format": "date"}
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": SCHEMA_URI,
        "title": "Catalyst Data Record 1.0",
        "description": "Canonical measurement record with review, quality, revisions, provenance, evidence, indicator governance, and observation lineage.",
        "type": "object", "additionalProperties": False,
        "required": ["$schema", "schema_version", "record_id", "record_type", "created_at", "updated_at", "producer", "entity", "indicator", "period", "measurement", "source", "confidence", "review", "method", "extensions"],
        "properties": {
            "$schema": {"const": SCHEMA_URI},
            "schema_version": {"const": record["contract"]},
            "record_id": {"type": "string", "pattern": record["id_pattern"]},
            "record_type": {"enum": record["record_types"]},
            "created_at": {"type": "string", "format": "date-time"},
            "updated_at": {"type": "string", "format": "date-time"},
            "producer": {"type": "object", "additionalProperties": False, "required": ["name", "version", "component"], "properties": {"name": {"type": "string", "minLength": 1}, "version": {"type": "string", "pattern": r"^\d+\.\d+\.\d+$"}, "component": {"enum": record["producer_components"]}}},
            "entity": {"type": "object", "additionalProperties": False, "required": ["id", "name", "type", "external_ids"], "properties": {"id": {"type": "string", "pattern": record["id_pattern"]}, "name": {"type": "string", "minLength": 1}, "type": {"enum": record["entity_types"]}, "external_ids": {"type": "object", "propertyNames": {"pattern": record["extension_key_pattern"]}, "additionalProperties": {"type": "string", "minLength": 1}}}},
            "indicator": {"type": "object", "additionalProperties": False, "required": ["id", "name", "unit", "direction", "framework", "version"], "properties": {"id": {"type": "string", "pattern": record["id_pattern"]}, "name": {"type": "string", "minLength": 1}, "unit": {"type": "string", "minLength": 1}, "direction": {"enum": review["directions"]}, "framework": string_or_null, "version": {"type": "string", "minLength": 1}}},
            "indicator_governance": indicator_governance_schema(record),
            "observation_lineage": observation_lineage_schema(record),
            "review_workflow": review_workflow_schema(record),
            "period": {"type": "object", "additionalProperties": False, "required": ["id", "label", "start_date", "end_date"], "properties": {"id": {"type": "string", "pattern": record["id_pattern"]}, "label": {"type": "string", "minLength": 1}, "start_date": date_or_null, "end_date": date_or_null}},
            "measurement": {"type": "object", "additionalProperties": False, "required": ["baseline", "current", "percent_change"], "properties": {"baseline": {"type": ["number", "null"]}, "current": {"type": "number"}, "percent_change": {"type": ["number", "null"]}}},
            "source": source_schema(record),
            "evidence_chain": evidence_chain_schema(record),
            "confidence": {"type": "object", "additionalProperties": False, "required": ["score", "scale", "basis"], "properties": {"score": {"type": "number", "minimum": review["confidence"]["minimum"], "maximum": review["confidence"]["maximum"]}, "scale": {"const": "0-100"}, "basis": string_or_null}},
            "review": {"type": "object", "additionalProperties": False, "required": ["status", "signal_status", "reviewer_notes"], "properties": {"status": {"enum": review["review_statuses"]}, "signal_status": {"enum": review["signal_statuses"]}, "reviewer_notes": {"type": "string"}}},
            "method": {"type": "object", "additionalProperties": False, "required": ["notes", "assumptions", "limitations", "uncertainty", "quality_flags"], "properties": {"notes": {"type": "string"}, "assumptions": {"type": "array", "items": {"type": "string", "minLength": 1}, "uniqueItems": True}, "limitations": {"type": "array", "items": {"type": "string", "minLength": 1}, "uniqueItems": True}, "uncertainty": string_or_null, "quality_flags": {"type": "array", "items": {"enum": record["quality_flags"]}, "uniqueItems": True}}},
            "extensions": {"type": "object", "propertyNames": {"pattern": record["extension_key_pattern"]}, "additionalProperties": True},
        },
    }


def python_constants(record: dict) -> str:
    names = [
        ("RECORD_CONTRACT", record["contract"]), ("RECORD_SCHEMA_URI", SCHEMA_URI),
        ("EVIDENCE_CONTRACT", record["evidence_contract"]), ("EVIDENCE_SCHEMA_URI", EVIDENCE_SCHEMA_URI),
        ("INDICATOR_GOVERNANCE_CONTRACT", record["indicator_governance_contract"]), ("INDICATOR_GOVERNANCE_SCHEMA_URI", GOVERNANCE_SCHEMA_URI),
        ("OBSERVATION_LINEAGE_CONTRACT", record["observation_lineage_contract"]), ("OBSERVATION_LINEAGE_SCHEMA_URI", LINEAGE_SCHEMA_URI),
        ("REVIEW_WORKFLOW_CONTRACT", record["review_workflow_contract"]), ("REVIEW_WORKFLOW_SCHEMA_URI", REVIEW_WORKFLOW_SCHEMA_URI),
    ]
    lines = ['"""Generated from contracts/record_contract.json. Do not edit by hand."""', ""]
    for name, value in names: lines.append(f"{name} = {value!r}")
    tuples = {
        "RECORD_TYPES":"record_types", "ENTITY_TYPES":"entity_types", "SOURCE_TYPES":"source_types", "PRODUCER_COMPONENTS":"producer_components",
        "QUALITY_FLAGS":"quality_flags", "EVIDENCE_ROLES":"evidence_roles", "SOURCE_RELATIONSHIPS":"source_relationships",
        "PROVENANCE_EVENT_TYPES":"provenance_event_types", "EVIDENCE_GAP_SEVERITIES":"evidence_gap_severities", "EVIDENCE_GAP_CODES":"evidence_gap_codes",
        "INDICATOR_STATUSES":"indicator_statuses", "INDICATOR_FREQUENCIES":"indicator_frequencies", "INDICATOR_AGGREGATIONS":"indicator_aggregations",
        "METHODOLOGY_STATUSES":"methodology_statuses", "FRAMEWORK_MAPPING_RELATIONSHIPS":"framework_mapping_relationships",
        "COMPARABILITY_STATUSES":"comparability_statuses", "GOVERNANCE_EVENT_TYPES":"governance_event_types",
        "QUESTION_TYPES":"question_types", "QUESTION_STATUSES":"question_statuses", "INSTRUMENT_TYPES":"instrument_types",
        "DATASET_ACCESS_LEVELS":"dataset_access_levels", "OBSERVATION_ROLES":"observation_roles",
        "OBSERVATION_QUALITY_STATUSES":"observation_quality_statuses", "LINEAGE_EVENT_TYPES":"lineage_event_types",
        "REVIEW_STATES":"review_states", "REVIEW_PRIORITIES":"review_priorities", "REVIEW_DECISION_TYPES":"review_decision_types",
        "REVIEW_COMMENT_VISIBILITIES":"review_comment_visibilities", "PUBLICATION_GATE_STATUSES":"publication_gate_statuses", "QUALITY_DIMENSIONS":"quality_dimensions",
        "LEGACY_CONTRACTS":"legacy_contracts",
    }
    for name, key in tuples.items(): lines.append(f"{name} = {tuple(record[key])!r}")
    lines.extend([
        f"ID_PATTERN = {record['id_pattern']!r}", f"EXTENSION_KEY_PATTERN = {record['extension_key_pattern']!r}",
        f"SOURCE_CHECKSUM_PATTERN = {record['source_checksum_pattern']!r}", ""
    ])
    return "\n".join(lines)


def javascript_constants(record: dict, review: dict) -> str:
    payload = {
        "contract": record["contract"], "release_version": (ROOT / "VERSION").read_text().strip(), "schema_uri": SCHEMA_URI,
        "evidence_contract": record["evidence_contract"], "evidence_schema_uri": EVIDENCE_SCHEMA_URI,
        "indicator_governance_contract": record["indicator_governance_contract"], "indicator_governance_schema_uri": GOVERNANCE_SCHEMA_URI,
        "observation_lineage_contract": record["observation_lineage_contract"], "observation_lineage_schema_uri": LINEAGE_SCHEMA_URI,
        "review_workflow_contract": record["review_workflow_contract"], "review_workflow_schema_uri": REVIEW_WORKFLOW_SCHEMA_URI,
        "record_types": record["record_types"], "entity_types": record["entity_types"], "source_types": record["source_types"],
        "producer_components": record["producer_components"], "quality_flags": record["quality_flags"], "evidence_roles": record["evidence_roles"],
        "source_relationships": record["source_relationships"], "indicator_statuses": record["indicator_statuses"],
        "indicator_frequencies": record["indicator_frequencies"], "indicator_aggregations": record["indicator_aggregations"],
        "methodology_statuses": record["methodology_statuses"], "framework_mapping_relationships": record["framework_mapping_relationships"],
        "comparability_statuses": record["comparability_statuses"], "question_types": record["question_types"],
        "question_statuses": record["question_statuses"], "instrument_types": record["instrument_types"],
        "dataset_access_levels": record["dataset_access_levels"], "observation_roles": record["observation_roles"],
        "observation_quality_statuses": record["observation_quality_statuses"], "review_states": record["review_states"],
        "review_priorities": record["review_priorities"], "review_decision_types": record["review_decision_types"],
        "publication_gate_statuses": record["publication_gate_statuses"], "quality_dimensions": record["quality_dimensions"], "id_pattern": record["id_pattern"],
        "extension_key_pattern": record["extension_key_pattern"], "review_statuses": review["review_statuses"], "signal_statuses": review["signal_statuses"]
    }
    return "/* Generated from contracts/record_contract.json. Do not edit by hand. */\n(function(root){\n  root.CatalystDataRecordContract = Object.freeze(" + json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + ");\n})(typeof globalThis !== 'undefined' ? globalThis : this);\n"


def export_alias(canonical: dict) -> dict:
    alias = json.loads(json.dumps(canonical))
    alias["$id"] = "https://sustainablecatalyst.com/schemas/catalyst-data-export-1.6.0.json"
    alias["title"] = "Catalyst Data Export 1.6.0"
    alias["description"] = "Compatibility export schema for record/1.0 with evidence-chain, indicator-governance, observation-lineage, and review-workflow metadata."
    return alias


def rendered_outputs() -> dict[Path, str]:
    record = load(RECORD_CONTRACT); review = load(REVIEW_CONTRACT)
    canonical = record_schema(record, review); evidence = evidence_chain_schema(record); governance = indicator_governance_schema(record); lineage = observation_lineage_schema(record); workflow = review_workflow_schema(record)
    canonical_text = json.dumps(canonical, indent=2, ensure_ascii=False) + "\n"
    evidence_text = json.dumps(evidence, indent=2, ensure_ascii=False) + "\n"
    governance_text = json.dumps(governance, indent=2, ensure_ascii=False) + "\n"
    lineage_text = json.dumps(lineage, indent=2, ensure_ascii=False) + "\n"
    workflow_text = json.dumps(workflow, indent=2, ensure_ascii=False) + "\n"
    return {
        ROOT / "schemas/catalyst_data_record_1_0.schema.json": canonical_text,
        ROOT / "schemas/catalyst_data_evidence_chain_1_0.schema.json": evidence_text,
        ROOT / "schemas/catalyst_data_indicator_governance_1_0.schema.json": governance_text,
        ROOT / "schemas/catalyst_data_observation_lineage_1_0.schema.json": lineage_text,
        ROOT / "schemas/catalyst_data_review_workflow_1_0.schema.json": workflow_text,
        ROOT / "schemas/catalyst_data_export.schema.json": json.dumps(export_alias(canonical), indent=2, ensure_ascii=False) + "\n",
        ROOT / "python/catalyst_data/schemas/catalyst_data_record_1_0.schema.json": canonical_text,
        ROOT / "python/catalyst_data/schemas/catalyst_data_evidence_chain_1_0.schema.json": evidence_text,
        ROOT / "python/catalyst_data/schemas/catalyst_data_indicator_governance_1_0.schema.json": governance_text,
        ROOT / "python/catalyst_data/schemas/catalyst_data_observation_lineage_1_0.schema.json": lineage_text,
        ROOT / "python/catalyst_data/schemas/catalyst_data_review_workflow_1_0.schema.json": workflow_text,
        ROOT / "python/catalyst_data/_record_contract.py": python_constants(record),
        ROOT / "wordpress/catalyst-data-demo/assets/catalyst-data-record-contract.js": javascript_constants(record, review),
    }


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--check", action="store_true"); args = parser.parse_args()
    stale=[]
    for path, content in rendered_outputs().items():
        if path.exists() and path.read_text(encoding="utf-8") == content: continue
        if args.check: stale.append(str(path.relative_to(ROOT)))
        else: path.parent.mkdir(parents=True, exist_ok=True); path.write_text(content, encoding="utf-8"); print(f"wrote {path.relative_to(ROOT)}")
    if stale:
        print("Generated record contract artifacts are stale:")
        for item in stale: print(f"- {item}")
        return 1
    return 0


if __name__ == "__main__": raise SystemExit(main())
