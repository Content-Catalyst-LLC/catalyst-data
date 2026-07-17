from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Mapping

from ._record_contract import (
    EVIDENCE_CONTRACT,
    EVIDENCE_GAP_CODES,
    EVIDENCE_GAP_SEVERITIES,
    EVIDENCE_ROLES,
    SOURCE_RELATIONSHIPS,
)


def _stable_id(kind: str, *parts: Any) -> str:
    canonical = json.dumps([str(part).strip().lower() for part in parts], separators=(",", ":"), ensure_ascii=False)
    return f"{kind}:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()[:20]}"


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _timestamp(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        candidate = value
    else:
        candidate = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if candidate.tzinfo is None:
        candidate = candidate.replace(tzinfo=timezone.utc)
    return candidate.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def source_payload(source: Mapping[str, Any]) -> dict[str, Any]:
    name = str(source.get("name") or "Unspecified source").strip() or "Unspecified source"
    source_type = str(source.get("type") or "unspecified").strip() or "unspecified"
    source_id = str(source.get("id") or _stable_id("source", name, source.get("publisher") or "", source.get("url") or ""))
    return {
        "id": source_id,
        "name": name,
        "type": source_type,
        "url": _text(source.get("url")),
        "publisher": _text(source.get("publisher")),
        "license": _text(source.get("license")),
        "retrieved_at": _timestamp(source.get("retrieved_at")),
        "citation": _text(source.get("citation")),
        "checksum": _text(source.get("checksum")),
        "access_notes": _text(source.get("access_notes")),
    }


def source_digest(source: Mapping[str, Any]) -> str:
    payload = json.dumps(source_payload(source), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _locator(value: Any) -> dict[str, str | None]:
    raw = value if isinstance(value, Mapping) else {}
    return {name: _text(raw.get(name)) for name in ("page", "section", "quote", "fragment")}


def _source_link(value: Mapping[str, Any], default_role: str = "supporting") -> dict[str, Any]:
    source = value.get("source") if isinstance(value.get("source"), Mapping) else value
    role = str(value.get("role", default_role)).strip() or default_role
    if role not in EVIDENCE_ROLES:
        raise ValueError(f"evidence source role must be one of: {', '.join(EVIDENCE_ROLES)}")
    supports = value.get("supports", ["measurement.current"])
    if isinstance(supports, str):
        supports = [supports]
    if not isinstance(supports, list):
        raise ValueError("evidence source supports must be an array")
    normalized_supports = list(dict.fromkeys(str(item).strip() for item in supports if str(item).strip()))
    return {
        "role": role,
        "source": source_payload(source),
        "locator": _locator(value.get("locator")),
        "supports": normalized_supports,
        "notes": _text(value.get("notes")),
    }


def derive_gaps(
    source_links: list[Mapping[str, Any]],
    method: Mapping[str, Any],
    confidence: Mapping[str, Any],
) -> list[dict[str, str]]:
    gaps: list[dict[str, str]] = []

    def add(code: str, severity: str, description: str) -> None:
        if code not in EVIDENCE_GAP_CODES or severity not in EVIDENCE_GAP_SEVERITIES:
            raise ValueError("invalid evidence gap")
        if not any(item["code"] == code for item in gaps):
            gaps.append({"code": code, "severity": severity, "description": description})

    if not source_links:
        add("missing-source", "critical", "No source is linked to the measurement.")
        return gaps
    sources = [item["source"] for item in source_links]
    if not any(item.get("role") == "primary" for item in source_links):
        add("missing-source", "critical", "No primary source is identified.")
    if any(not source.get("citation") for source in sources):
        add("missing-citation", "warning", "One or more linked sources lack a citation.")
    if any(not source.get("license") for source in sources):
        add("missing-license", "warning", "One or more linked sources lack license metadata.")
    if any(not source.get("retrieved_at") for source in sources):
        add("missing-retrieval-date", "warning", "One or more linked sources lack a retrieval timestamp.")
    if any(not source.get("checksum") for source in sources):
        add("missing-checksum", "info", "One or more linked sources lack a content checksum.")
    if not str(method.get("notes") or "").strip():
        add("missing-method", "warning", "The measurement has no method description.")
    if float(confidence.get("score", 0)) < 40:
        add("low-confidence", "warning", "Confidence is below the evidence-readiness threshold.")
    if any(item.get("role") == "conflicting" for item in source_links):
        add("conflicting-evidence", "warning", "The evidence chain includes conflicting evidence.")
    if any("restricted" in str(source.get("access_notes") or "").lower() for source in sources):
        add("restricted-source", "warning", "The evidence chain includes a restricted source.")
    return gaps


def completeness_score(
    source_links: list[Mapping[str, Any]],
    method: Mapping[str, Any],
    confidence: Mapping[str, Any],
) -> int:
    if not source_links:
        return 0
    sources = [item["source"] for item in source_links]
    score = 20 if any(item.get("role") == "primary" for item in source_links) else 0
    score += 15 if all(source.get("citation") for source in sources) else 0
    score += 10 if all(source.get("license") for source in sources) else 0
    score += 10 if all(source.get("retrieved_at") for source in sources) else 0
    score += 10 if all(source.get("checksum") for source in sources) else 0
    score += 15 if str(method.get("notes") or "").strip() else 0
    score += 10 if float(confidence.get("score", 0)) >= 40 else 0
    score += 5 if len(source_links) > 1 else 0
    score += 5 if not any(item.get("role") == "conflicting" for item in source_links) else 0
    return min(score, 100)


def normalize_evidence_chain(
    primary_source: Mapping[str, Any],
    raw_chain: Any,
    *,
    method: Mapping[str, Any],
    confidence: Mapping[str, Any],
    occurred_at: str,
) -> dict[str, Any]:
    raw = raw_chain if isinstance(raw_chain, Mapping) else {}
    raw_sources = raw.get("sources") if isinstance(raw.get("sources"), list) else []
    links: list[dict[str, Any]] = []
    for item in raw_sources:
        if not isinstance(item, Mapping):
            raise ValueError("evidence_chain.sources entries must be objects")
        links.append(_source_link(item))
    primary = source_payload(primary_source)
    primary_matches = [item for item in links if item["source"]["id"] == primary["id"]]
    if primary_matches:
        primary_matches[0]["role"] = "primary"
        primary_matches[0]["source"] = primary
    else:
        links.insert(0, {"role": "primary", "source": primary, "locator": _locator(None), "supports": ["measurement.baseline", "measurement.current"], "notes": None})

    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in links:
        key = (item["source"]["id"], item["role"])
        if key not in seen:
            deduped.append(item); seen.add(key)
    links = deduped

    ids = {item["source"]["id"] for item in links}
    relationships=[]
    for item in raw.get("relationships", []):
        if not isinstance(item, Mapping):
            raise ValueError("evidence relationships must be objects")
        predicate = str(item.get("predicate", "")).strip()
        subject = str(item.get("subject_source_id", "")).strip()
        obj = str(item.get("object_source_id", "")).strip()
        if predicate not in SOURCE_RELATIONSHIPS:
            raise ValueError(f"source relationship must be one of: {', '.join(SOURCE_RELATIONSHIPS)}")
        if subject not in ids or obj not in ids:
            raise ValueError("source relationships must reference linked source IDs")
        relationships.append({"subject_source_id": subject, "predicate": predicate, "object_source_id": obj, "notes": _text(item.get("notes"))})

    transformations=[]
    for index, item in enumerate(raw.get("transformations", []), start=1):
        if not isinstance(item, Mapping):
            raise ValueError("evidence transformations must be objects")
        operation = _text(item.get("operation"))
        description = _text(item.get("description"))
        if not operation or not description:
            raise ValueError("evidence transformations require operation and description")
        transformations.append({
            "id": _text(item.get("id")) or _stable_id("transformation", operation, description, index),
            "operation": operation,
            "description": description,
            "software": _text(item.get("software")),
            "parameters": deepcopy(item.get("parameters", {})) if isinstance(item.get("parameters", {}), Mapping) else {},
            "occurred_at": _timestamp(item.get("occurred_at")) or occurred_at,
        })

    calculated_gaps = derive_gaps(links, method, confidence)
    for item in raw.get("gaps", []):
        if not isinstance(item, Mapping):
            continue
        code = str(item.get("code", "")); severity = str(item.get("severity", "")); description = _text(item.get("description"))
        if code in EVIDENCE_GAP_CODES and severity in EVIDENCE_GAP_SEVERITIES and description and not any(gap["code"] == code for gap in calculated_gaps):
            calculated_gaps.append({"code": code, "severity": severity, "description": description})

    return {
        "schema_version": EVIDENCE_CONTRACT,
        "sources": links,
        "relationships": relationships,
        "transformations": transformations,
        "gaps": calculated_gaps,
        "completeness_score": completeness_score(links, method, confidence),
    }


def validate_evidence_chain_semantics(record: Mapping[str, Any]) -> None:
    chain = record.get("evidence_chain")
    if chain is None:
        return
    links = chain["sources"]
    primary_id = record["source"]["id"]
    primary = [item for item in links if item["role"] == "primary"]
    if not primary or primary[0]["source"]["id"] != primary_id:
        raise ValueError("evidence_chain primary source must match record.source")
    if source_payload(primary[0]["source"]) != source_payload(record["source"]):
        raise ValueError("evidence_chain primary source metadata must match record.source")
    expected = completeness_score(links, record["method"], record["confidence"])
    if chain["completeness_score"] != expected:
        raise ValueError(f"evidence_chain.completeness_score must be {expected}")
    derived_codes = {item["code"] for item in derive_gaps(links, record["method"], record["confidence"])}
    actual_codes = {item["code"] for item in chain["gaps"]}
    if not derived_codes.issubset(actual_codes):
        raise ValueError("evidence_chain.gaps omits one or more derived evidence gaps")
