from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Mapping

from ._record_contract import (
    PUBLICATION_GATE_STATUSES,
    QUALITY_DIMENSIONS,
    REVIEW_COMMENT_VISIBILITIES,
    REVIEW_DECISION_TYPES,
    REVIEW_PRIORITIES,
    REVIEW_STATES,
    REVIEW_WORKFLOW_CONTRACT,
)

_STATE_DECISIONS = {
    "submitted": "submitted",
    "review_started": "in-review",
    "changes_requested": "changes-requested",
    "approved": "approved",
    "rejected": "rejected",
    "superseded": "superseded",
    "archived": "archived",
    "reopened": "draft",
}

_ALLOWED_TRANSITIONS = {
    "draft": {"submitted", "archived"},
    "submitted": {"review_started", "changes_requested", "rejected", "archived"},
    "in-review": {"changes_requested", "approved", "rejected", "archived"},
    "changes-requested": {"submitted", "review_started", "rejected", "archived"},
    "approved": {"superseded", "archived"},
    "rejected": {"submitted", "archived"},
    "superseded": {"archived"},
    "archived": {"reopened"},
}


def _canonical(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _id(prefix: str, *parts: Any) -> str:
    digest = hashlib.sha256("|".join(str(part) for part in parts).encode("utf-8")).hexdigest()[:24]
    return f"{prefix}:{digest}"


def _timestamp(value: str | None = None) -> str:
    if value:
        candidate = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    else:
        candidate = datetime.now(timezone.utc)
    if candidate.tzinfo is None:
        candidate = candidate.replace(tzinfo=timezone.utc)
    return candidate.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def quality_overall(quality: Mapping[str, Any]) -> int:
    scores = [int(quality[name]) for name in QUALITY_DIMENSIONS]
    return round(sum(scores) / len(scores))


def derive_quality(record: Mapping[str, Any], *, assessed_by: str | None = None, assessed_at: str | None = None) -> dict[str, Any]:
    evidence = int(record.get("evidence_chain", {}).get("completeness_score", 0))
    lineage = int(record.get("observation_lineage", {}).get("completeness_score", 0))
    flags = set(record.get("method", {}).get("quality_flags", []))
    observations = record.get("observation_lineage", {}).get("observations", [])
    flagged_observations = sum(1 for item in observations if item.get("quality_status") in {"outlier", "rejected"})
    missing_observations = sum(1 for item in observations if item.get("quality_status") == "missing")

    completeness = max(0, min(100, round((evidence + lineage) / 2)))
    validity = max(25, 100 - (12 * len(flags)) - (12 * flagged_observations) - (5 * missing_observations))
    consistency = 92
    if "conflicting" in flags:
        consistency -= 35
    if record.get("indicator_governance", {}).get("status") != "active":
        consistency -= 15
    consistency = max(25, consistency)
    timeliness = 45 if "stale" in flags else 85
    provenance = evidence
    uncertainty = 85 if record.get("method", {}).get("uncertainty") else 55
    if record.get("method", {}).get("limitations"):
        uncertainty = min(100, uncertainty + 5)

    quality = {
        "completeness": completeness,
        "validity": validity,
        "consistency": consistency,
        "timeliness": timeliness,
        "provenance": provenance,
        "uncertainty": uncertainty,
        "overall": 0,
        "basis": {
            "completeness": "Average of evidence-chain and observation-lineage completeness.",
            "validity": "Derived from method quality flags and observation quality states.",
            "consistency": "Derived from indicator governance status and conflicting-data flags.",
            "timeliness": "Reduced when the record is explicitly marked stale.",
            "provenance": "Equal to evidence-chain completeness.",
            "uncertainty": "Higher when uncertainty and limitations are explicitly documented.",
        },
        "assessed_by": assessed_by or str(record.get("producer", {}).get("component", "repository-service")),
        "assessed_at": _timestamp(assessed_at or str(record.get("updated_at"))),
    }
    quality["overall"] = quality_overall(quality)
    return quality


def publication_gate(record: Mapping[str, Any], state: str, quality: Mapping[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []
    critical_gaps = [gap for gap in record.get("evidence_chain", {}).get("gaps", []) if gap.get("severity") == "critical"]
    if state != "approved":
        reasons.append("record has not been approved")
    if int(quality["overall"]) < 70:
        reasons.append("overall quality score is below 70")
    if critical_gaps:
        reasons.append("critical evidence gaps remain open")
    if state == "approved" and not reasons:
        status = "external"
    elif state in {"submitted", "in-review", "changes-requested", "approved"} and int(quality["overall"]) >= 50:
        status = "internal"
    else:
        status = "blocked"
    return {"status": status, "reasons": reasons, "approved_by": None, "approved_at": None}


def normalize_review_workflow(record: Mapping[str, Any], supplied: Mapping[str, Any] | None = None) -> dict[str, Any]:
    supplied = deepcopy(dict(supplied or {}))
    state = str(supplied.get("state", "draft"))
    if state not in REVIEW_STATES:
        raise ValueError("review_workflow.state is invalid")
    priority = str(supplied.get("priority", "normal"))
    if priority not in REVIEW_PRIORITIES:
        raise ValueError("review_workflow.priority is invalid")
    reviewers = list(dict.fromkeys(str(item).strip() for item in supplied.get("assigned_reviewers", []) if str(item).strip()))
    quality = deepcopy(supplied.get("quality")) if isinstance(supplied.get("quality"), Mapping) else derive_quality(record)
    quality.setdefault("overall", quality_overall(quality))
    quality.setdefault("basis", {})
    quality.setdefault("assessed_by", str(record.get("producer", {}).get("component", "repository-service")))
    quality.setdefault("assessed_at", str(record.get("updated_at")))
    gate = deepcopy(supplied.get("publication_gate")) if isinstance(supplied.get("publication_gate"), Mapping) else publication_gate(record, state, quality)
    revision = deepcopy(supplied.get("revision")) if isinstance(supplied.get("revision"), Mapping) else {
        "number": 1,
        "action": "inserted",
        "change_summary": "Initial governed record revision.",
        "reason": "Initial repository registration.",
        "changed_by": str(record.get("producer", {}).get("component", "repository-service")),
        "compared_to_sha256": None,
    }
    decisions = deepcopy(supplied.get("decisions", []))
    comments = deepcopy(supplied.get("comments", []))
    workflow = {
        "schema_version": REVIEW_WORKFLOW_CONTRACT,
        "state": state,
        "priority": priority,
        "assigned_reviewers": reviewers,
        "quality": quality,
        "publication_gate": gate,
        "revision": revision,
        "decisions": decisions,
        "comments": comments,
    }
    validate_review_workflow(workflow, record)
    return workflow


def validate_review_workflow(workflow: Mapping[str, Any], record: Mapping[str, Any] | None = None) -> None:
    expected = {"schema_version", "state", "priority", "assigned_reviewers", "quality", "publication_gate", "revision", "decisions", "comments"}
    if set(workflow) != expected:
        raise ValueError("review_workflow has invalid fields")
    if workflow.get("schema_version") != REVIEW_WORKFLOW_CONTRACT:
        raise ValueError("review_workflow schema version is invalid")
    if workflow.get("state") not in REVIEW_STATES or workflow.get("priority") not in REVIEW_PRIORITIES:
        raise ValueError("review_workflow state or priority is invalid")
    reviewers = workflow.get("assigned_reviewers")
    if not isinstance(reviewers, list) or len(reviewers) != len(set(reviewers)) or any(not str(item).strip() for item in reviewers):
        raise ValueError("review_workflow assigned reviewers are invalid")
    quality = workflow.get("quality")
    required_quality = set(QUALITY_DIMENSIONS) | {"overall", "basis", "assessed_by", "assessed_at"}
    if not isinstance(quality, Mapping) or set(quality) != required_quality:
        raise ValueError("review_workflow quality assessment is invalid")
    for dimension in (*QUALITY_DIMENSIONS, "overall"):
        value = quality.get(dimension)
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
            raise ValueError(f"review_workflow quality.{dimension} must be an integer from 0 to 100")
    if quality["overall"] != quality_overall(quality):
        raise ValueError("review_workflow quality.overall does not match dimension scores")
    if not isinstance(quality.get("basis"), Mapping) or not str(quality.get("assessed_by", "")).strip():
        raise ValueError("review_workflow quality basis or assessor is invalid")
    _timestamp(str(quality.get("assessed_at")))
    gate = workflow.get("publication_gate")
    if not isinstance(gate, Mapping) or set(gate) != {"status", "reasons", "approved_by", "approved_at"}:
        raise ValueError("review_workflow publication gate is invalid")
    if gate.get("status") not in PUBLICATION_GATE_STATUSES or not isinstance(gate.get("reasons"), list):
        raise ValueError("review_workflow publication gate status or reasons are invalid")
    if gate.get("status") == "external" and workflow.get("state") != "approved":
        raise ValueError("external publication requires an approved review state")
    revision = workflow.get("revision")
    if not isinstance(revision, Mapping) or set(revision) != {"number", "action", "change_summary", "reason", "changed_by", "compared_to_sha256"}:
        raise ValueError("review_workflow revision is invalid")
    if not isinstance(revision.get("number"), int) or revision["number"] < 1 or revision.get("action") not in {"inserted", "updated", "corrected", "superseded"}:
        raise ValueError("review_workflow revision number or action is invalid")
    if not str(revision.get("changed_by", "")).strip():
        raise ValueError("review_workflow revision changed_by is required")
    checksum = revision.get("compared_to_sha256")
    if checksum is not None and (not isinstance(checksum, str) or len(checksum) != 64 or any(ch not in "0123456789abcdef" for ch in checksum)):
        raise ValueError("review_workflow revision compared_to_sha256 is invalid")
    decision_ids: set[str] = set()
    for decision in workflow.get("decisions", []):
        if set(decision) != {"id", "type", "actor", "reason", "notes", "occurred_at"} or decision.get("type") not in REVIEW_DECISION_TYPES:
            raise ValueError("review_workflow decision is invalid")
        if decision["id"] in decision_ids or not str(decision.get("actor", "")).strip():
            raise ValueError("review_workflow decision id or actor is invalid")
        decision_ids.add(decision["id"]); _timestamp(str(decision["occurred_at"]))
    comment_ids: set[str] = set()
    for comment in workflow.get("comments", []):
        if set(comment) != {"id", "actor", "body", "visibility", "occurred_at"} or comment.get("visibility") not in REVIEW_COMMENT_VISIBILITIES:
            raise ValueError("review_workflow comment is invalid")
        if comment["id"] in comment_ids or not str(comment.get("actor", "")).strip() or not str(comment.get("body", "")).strip():
            raise ValueError("review_workflow comment id, actor, or body is invalid")
        comment_ids.add(comment["id"]); _timestamp(str(comment["occurred_at"]))
    if workflow["state"] == "approved" and not any(item["type"] == "approved" for item in workflow["decisions"]):
        raise ValueError("approved review state requires an approval decision")


def append_decision(workflow: Mapping[str, Any], decision_type: str, actor: str, *, reason: str | None = None, notes: str | None = None, occurred_at: str | None = None) -> dict[str, Any]:
    if decision_type not in REVIEW_DECISION_TYPES:
        raise ValueError("review decision type is invalid")
    current = str(workflow["state"])
    if decision_type in _STATE_DECISIONS and decision_type not in _ALLOWED_TRANSITIONS.get(current, set()):
        raise ValueError(f"review transition {current!r} -> {decision_type!r} is not allowed")
    timestamp = _timestamp(occurred_at)
    result = deepcopy(dict(workflow))
    decision = {
        "id": _id("review-decision", actor, decision_type, timestamp, reason or "", notes or ""),
        "type": decision_type,
        "actor": str(actor).strip(),
        "reason": reason,
        "notes": notes,
        "occurred_at": timestamp,
    }
    result["decisions"].append(decision)
    if decision_type in _STATE_DECISIONS:
        result["state"] = _STATE_DECISIONS[decision_type]
    return result


def append_comment(workflow: Mapping[str, Any], actor: str, body: str, *, visibility: str = "internal", occurred_at: str | None = None) -> dict[str, Any]:
    if visibility not in REVIEW_COMMENT_VISIBILITIES:
        raise ValueError("review comment visibility is invalid")
    timestamp = _timestamp(occurred_at)
    result = deepcopy(dict(workflow))
    result["comments"].append({
        "id": _id("review-comment", actor, body, timestamp),
        "actor": str(actor).strip(),
        "body": str(body).strip(),
        "visibility": visibility,
        "occurred_at": timestamp,
    })
    return result


def review_digest(workflow: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical(workflow).encode("utf-8")).hexdigest()
