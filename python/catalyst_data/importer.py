from __future__ import annotations

import csv
import json
import sqlite3
from dataclasses import asdict, dataclass, field
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Iterable, Iterator, Mapping

from .database import connect
from .engine import build_record
from .repository import CatalystRepository


@dataclass
class ImportErrorDetail:
    row_number: int
    message: str
    raw: Any = None


@dataclass
class ImportSummary:
    source: str
    format: str
    dry_run: bool
    atomic: bool
    processed: int = 0
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    rolled_back: bool = False
    import_run_id: int | None = None
    errors: list[ImportErrorDetail] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        return result


class ImportPipelineError(RuntimeError):
    def __init__(self, summary: ImportSummary):
        super().__init__(f"import failed with {summary.failed} row error(s)")
        self.summary = summary


def _split_list(value: Any) -> list[str]:
    if value is None:
        return []
    return [item.strip() for item in str(value).replace(";", "|").split("|") if item.strip()]


def _float_or_none(value: Any) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    return float(value)


def csv_row_to_payload(row: Mapping[str, Any]) -> dict[str, Any]:
    if row.get("record_json"):
        value = json.loads(str(row["record_json"]))
        if not isinstance(value, dict):
            raise ValueError("record_json must contain an object")
        return value
    required = ["entity_name", "indicator_name", "period_label", "current", "source_name", "confidence"]
    missing = [field for field in required if not str(row.get(field, "")).strip()]
    if missing:
        raise ValueError("missing required CSV fields: " + ", ".join(missing))
    evidence_chain = None
    if row.get("evidence_chain_json"):
        evidence_chain = json.loads(str(row["evidence_chain_json"]))
        if not isinstance(evidence_chain, dict):
            raise ValueError("evidence_chain_json must contain an object")
    elif row.get("sources_json"):
        sources = json.loads(str(row["sources_json"]))
        if not isinstance(sources, list):
            raise ValueError("sources_json must contain an array")
        evidence_chain = {"sources": sources}

    payload: dict[str, Any] = {
        "created_at": row.get("created_at") or None,
        "updated_at": row.get("updated_at") or None,
        "record_id": row.get("record_id") or None,
        "entity": {
            "id": row.get("entity_id") or None,
            "name": row["entity_name"],
            "type": row.get("entity_type") or "other",
            "external_ids": ({row["external_id_namespace"]: row["external_id"]}
                             if row.get("external_id_namespace") and row.get("external_id") else {}),
        },
        "indicator": {
            "id": row.get("indicator_id") or None,
            "name": row["indicator_name"],
            "unit": row.get("unit") or "unspecified",
            "direction": row.get("direction") or "neutral",
            "framework": row.get("framework") or None,
            "version": row.get("indicator_version") or "1.0",
        },
        "period": {
            "id": row.get("period_id") or None,
            "label": row["period_label"],
            "start_date": row.get("start_date") or None,
            "end_date": row.get("end_date") or None,
        },
        "values": {"baseline": _float_or_none(row.get("baseline")), "current": float(row["current"])},
        "source": {
            "id": row.get("source_id") or None,
            "name": row["source_name"],
            "type": row.get("source_type") or "unspecified",
            "url": row.get("source_url") or None,
            "publisher": row.get("publisher") or None,
            "license": row.get("license") or None,
            "retrieved_at": row.get("retrieved_at") or None,
            "citation": row.get("citation") or None,
            "checksum": row.get("checksum") or None,
            "access_notes": row.get("access_notes") or None,
        },
        "confidence": {"score": float(row["confidence"]), "basis": row.get("confidence_basis") or None},
        "method": {
            "notes": row.get("method_notes") or None,
            "assumptions": _split_list(row.get("assumptions")),
            "limitations": _split_list(row.get("limitations")),
            "uncertainty": row.get("uncertainty") or None,
            "quality_flags": _split_list(row.get("quality_flags")),
        },
        "reviewer_notes": row.get("reviewer_notes") or "",
        "extensions": {},
    }
    if evidence_chain is not None:
        payload["evidence_chain"] = evidence_chain
    return payload


def iter_input(path: Path, format_name: str = "auto") -> tuple[str, Iterator[tuple[int, Any]]]:
    selected = format_name
    if selected == "auto":
        selected = "csv" if path.suffix.lower() == ".csv" else "json"
    if selected == "json":
        value = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(value, dict) and isinstance(value.get("records"), list):
            records = value["records"]
        elif isinstance(value, list):
            records = value
        elif isinstance(value, dict):
            records = [value]
        else:
            raise ValueError("JSON import must contain an object, an array, or an object with records[]")
        return selected, iter(enumerate(records, start=1))
    if selected == "csv":
        handle = path.open("r", encoding="utf-8-sig", newline="")
        reader = csv.DictReader(handle)
        def iterator() -> Iterator[tuple[int, Any]]:
            try:
                for number, row in enumerate(reader, start=2):
                    yield number, row
            finally:
                handle.close()
        return selected, iterator()
    raise ValueError("format must be auto, json, or csv")


class ImportService:
    def __init__(self, repository: CatalystRepository):
        self.repository = repository

    def run(
        self,
        source: str | Path,
        *,
        format_name: str = "auto",
        dry_run: bool = False,
        atomic: bool = True,
        continue_on_error: bool = False,
    ) -> ImportSummary:
        path = Path(source)
        selected, rows = iter_input(path, format_name)
        source_time = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).replace(microsecond=0)
        summary = ImportSummary(str(path), selected, dry_run, atomic)
        self.repository.initialize()
        connection = connect(self.repository.path)
        run_id: int | None = None
        try:
            connection.execute("BEGIN IMMEDIATE")
            if not dry_run:
                cursor = connection.execute(
                    "INSERT INTO import_runs(source_name, source_format, dry_run, atomic_mode, status) VALUES (?, ?, ?, ?, 'running')",
                    (str(path), selected, int(dry_run), int(atomic)),
                )
                run_id = int(cursor.lastrowid)
                summary.import_run_id = run_id
            for row_number, raw in rows:
                summary.processed += 1
                savepoint = f"row_{row_number}"
                if continue_on_error:
                    connection.execute(f"SAVEPOINT {savepoint}")
                try:
                    payload = csv_row_to_payload(raw) if selected == "csv" else raw
                    if not isinstance(payload, Mapping):
                        raise ValueError("record must be an object")
                    record = build_record(payload, now=source_time, producer_component="import-service")
                    action = self.repository.upsert_record(
                        record, connection=connection, import_run_id=run_id, row_number=row_number
                    )
                    setattr(summary, action, getattr(summary, action) + 1)
                    if continue_on_error:
                        connection.execute(f"RELEASE SAVEPOINT {savepoint}")
                except Exception as exc:
                    summary.failed += 1
                    detail = ImportErrorDetail(row_number, str(exc), raw)
                    summary.errors.append(detail)
                    if continue_on_error:
                        connection.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                        connection.execute(f"RELEASE SAVEPOINT {savepoint}")
                        if run_id is not None:
                            connection.execute(
                                "INSERT INTO import_row_errors(import_run_id, row_number, error_message, raw_payload) VALUES (?, ?, ?, ?)",
                                (run_id, row_number, str(exc), json.dumps(raw, ensure_ascii=False, default=str)),
                            )
                        continue
                    raise
            if summary.failed and atomic:
                raise ImportPipelineError(summary)
            if dry_run:
                connection.rollback()
                summary.rolled_back = True
            else:
                connection.execute(
                    """
                    UPDATE import_runs SET status=?, finished_at=datetime('now'), processed=?, inserted=?, updated=?, skipped=?, failed=?
                    WHERE id=?
                    """,
                    ("completed_with_errors" if summary.failed else "completed", summary.processed, summary.inserted,
                     summary.updated, summary.skipped, summary.failed, run_id),
                )
                connection.commit()
            return summary
        except Exception as exc:
            connection.rollback()
            summary.rolled_back = True
            if not summary.errors:
                summary.failed += 1
                summary.errors.append(ImportErrorDetail(summary.processed or 1, str(exc)))
            if not dry_run:
                with connect(self.repository.path) as error_connection:
                    cursor = error_connection.execute(
                        """
                        INSERT INTO import_runs(source_name, source_format, dry_run, atomic_mode, status, finished_at,
                            processed, inserted, updated, skipped, failed)
                        VALUES (?, ?, ?, ?, 'failed', datetime('now'), ?, ?, ?, ?, ?)
                        """,
                        (str(path), selected, int(dry_run), int(atomic), summary.processed, summary.inserted,
                         summary.updated, summary.skipped, summary.failed),
                    )
                    summary.import_run_id = int(cursor.lastrowid)
                    for detail in summary.errors:
                        error_connection.execute(
                            "INSERT INTO import_row_errors(import_run_id, row_number, error_message, raw_payload) VALUES (?, ?, ?, ?)",
                            (summary.import_run_id, detail.row_number, detail.message,
                             json.dumps(detail.raw, ensure_ascii=False, default=str) if detail.raw is not None else None),
                        )
                    error_connection.commit()
            if atomic or not continue_on_error:
                raise ImportPipelineError(summary) from exc
            return summary
        finally:
            connection.close()
