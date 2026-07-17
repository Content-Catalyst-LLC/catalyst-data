from __future__ import annotations

import hashlib
import json
import math
import re
from copy import deepcopy
from typing import Any, Mapping

from ._record_contract import (
    COMPARABILITY_STATUSES,
    FRAMEWORK_MAPPING_RELATIONSHIPS,
    INDICATOR_AGGREGATIONS,
    INDICATOR_FREQUENCIES,
    INDICATOR_GOVERNANCE_CONTRACT,
    INDICATOR_STATUSES,
    METHODOLOGY_STATUSES,
)


def _stable_id(kind: str, *parts: Any) -> str:
    canonical = json.dumps([str(part).strip().lower() for part in parts], separators=(",", ":"), ensure_ascii=False)
    return f"{kind}:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()[:20]}"


def _text(value: Any, default: str | None = None) -> str | None:
    if value is None:
        return default
    result = str(value).strip()
    return result or default


def _list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, (list, tuple)):
        values = list(value)
    else:
        raise ValueError("governance list fields must be arrays")
    return list(dict.fromkeys(str(item).strip() for item in values if str(item).strip()))


def _number(value: Any, field: str, default: float) -> float:
    candidate = default if value in (None, "") else value
    if isinstance(candidate, bool) or not isinstance(candidate, (int, float)):
        try:
            candidate = float(candidate)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} must be numeric") from exc
    result = float(candidate)
    if not math.isfinite(result):
        raise ValueError(f"{field} must be finite")
    return result


def _component(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError("indicator numerator and denominator must be objects or null")
    name = _text(value.get("name"))
    if not name:
        raise ValueError("indicator numerator and denominator require a name")
    return {
        "name": name,
        "unit_id": _text(value.get("unit_id")),
        "description": _text(value.get("description")),
    }


def normalize_unit(value: Any, indicator_unit: str) -> dict[str, Any]:
    raw = value if isinstance(value, Mapping) else {}
    symbol = _text(raw.get("symbol"), indicator_unit) or indicator_unit
    name = _text(raw.get("name"), symbol) or symbol
    dimension = _text(raw.get("dimension"), re.sub(r"[^a-z0-9]+", "_", symbol.lower()).strip("_") or "unspecified") or "unspecified"
    unit_id = _text(raw.get("id")) or _stable_id("unit", dimension, symbol)
    canonical_unit_id = _text(raw.get("canonical_unit_id")) or unit_id
    factor = _number(raw.get("conversion_factor"), "unit.conversion_factor", 1.0)
    offset = _number(raw.get("conversion_offset"), "unit.conversion_offset", 0.0)
    if factor <= 0:
        raise ValueError("unit.conversion_factor must be greater than zero")
    return {
        "id": unit_id,
        "symbol": symbol,
        "name": name,
        "dimension": dimension,
        "canonical_unit_id": canonical_unit_id,
        "conversion_factor": factor,
        "conversion_offset": offset,
    }


def normalize_methodology(value: Any, indicator: Mapping[str, Any], method: Mapping[str, Any]) -> dict[str, Any]:
    raw = value if isinstance(value, Mapping) else {}
    title = _text(raw.get("title"), f"{indicator['name']} methodology") or f"{indicator['name']} methodology"
    description = _text(raw.get("description"), _text(method.get("notes"), "")) or ""
    method_id = _text(raw.get("id")) or _stable_id("method", indicator["id"], title)
    status = _text(raw.get("status"), "draft") or "draft"
    if status not in METHODOLOGY_STATUSES:
        raise ValueError(f"methodology.status must be one of: {', '.join(METHODOLOGY_STATUSES)}")
    approved_by = _text(raw.get("approved_by"))
    approved_at = _text(raw.get("approved_at"))
    if status == "approved" and (not approved_by or not approved_at):
        raise ValueError("approved methodology requires approved_by and approved_at")
    return {
        "id": method_id,
        "version": _text(raw.get("version"), str(indicator.get("version") or "1.0")) or "1.0",
        "title": title,
        "description": description,
        "formula": _text(raw.get("formula")),
        "references": _list(raw.get("references")),
        "status": status,
        "approved_by": approved_by,
        "approved_at": approved_at,
        "revision_notes": _text(raw.get("revision_notes")),
    }


def normalize_indicator_governance(
    indicator: Mapping[str, Any],
    method: Mapping[str, Any],
    raw_governance: Any = None,
) -> dict[str, Any]:
    raw = raw_governance if isinstance(raw_governance, Mapping) else {}
    namespace = (_text(raw.get("namespace"), "sc") or "sc").lower()
    code = _text(raw.get("code"), str(indicator["id"]).split(":", 1)[-1]) or str(indicator["id"]).split(":", 1)[-1]
    status = _text(raw.get("status"), "active") or "active"
    frequency = _text(raw.get("frequency"), "annual") or "annual"
    aggregation = _text(raw.get("aggregation"), "point-estimate") or "point-estimate"
    if status not in INDICATOR_STATUSES:
        raise ValueError(f"indicator governance status must be one of: {', '.join(INDICATOR_STATUSES)}")
    if frequency not in INDICATOR_FREQUENCIES:
        raise ValueError(f"indicator frequency must be one of: {', '.join(INDICATOR_FREQUENCIES)}")
    if aggregation not in INDICATOR_AGGREGATIONS:
        raise ValueError(f"indicator aggregation must be one of: {', '.join(INDICATOR_AGGREGATIONS)}")

    unit = normalize_unit(raw.get("unit"), str(indicator["unit"]))
    methodology = normalize_methodology(raw.get("methodology"), indicator, method)
    mappings: list[dict[str, Any]] = []
    seen_mappings: set[tuple[str, str, str]] = set()
    for item in raw.get("framework_mappings", []):
        if not isinstance(item, Mapping):
            raise ValueError("framework mappings must be objects")
        framework = _text(item.get("framework")); mapping_code = _text(item.get("code")); relationship = _text(item.get("relationship"), "relatedMatch") or "relatedMatch"
        if not framework or not mapping_code:
            raise ValueError("framework mappings require framework and code")
        if relationship not in FRAMEWORK_MAPPING_RELATIONSHIPS:
            raise ValueError(f"framework mapping relationship must be one of: {', '.join(FRAMEWORK_MAPPING_RELATIONSHIPS)}")
        key = (framework.lower(), mapping_code.lower(), relationship)
        if key not in seen_mappings:
            mappings.append({"framework": framework, "code": mapping_code, "relationship": relationship, "notes": _text(item.get("notes"))})
            seen_mappings.add(key)
    if indicator.get("framework") and not mappings:
        mappings.append({"framework": str(indicator["framework"]), "code": code, "relationship": "exactMatch", "notes": None})

    compatibility_raw = raw.get("compatibility") if isinstance(raw.get("compatibility"), Mapping) else {}
    comparable_versions = _list(compatibility_raw.get("comparable_versions")) or [str(indicator.get("version") or "1.0")]
    methodology_equivalence = _list(compatibility_raw.get("methodology_equivalence")) or [methodology["id"]]
    governance = {
        "schema_version": INDICATOR_GOVERNANCE_CONTRACT,
        "namespace": namespace,
        "code": code,
        "domain": _text(raw.get("domain"), _text(indicator.get("framework"), "general")) or "general",
        "custodian": _text(raw.get("custodian"), "Content Catalyst LLC") or "Content Catalyst LLC",
        "status": status,
        "aliases": _list(raw.get("aliases")),
        "definition": _text(raw.get("definition"), str(indicator["name"])) or str(indicator["name"]),
        "frequency": frequency,
        "aggregation": aggregation,
        "disaggregation_dimensions": _list(raw.get("disaggregation_dimensions")),
        "numerator": _component(raw.get("numerator")),
        "denominator": _component(raw.get("denominator")),
        "unit": unit,
        "methodology": methodology,
        "framework_mappings": mappings,
        "compatibility": {
            "comparable_versions": comparable_versions,
            "required_dimensions": _list(compatibility_raw.get("required_dimensions")),
            "methodology_equivalence": methodology_equivalence,
            "notes": _text(compatibility_raw.get("notes")),
        },
    }
    validate_indicator_governance(governance, indicator)
    return governance


def validate_indicator_governance(governance: Mapping[str, Any], indicator: Mapping[str, Any]) -> None:
    if governance.get("schema_version") != INDICATOR_GOVERNANCE_CONTRACT:
        raise ValueError("indicator_governance schema version is invalid")
    if governance["unit"]["symbol"] != indicator["unit"]:
        raise ValueError("indicator_governance.unit.symbol must match indicator.unit")
    if not re.fullmatch(r"^[a-z][a-z0-9.-]{1,63}$", str(governance["namespace"])):
        raise ValueError("indicator governance namespace is invalid")
    if governance["methodology"]["status"] == "approved" and (
        not governance["methodology"].get("approved_by") or not governance["methodology"].get("approved_at")
    ):
        raise ValueError("approved methodology requires approval metadata")
    if indicator["version"] not in governance["compatibility"]["comparable_versions"]:
        raise ValueError("indicator version must appear in compatibility.comparable_versions")
    if governance["methodology"]["id"] not in governance["compatibility"]["methodology_equivalence"]:
        raise ValueError("current methodology must appear in compatibility.methodology_equivalence")


def governance_digest(governance: Mapping[str, Any]) -> str:
    payload = json.dumps(governance, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def convert_value(value: float, from_unit: Mapping[str, Any], to_unit: Mapping[str, Any]) -> float:
    if from_unit["dimension"] != to_unit["dimension"]:
        raise ValueError("units have incompatible dimensions")
    if from_unit["canonical_unit_id"] != to_unit["canonical_unit_id"]:
        raise ValueError("units do not share a canonical conversion basis")
    numeric = _number(value, "value", 0.0)
    canonical = numeric * float(from_unit["conversion_factor"]) + float(from_unit["conversion_offset"])
    result = (canonical - float(to_unit["conversion_offset"])) / float(to_unit["conversion_factor"])
    return round(result, 12)


def compare_governance(left: Mapping[str, Any], right: Mapping[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []
    left_indicator = left["indicator"]; right_indicator = right["indicator"]
    left_g = left["indicator_governance"]; right_g = right["indicator_governance"]
    status = "equivalent"

    if left_indicator["id"] != right_indicator["id"]:
        return {"status": "incompatible", "reasons": ["indicator IDs differ"], "conversion_available": False}
    if left_indicator["direction"] != right_indicator["direction"]:
        return {"status": "incompatible", "reasons": ["indicator directions differ"], "conversion_available": False}
    left_unit = left_g["unit"]; right_unit = right_g["unit"]
    if left_unit["dimension"] != right_unit["dimension"] or left_unit["canonical_unit_id"] != right_unit["canonical_unit_id"]:
        return {"status": "incompatible", "reasons": ["unit dimensions or canonical bases differ"], "conversion_available": False}
    if left_unit["id"] != right_unit["id"]:
        status = "convertible"
        reasons.append("units differ but share a conversion basis")
    if left_g["frequency"] != right_g["frequency"]:
        status = "limited"
        reasons.append("measurement frequencies differ")
    if left_g["aggregation"] != right_g["aggregation"]:
        status = "limited"
        reasons.append("aggregation methods differ")
    left_method = left_g["methodology"]; right_method = right_g["methodology"]
    left_equiv = set(left_g["compatibility"]["methodology_equivalence"])
    right_equiv = set(right_g["compatibility"]["methodology_equivalence"])
    if left_method["id"] != right_method["id"] and not ({left_method["id"], right_method["id"]} <= (left_equiv | right_equiv)):
        status = "limited"
        reasons.append("methodologies are not declared equivalent")
    if right_indicator["version"] not in left_g["compatibility"]["comparable_versions"] or left_indicator["version"] not in right_g["compatibility"]["comparable_versions"]:
        status = "limited"
        reasons.append("indicator versions are not mutually declared comparable")
    required = set(left_g["compatibility"]["required_dimensions"]) | set(right_g["compatibility"]["required_dimensions"])
    left_dims = set(left_g["disaggregation_dimensions"]); right_dims = set(right_g["disaggregation_dimensions"])
    missing = sorted(required - (left_dims & right_dims))
    if missing:
        status = "limited"
        reasons.append("required dimensions are not shared: " + ", ".join(missing))
    if status not in COMPARABILITY_STATUSES:
        raise AssertionError("invalid comparability status")
    return {"status": status, "reasons": reasons or ["governance definitions are equivalent"], "conversion_available": status in {"equivalent", "convertible"}}
