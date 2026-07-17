from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import sqlite3
import zipfile
from collections import defaultdict
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from .database import connect, transaction
from .exporter import CSV_FIELDS, flatten_record
from .governance import compare_governance, convert_value
from .repository import CatalystRepository, canonical_json, payload_hash

QUERY_SCHEMA_VERSION = "catalyst-data-query/1.0"
BUNDLE_SCHEMA_VERSION = "catalyst-data-export-bundle/1.0"
ALLOWED_FILTERS = {
    "record_ids", "entity_ids", "entity_types", "entity_names", "indicator_ids",
    "indicator_names", "indicator_codes", "frameworks", "period_ids", "period_labels",
    "period_start_from", "period_end_to", "source_ids", "review_states",
    "publication_statuses", "evidence_statuses", "quality_min", "confidence_min",
    "tags", "search",
}
ALLOWED_SORT_FIELDS = {
    "record_id", "entity.name", "entity.type", "indicator.name", "indicator.id",
    "indicator_governance.code", "indicator.framework", "period.label", "period.start_date",
    "period.end_date", "measurement.current", "measurement.baseline",
    "measurement.percent_change", "confidence.score", "review_workflow.state",
    "review_workflow.quality.overall", "updated_at",
}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _stable_id(kind: str, *parts: Any) -> str:
    encoded = canonical_json({"parts": [str(part) for part in parts]})
    return f"{kind}:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24]


def _get(record: Mapping[str, Any], path: str, default: Any = None) -> Any:
    value: Any = record
    for component in path.split("."):
        if not isinstance(value, Mapping) or component not in value:
            return default
        value = value[component]
    return value


def normalize_query_definition(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("query definition must be an object")
    filters = dict(value.get("filters") or {})
    unknown = sorted(set(filters) - ALLOWED_FILTERS)
    if unknown:
        raise ValueError("unsupported query filters: " + ", ".join(unknown))
    sort = value.get("sort") or [
        {"field": "entity.name", "direction": "asc"},
        {"field": "indicator.name", "direction": "asc"},
        {"field": "period.start_date", "direction": "asc"},
        {"field": "period.label", "direction": "asc"},
        {"field": "record_id", "direction": "asc"},
    ]
    if not isinstance(sort, list):
        raise ValueError("query sort must be an array")
    normalized_sort: list[dict[str, str]] = []
    for item in sort:
        if not isinstance(item, Mapping):
            raise ValueError("query sort entries must be objects")
        field = str(item.get("field") or "").strip()
        direction = str(item.get("direction") or "asc").strip().lower()
        if field not in ALLOWED_SORT_FIELDS:
            raise ValueError(f"unsupported sort field: {field}")
        if direction not in {"asc", "desc"}:
            raise ValueError("sort direction must be asc or desc")
        normalized_sort.append({"field": field, "direction": direction})
    limit = int(value.get("limit", 1000))
    if limit < 1 or limit > 1_000_000:
        raise ValueError("query limit must be between 1 and 1000000")
    return {
        "schema_version": QUERY_SCHEMA_VERSION,
        "name": str(value.get("name") or "Ad hoc query").strip(),
        "description": str(value.get("description") or "").strip() or None,
        "filters": filters,
        "sort": normalized_sort,
        "limit": limit,
    }


def _as_set(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        return {value}
    return {str(item) for item in value}


def _record_tags(record: Mapping[str, Any]) -> set[str]:
    extensions = record.get("extensions") or {}
    tags = extensions.get("sc:tags") or extensions.get("tags") or []
    return _as_set(tags)


def _matches(record: Mapping[str, Any], filters: Mapping[str, Any]) -> bool:
    membership = {
        "record_ids": record.get("record_id"),
        "entity_ids": _get(record, "entity.id"),
        "entity_types": _get(record, "entity.type"),
        "entity_names": _get(record, "entity.name"),
        "indicator_ids": _get(record, "indicator.id"),
        "indicator_names": _get(record, "indicator.name"),
        "indicator_codes": _get(record, "indicator_governance.code"),
        "frameworks": _get(record, "indicator.framework"),
        "period_ids": _get(record, "period.id"),
        "period_labels": _get(record, "period.label"),
        "source_ids": _get(record, "source.id"),
        "review_states": _get(record, "review_workflow.state"),
        "publication_statuses": _get(record, "review_workflow.publication_gate.status"),
        "evidence_statuses": _get(record, "review.status"),
    }
    for name, actual in membership.items():
        expected = _as_set(filters.get(name))
        if expected and str(actual) not in expected:
            return False
    start_from = filters.get("period_start_from")
    if start_from and str(_get(record, "period.start_date") or "") < str(start_from):
        return False
    end_to = filters.get("period_end_to")
    if end_to and str(_get(record, "period.end_date") or "9999-12-31") > str(end_to):
        return False
    quality_min = filters.get("quality_min")
    if quality_min is not None and float(_get(record, "review_workflow.quality.overall", 0)) < float(quality_min):
        return False
    confidence_min = filters.get("confidence_min")
    if confidence_min is not None and float(_get(record, "confidence.score", 0)) < float(confidence_min):
        return False
    tags = _as_set(filters.get("tags"))
    if tags and not tags.issubset(_record_tags(record)):
        return False
    search = str(filters.get("search") or "").strip().lower()
    if search:
        haystack = " ".join(
            str(value or "") for value in (
                record.get("record_id"), _get(record, "entity.name"), _get(record, "indicator.name"),
                _get(record, "indicator.framework"), _get(record, "period.label"),
                _get(record, "source.name"), _get(record, "method.notes"),
            )
        ).lower()
        if search not in haystack:
            return False
    return True


def _sort_value(record: Mapping[str, Any], field: str) -> tuple[int, Any]:
    value = _get(record, field)
    if value is None:
        return (1, "")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return (0, float(value))
    return (0, str(value).lower())


def apply_query(records: Sequence[Mapping[str, Any]], definition: Mapping[str, Any]) -> list[dict[str, Any]]:
    query = normalize_query_definition(definition)
    selected = [dict(record) for record in records if _matches(record, query["filters"])]
    for item in reversed(query["sort"]):
        selected.sort(key=lambda record, field=item["field"]: _sort_value(record, field), reverse=item["direction"] == "desc")
    return selected[: query["limit"]]


def comparison_rows(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[(str(_get(record, "entity.id")), str(_get(record, "indicator.id")))].append(record)
    rows: list[dict[str, Any]] = []
    for (entity_id, indicator_id), group in grouped.items():
        ordered = sorted(group, key=lambda record: (str(_get(record, "period.start_date") or ""), str(_get(record, "period.label") or ""), str(record["record_id"])))
        for left, right in zip(ordered, ordered[1:]):
            comparability = compare_governance(left, right)
            left_value = float(_get(left, "measurement.current"))
            right_value = float(_get(right, "measurement.current"))
            converted_right = right_value
            if comparability["status"] == "convertible":
                converted_right = convert_value(right_value, right["indicator_governance"]["unit"], left["indicator_governance"]["unit"])
            absolute_change = None if comparability["status"] == "incompatible" else converted_right - left_value
            percent_change = None
            if absolute_change is not None and left_value != 0:
                percent_change = round(absolute_change / abs(left_value) * 100.0, 4)
            rows.append({
                "entity_id": entity_id,
                "entity_name": _get(left, "entity.name"),
                "indicator_id": indicator_id,
                "indicator_name": _get(left, "indicator.name"),
                "from_record_id": left["record_id"], "to_record_id": right["record_id"],
                "from_period": _get(left, "period.label"), "to_period": _get(right, "period.label"),
                "from_value": left_value, "to_value": right_value,
                "comparison_unit": _get(left, "indicator_governance.unit.symbol"),
                "converted_to_value": converted_right,
                "absolute_change": None if absolute_change is None else round(absolute_change, 12),
                "percent_change": percent_change,
                "comparability": comparability,
            })
    return rows


def query_warnings(records: Sequence[Mapping[str, Any]], comparisons: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    for record in records:
        record_id = str(record["record_id"])
        gate = _get(record, "review_workflow.publication_gate.status")
        if gate == "blocked":
            warnings.append({"code": "publication-blocked", "severity": "blocking", "record_ids": [record_id], "message": "Record is blocked from publication."})
        quality = int(_get(record, "review_workflow.quality.overall", 0))
        if quality < 70:
            warnings.append({"code": "quality-below-70", "severity": "caution", "record_ids": [record_id], "message": f"Record quality score is {quality}."})
        if _get(record, "review.status") != "reviewable":
            warnings.append({"code": "evidence-review", "severity": "caution", "record_ids": [record_id], "message": f"Evidence status is {_get(record, 'review.status')}."})
    for comparison in comparisons:
        status = comparison["comparability"]["status"]
        if status in {"limited", "incompatible"}:
            warnings.append({
                "code": f"comparison-{status}", "severity": "blocking" if status == "incompatible" else "caution",
                "record_ids": [comparison["from_record_id"], comparison["to_record_id"]],
                "message": "; ".join(comparison["comparability"]["reasons"]),
            })
    return warnings


def query_summary(records: Sequence[Mapping[str, Any]], comparisons: Sequence[Mapping[str, Any]], warnings: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    currents = [float(_get(record, "measurement.current")) for record in records]
    changes = [float(row["percent_change"]) for row in comparisons if row.get("percent_change") is not None]
    return {
        "record_count": len(records),
        "entity_count": len({_get(record, "entity.id") for record in records}),
        "indicator_count": len({_get(record, "indicator.id") for record in records}),
        "period_count": len({_get(record, "period.id") for record in records}),
        "warning_count": len(warnings),
        "blocking_warning_count": sum(1 for item in warnings if item["severity"] == "blocking"),
        "current": {
            "minimum": min(currents) if currents else None,
            "maximum": max(currents) if currents else None,
            "mean": round(sum(currents) / len(currents), 6) if currents else None,
        },
        "period_change": {
            "comparison_count": len(comparisons),
            "mean_percent_change": round(sum(changes) / len(changes), 6) if changes else None,
        },
    }


def brief_markdown(run: Mapping[str, Any]) -> str:
    summary = run["summary"]
    lines = [
        f"# {run['definition']['name']}", "",
        run["definition"].get("description") or "Reproducible Catalyst Data query brief.", "",
        "## Snapshot", "",
        f"- Run: `{run['run_id']}`",
        f"- Records: {summary['record_count']}",
        f"- Entities: {summary['entity_count']}",
        f"- Indicators: {summary['indicator_count']}",
        f"- Periods: {summary['period_count']}",
        f"- Warnings: {summary['warning_count']} ({summary['blocking_warning_count']} blocking)", "",
        "## Results", "",
        "| Entity | Indicator | Period | Current | Unit | Quality | Review |",
        "|---|---|---:|---:|---|---:|---|",
    ]
    for record in run["records"]:
        lines.append("| {entity} | {indicator} | {period} | {current} | {unit} | {quality} | {review} |".format(
            entity=_get(record, "entity.name"), indicator=_get(record, "indicator.name"), period=_get(record, "period.label"),
            current=_get(record, "measurement.current"), unit=_get(record, "indicator.unit"),
            quality=_get(record, "review_workflow.quality.overall"), review=_get(record, "review_workflow.state"),
        ))
    if run["comparisons"]:
        lines += ["", "## Period comparisons", "", "| Entity | Indicator | From | To | Change | Comparability |", "|---|---|---|---|---:|---|"]
        for row in run["comparisons"]:
            change = "—" if row["percent_change"] is None else f"{row['percent_change']:.2f}%"
            lines.append(f"| {row['entity_name']} | {row['indicator_name']} | {row['from_period']} | {row['to_period']} | {change} | {row['comparability']['status']} |")
    if run["warnings"]:
        lines += ["", "## Warnings", ""]
        for warning in run["warnings"]:
            lines.append(f"- **{warning['severity'].upper()} — {warning['code']}:** {warning['message']}")
    lines += ["", "## Reproducibility", "", f"Definition SHA-256: `{run['definition_sha256']}`", f"Result SHA-256: `{run['result_sha256']}`", ""]
    return "\n".join(lines)


class QueryStudio:
    def __init__(self, repository: CatalystRepository):
        self.repository = repository

    def _ready(self) -> None:
        self.repository.initialize()

    def save(self, definition: Mapping[str, Any], *, name: str | None = None, description: str | None = None, actor: str = "local") -> dict[str, Any]:
        self._ready()
        normalized = normalize_query_definition({**dict(definition), **({"name": name} if name else {}), **({"description": description} if description is not None else {})})
        query_id = _stable_id("query", normalized["name"])
        digest = payload_hash(normalized)
        now = _now()
        with closing(connect(self.repository.path)) as connection, transaction(connection):
            existing = connection.execute("SELECT definition_sha256 FROM saved_queries WHERE query_id=?", (query_id,)).fetchone()
            if existing and existing[0] == digest:
                return self.get_query(query_id, connection=connection)
            version_number = int(connection.execute("SELECT COALESCE(MAX(version_number),0)+1 FROM saved_query_versions WHERE query_id=?", (query_id,)).fetchone()[0])
            connection.execute(
                """INSERT INTO saved_queries(query_id,name,description,definition_json,definition_sha256,created_by,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(query_id) DO UPDATE SET name=excluded.name,description=excluded.description,
                definition_json=excluded.definition_json,definition_sha256=excluded.definition_sha256,updated_at=excluded.updated_at""",
                (query_id, normalized["name"], normalized.get("description"), canonical_json(normalized), digest, actor, now, now),
            )
            connection.execute(
                "INSERT INTO saved_query_versions(query_id,version_number,definition_json,definition_sha256,created_by,created_at) VALUES(?,?,?,?,?,?)",
                (query_id, version_number, canonical_json(normalized), digest, actor, now),
            )
            return self.get_query(query_id, connection=connection)

    def get_query(self, query_id: str, *, connection: sqlite3.Connection | None = None) -> dict[str, Any]:
        owns = connection is None
        connection = connection or connect(self.repository.path)
        try:
            row = connection.execute("SELECT * FROM saved_query_registry WHERE query_id=?", (query_id,)).fetchone()
            if not row:
                raise KeyError(f"saved query not found: {query_id}")
            definition = json.loads(connection.execute("SELECT definition_json FROM saved_queries WHERE query_id=?", (query_id,)).fetchone()[0])
            return {**dict(row), "definition": definition}
        finally:
            if owns:
                connection.close()

    def list_queries(self, *, limit: int = 100) -> list[dict[str, Any]]:
        self._ready()
        with closing(connect(self.repository.path)) as connection:
            return [dict(row) for row in connection.execute("SELECT * FROM saved_query_registry ORDER BY updated_at DESC, name LIMIT ?", (limit,))]

    def run(self, definition_or_query_id: Mapping[str, Any] | str) -> dict[str, Any]:
        self._ready()
        query_id: str | None = None
        version_id: int | None = None
        if isinstance(definition_or_query_id, str):
            query_id = definition_or_query_id
            with closing(connect(self.repository.path)) as connection:
                row = connection.execute("SELECT definition_json FROM saved_queries WHERE query_id=?", (query_id,)).fetchone()
                if not row:
                    raise KeyError(f"saved query not found: {query_id}")
                definition = json.loads(row[0])
                version_id = int(connection.execute("SELECT id FROM saved_query_versions WHERE query_id=? ORDER BY version_number DESC LIMIT 1", (query_id,)).fetchone()[0])
        else:
            definition = normalize_query_definition(definition_or_query_id)
        definition = normalize_query_definition(definition)
        records = apply_query(self.repository.list_records(limit=1_000_000), definition)
        comparisons = comparison_rows(records)
        warnings = query_warnings(records, comparisons)
        summary = query_summary(records, comparisons, warnings)
        definition_sha = payload_hash(definition)
        result_material = [{"record_id": record["record_id"], "sha256": payload_hash(record)} for record in records]
        result_sha = payload_hash({"definition_sha256": definition_sha, "records": result_material, "comparisons": comparisons, "warnings": warnings})
        started = completed = _now()
        run_id = _stable_id("query-run", definition_sha, result_sha, started)
        with closing(connect(self.repository.path)) as connection, transaction(connection):
            connection.execute(
                "INSERT INTO query_runs(run_id,query_id,query_version_id,definition_json,definition_sha256,result_sha256,record_count,warning_count,started_at,completed_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (run_id, query_id, version_id, canonical_json(definition), definition_sha, result_sha, len(records), len(warnings), started, completed),
            )
            for position, record in enumerate(records):
                connection.execute(
                    "INSERT INTO query_run_records(run_id,position,record_id,record_payload_sha256,record_payload_json) VALUES(?,?,?,?,?)",
                    (run_id, position, record["record_id"], payload_hash(record), canonical_json(record)),
                )
            for warning in warnings:
                connection.execute(
                    "INSERT INTO query_run_warnings(run_id,warning_code,severity,record_ids_json,message,created_at) VALUES(?,?,?,?,?,?)",
                    (run_id, warning["code"], warning["severity"], canonical_json(warning["record_ids"]), warning["message"], completed),
                )
        return {"run_id": run_id, "query_id": query_id, "definition": definition, "definition_sha256": definition_sha,
                "result_sha256": result_sha, "started_at": started, "completed_at": completed,
                "records": records, "comparisons": comparisons, "warnings": warnings, "summary": summary}

    def get_run(self, run_id: str) -> dict[str, Any]:
        self._ready()
        with closing(connect(self.repository.path)) as connection:
            run = connection.execute("SELECT * FROM query_runs WHERE run_id=?", (run_id,)).fetchone()
            if not run:
                raise KeyError(f"query run not found: {run_id}")
            records = [json.loads(row[0]) for row in connection.execute("SELECT record_payload_json FROM query_run_records WHERE run_id=? ORDER BY position", (run_id,))]
            warnings = [{"code": row[0], "severity": row[1], "record_ids": json.loads(row[2]), "message": row[3]} for row in connection.execute("SELECT warning_code,severity,record_ids_json,message FROM query_run_warnings WHERE run_id=? ORDER BY id", (run_id,))]
            comparisons = comparison_rows(records)
            return {"run_id": run_id, "query_id": run["query_id"], "definition": json.loads(run["definition_json"]),
                    "definition_sha256": run["definition_sha256"], "result_sha256": run["result_sha256"],
                    "started_at": run["started_at"], "completed_at": run["completed_at"], "records": records,
                    "comparisons": comparisons, "warnings": warnings, "summary": query_summary(records, comparisons, warnings)}

    def list_runs(self, *, query_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        self._ready()
        sql = "SELECT * FROM query_run_summary"; params: list[Any] = []
        if query_id:
            sql += " WHERE query_id=?"; params.append(query_id)
        sql += " ORDER BY completed_at DESC LIMIT ?"; params.append(limit)
        with closing(connect(self.repository.path)) as connection:
            return [dict(row) for row in connection.execute(sql, params)]

    def write_brief(self, run_id: str, destination: str | Path) -> Path:
        path = Path(destination); path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(brief_markdown(self.get_run(run_id)), encoding="utf-8")
        return path

    def export_bundle(self, run_id: str, destination: str | Path, *, bundle_format: str = "zip") -> dict[str, Any]:
        run = self.get_run(run_id)
        files: dict[str, bytes] = {}
        records_payload = {"schema_version": "catalyst-data-export/1.0", "record_count": len(run["records"]), "records": run["records"]}
        files["records.json"] = (json.dumps(records_payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        csv_buffer = io.StringIO(newline="")
        writer = csv.DictWriter(csv_buffer, fieldnames=CSV_FIELDS, extrasaction="ignore"); writer.writeheader()
        for record in run["records"]: writer.writerow(flatten_record(record))
        files["records.csv"] = csv_buffer.getvalue().encode("utf-8")
        files["comparisons.json"] = (json.dumps(run["comparisons"], indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        files["warnings.json"] = (json.dumps(run["warnings"], indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        files["brief.md"] = brief_markdown(run).encode("utf-8")
        files["data-dictionary.json"] = (json.dumps({"schema_version": "catalyst-data-dictionary/1.0", "csv_fields": CSV_FIELDS}, indent=2) + "\n").encode("utf-8")
        files["provenance.json"] = (json.dumps({record["record_id"]: self.repository.provenance(record["record_id"]) for record in run["records"]}, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        files["review.json"] = (json.dumps({record["record_id"]: self.repository.review_history(record["record_id"]) for record in run["records"]}, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        file_hashes = {name: hashlib.sha256(content).hexdigest() for name, content in sorted(files.items())}
        manifest = {
            "schema_version": BUNDLE_SCHEMA_VERSION, "run_id": run_id, "query_id": run.get("query_id"),
            "created_at": run["completed_at"], "definition": run["definition"],
            "definition_sha256": run["definition_sha256"], "result_sha256": run["result_sha256"],
            "record_count": len(run["records"]), "files": file_hashes,
        }
        manifest_bytes = (json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        files["manifest.json"] = manifest_bytes
        manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
        destination = Path(destination)
        if bundle_format == "directory":
            destination.mkdir(parents=True, exist_ok=True)
            for name, content in files.items():
                target = destination / name; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(content)
        elif bundle_format == "zip":
            destination.parent.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
                for name in sorted(files):
                    info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0)); info.compress_type = zipfile.ZIP_DEFLATED; info.external_attr = 0o644 << 16
                    archive.writestr(info, files[name])
        else:
            raise ValueError("bundle format must be zip or directory")
        bundle_id = _stable_id("bundle", run_id, bundle_format, manifest_sha)
        with closing(connect(self.repository.path)) as connection, transaction(connection):
            connection.execute(
                "INSERT OR IGNORE INTO export_bundles(bundle_id,run_id,bundle_format,output_name,manifest_sha256,created_at) VALUES(?,?,?,?,?,?)",
                (bundle_id, run_id, bundle_format, destination.name, manifest_sha, run["completed_at"]),
            )
        return {"bundle_id": bundle_id, "run_id": run_id, "format": bundle_format, "path": str(destination), "manifest_sha256": manifest_sha, "files": file_hashes}
