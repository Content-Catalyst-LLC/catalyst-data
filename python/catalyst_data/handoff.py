from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone
from importlib.resources import files
from pathlib import Path
from typing import Any, Mapping, Sequence

HANDOFF_CONTRACT = "catalyst-data-handoff/1.0"
SUPPORTED_PRODUCTS = (
    "catalyst-data", "knowledge-library", "research-librarian", "site-intelligence",
    "workbench", "research-lab", "catalyst-analytics-r", "catalyst-canvas",
    "decision-studio", "platform-core",
)
HANDOFF_ACTIONS = ("record-reference", "record-transfer", "query-run-reference", "export-bundle-reference")

class HandoffValidationError(ValueError):
    pass


def _canonical(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def handoff_digest(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def handoff_schema() -> dict[str, Any]:
    path = files("catalyst_data").joinpath("schemas/catalyst_data_handoff_1_0.schema.json")
    return json.loads(path.read_text(encoding="utf-8"))


def validate_handoff(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise HandoffValidationError("handoff must be an object")
    try:
        from jsonschema import Draft202012Validator, FormatChecker
        errors = sorted(Draft202012Validator(handoff_schema(), format_checker=FormatChecker()).iter_errors(payload), key=lambda item: list(item.path))
        if errors:
            message = "; ".join(f"{'.'.join(map(str, error.path)) or '$'}: {error.message}" for error in errors[:8])
            raise HandoffValidationError(message)
    except ImportError:
        required = {"schema_version", "handoff_id", "created_at", "source", "target", "action", "records", "context"}
        if set(payload) - (required | {"query_run_id", "bundle_uri", "extensions"}) or not required.issubset(payload):
            raise HandoffValidationError("handoff fields are invalid")
        if payload.get("schema_version") != HANDOFF_CONTRACT or payload.get("action") not in HANDOFF_ACTIONS:
            raise HandoffValidationError("handoff contract or action is invalid")
    return deepcopy(dict(payload))


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def create_handoff(
    records: Sequence[Mapping[str, Any]], *, target_product: str, target_capability: str,
    source_version: str, source_component: str = "handoff-service",
    source_product: str = "catalyst-data", action: str = "record-reference",
    api_base_url: str | None = None, query_run_id: str | None = None,
    bundle_uri: str | None = None, context: Mapping[str, Any] | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    if target_product not in SUPPORTED_PRODUCTS or source_product not in SUPPORTED_PRODUCTS:
        raise HandoffValidationError("unsupported handoff product")
    if action not in HANDOFF_ACTIONS:
        raise HandoffValidationError("unsupported handoff action")
    refs: list[dict[str, Any]] = []
    for record in records:
        record_id = str(record.get("record_id", "")).strip()
        if not record_id:
            raise HandoffValidationError("record_id is required")
        digest = hashlib.sha256(_canonical(record).encode("utf-8")).hexdigest()
        href = f"{api_base_url.rstrip('/')}/v1/records/{record_id}" if api_base_url else None
        refs.append({"record_id": record_id, "record_sha256": digest, "href": href})
    timestamp = created_at or _now()
    seed = _canonical({"source": source_product, "target": target_product, "capability": target_capability, "records": refs, "created_at": timestamp, "action": action})
    payload = {
        "schema_version": HANDOFF_CONTRACT,
        "handoff_id": "handoff:" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24],
        "created_at": timestamp,
        "source": {"product": source_product, "version": source_version, "component": source_component, "capability": "evidence-records"},
        "target": {"product": target_product, "version": "unknown", "component": "integration", "capability": target_capability},
        "action": action,
        "records": refs,
        "query_run_id": query_run_id,
        "bundle_uri": bundle_uri,
        "context": dict(context or {}),
        "extensions": {},
    }
    return validate_handoff(payload)


def read_handoff(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return validate_handoff(payload)
