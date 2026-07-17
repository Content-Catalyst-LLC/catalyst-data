from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Mapping

from .database import DatabaseHealth, connect, transaction
from .engine import validate_record_semantics
from .migrations import MigrationManager, discover_migrations
from .provenance import normalize_evidence_chain, source_digest, source_payload
from .validation import validate_record


def canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def payload_hash(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _event_id(record_id: str, event_type: str, occurred_at: str, digest: str, source_id: int | None = None) -> str:
    value = f"{record_id}|{event_type}|{occurred_at}|{digest}|{source_id or ''}"
    return "event:" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


class RepositoryError(RuntimeError):
    pass


class CatalystRepository:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def initialize(self, *, target: int | None = None) -> list[int]:
        with closing(connect(self.path)) as connection:
            manager = MigrationManager(connection)
            applied = manager.migrate(target)
            current = manager.current_version
        if current >= 3:
            self._backfill_evidence_storage()
        return applied

    def _backfill_evidence_storage(self) -> int:
        """Populate v1.3 evidence tables for records created under v1.2.

        Migration 003 creates the append-only structures. This application-level
        backfill then replays stored canonical records through the current
        repository writer so source digests, revisions, events, links, and gaps
        are calculated by the same code used for new imports.
        """
        with closing(connect(self.path)) as connection:
            rows = connection.execute(
                """
                SELECT dr.payload_json
                FROM data_records dr
                JOIN measurements m ON m.id = dr.measurement_id
                WHERE NOT EXISTS (
                    SELECT 1 FROM measurement_sources ms WHERE ms.measurement_id = m.id
                )
                OR NOT EXISTS (
                    SELECT 1 FROM record_revisions rr WHERE rr.record_id = dr.record_id
                )
                ORDER BY dr.record_id
                """
            ).fetchall()
        count = 0
        for row in rows:
            record = json.loads(row[0])
            if "evidence_chain" not in record:
                record["evidence_chain"] = normalize_evidence_chain(
                    record["source"],
                    None,
                    method=record["method"],
                    confidence=record["confidence"],
                    occurred_at=record["updated_at"],
                )
            self.upsert_record(record, _force_evidence_rebuild=True)
            count += 1
        return count

    def migrate(self, *, target: int | None = None) -> list[int]:
        return self.initialize(target=target)

    def rollback(self, steps: int = 1) -> list[int]:
        with closing(connect(self.path)) as connection:
            return MigrationManager(connection).rollback(steps)

    def migration_status(self) -> list[dict[str, object]]:
        with closing(connect(self.path)) as connection:
            return MigrationManager(connection).status()

    def health(self) -> DatabaseHealth:
        exists = self.path.exists()
        latest = discover_migrations()[-1].version
        if not exists:
            return DatabaseHealth(str(self.path), False, "missing", False, 0, latest, None, 0, 0)
        with closing(connect(self.path)) as connection:
            manager = MigrationManager(connection)
            integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
            foreign_keys = bool(connection.execute("PRAGMA foreign_keys").fetchone()[0])
            repository_id = None; record_count = 0; import_run_count = 0
            if manager.current_version >= 2:
                row = connection.execute("SELECT repository_id FROM repository_metadata WHERE id = 1").fetchone()
                repository_id = str(row[0]) if row else None
                record_count = int(connection.execute("SELECT COUNT(*) FROM data_records").fetchone()[0])
                import_run_count = int(connection.execute("SELECT COUNT(*) FROM import_runs").fetchone()[0])
            return DatabaseHealth(str(self.path), exists, integrity, foreign_keys, manager.current_version, manager.latest_version, repository_id, record_count, import_run_count)

    @staticmethod
    def _require_current(connection: sqlite3.Connection) -> MigrationManager:
        manager = MigrationManager(connection)
        if manager.current_version != manager.latest_version:
            raise RepositoryError(f"repository schema is at migration {manager.current_version}; run migrate to reach {manager.latest_version}")
        return manager

    @staticmethod
    def _upsert_entity(connection: sqlite3.Connection, record: Mapping[str, Any]) -> int:
        entity = record["entity"]
        external_ids = json.dumps(entity.get("external_ids", {}), sort_keys=True)
        connection.execute("""
            INSERT INTO entities(canonical_id, entity_type, name, external_id, external_ids_json)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(canonical_id) DO UPDATE SET entity_type=excluded.entity_type, name=excluded.name,
                external_id=excluded.external_id, external_ids_json=excluded.external_ids_json
        """, (entity["id"], entity["type"], entity["name"], next(iter(entity.get("external_ids", {}).values()), None), external_ids))
        return int(connection.execute("SELECT id FROM entities WHERE canonical_id = ?", (entity["id"],)).fetchone()[0])

    @staticmethod
    def _upsert_indicator(connection: sqlite3.Connection, record: Mapping[str, Any]) -> int:
        indicator = record["indicator"]
        connection.execute("""
            INSERT INTO indicators(canonical_id, name, framework, unit, direction, version)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(canonical_id) DO UPDATE SET name=excluded.name, framework=excluded.framework,
                unit=excluded.unit, direction=excluded.direction, version=excluded.version
        """, (indicator["id"], indicator["name"], indicator.get("framework"), indicator.get("unit"), indicator["direction"], indicator["version"]))
        return int(connection.execute("SELECT id FROM indicators WHERE canonical_id = ?", (indicator["id"],)).fetchone()[0])

    @staticmethod
    def _upsert_period(connection: sqlite3.Connection, record: Mapping[str, Any]) -> int:
        period = record["period"]; label = period["label"]
        period_type = "year" if len(label) == 4 and label.isdigit() else ("quarter" if "Q" in label.upper() else "custom")
        connection.execute("""
            INSERT INTO periods(canonical_id, label, period_type, start_date, end_date)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(canonical_id) DO UPDATE SET label=excluded.label, period_type=excluded.period_type,
                start_date=excluded.start_date, end_date=excluded.end_date
        """, (period["id"], label, period_type, period.get("start_date"), period.get("end_date")))
        return int(connection.execute("SELECT id FROM periods WHERE canonical_id = ?", (period["id"],)).fetchone()[0])

    @staticmethod
    def _upsert_source(connection: sqlite3.Connection, source: Mapping[str, Any]) -> tuple[int, int, bool]:
        normalized = source_payload(source); digest = source_digest(normalized); payload_json = canonical_json(normalized)
        connection.execute("""
            INSERT INTO sources(canonical_id, name, source_type, url, publisher, license, retrieved_at, citation, checksum, access_notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(canonical_id) DO UPDATE SET name=excluded.name, source_type=excluded.source_type,
                url=excluded.url, publisher=excluded.publisher, license=excluded.license,
                retrieved_at=excluded.retrieved_at, citation=excluded.citation,
                checksum=excluded.checksum, access_notes=excluded.access_notes
        """, (normalized["id"], normalized["name"], normalized["type"], normalized.get("url"), normalized.get("publisher"), normalized.get("license"), normalized.get("retrieved_at"), normalized.get("citation"), normalized.get("checksum"), normalized.get("access_notes")))
        source_id = int(connection.execute("SELECT id FROM sources WHERE canonical_id = ?", (normalized["id"],)).fetchone()[0])
        row = connection.execute("SELECT id, version_number FROM source_versions WHERE source_id=? AND payload_sha256=?", (source_id, digest)).fetchone()
        created = False
        if row:
            version_id, version_number = int(row[0]), int(row[1])
        else:
            version_number = int(connection.execute("SELECT COALESCE(MAX(version_number), 0) + 1 FROM source_versions WHERE source_id=?", (source_id,)).fetchone()[0])
            cursor = connection.execute("INSERT INTO source_versions(source_id, version_number, payload_json, payload_sha256) VALUES (?, ?, ?, ?)", (source_id, version_number, payload_json, digest))
            version_id = int(cursor.lastrowid); created = True
        if normalized.get("checksum") or normalized.get("retrieved_at"):
            snapshot_key = f"{normalized['id']}|{version_number}|{normalized.get('retrieved_at') or ''}|{normalized.get('checksum') or ''}"
            snapshot_id = "snapshot:" + hashlib.sha256(snapshot_key.encode("utf-8")).hexdigest()[:24]
            connection.execute("""
                INSERT OR IGNORE INTO source_snapshots(snapshot_id, source_version_id, retrieved_at, content_sha256, storage_uri, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (snapshot_id, version_id, normalized.get("retrieved_at"), normalized.get("checksum"), normalized.get("url"), json.dumps({"publisher": normalized.get("publisher"), "license": normalized.get("license")}, sort_keys=True)))
        return source_id, version_id, created

    @staticmethod
    def _append_event(connection: sqlite3.Connection, *, record_id: str, measurement_id: int, event_type: str, actor: str, occurred_at: str, digest: str, details: Mapping[str, Any], source_id: int | None = None) -> None:
        previous = connection.execute("SELECT event_id FROM provenance_events WHERE record_id=? ORDER BY id DESC LIMIT 1", (record_id,)).fetchone()
        event_id = _event_id(record_id, event_type, occurred_at, digest + canonical_json(details), source_id)
        connection.execute("""
            INSERT OR IGNORE INTO provenance_events(event_id, record_id, measurement_id, source_id, event_type, actor, details_json, previous_event_id, occurred_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (event_id, record_id, measurement_id, source_id, event_type, actor, canonical_json(details), previous[0] if previous else None, occurred_at))

    def upsert_record(self, record: Mapping[str, Any], *, connection: sqlite3.Connection | None = None, import_run_id: int | None = None, row_number: int | None = None, _force_evidence_rebuild: bool = False) -> str:
        validate_record(record); validate_record_semantics(record)
        own_connection = connection is None; conn = connection or connect(self.path)
        try:
            self._require_current(conn)
            digest = payload_hash(record)
            existing = conn.execute("SELECT payload_sha256 FROM data_records WHERE record_id=?", (record["record_id"],)).fetchone()
            if existing and existing[0] == digest and not _force_evidence_rebuild:
                if import_run_id is not None:
                    conn.execute("INSERT INTO import_records(import_run_id,row_number,record_id,action,payload_sha256) VALUES (?,?,?,?,?)", (import_run_id, row_number, record["record_id"], "skipped", digest))
                if own_connection: conn.commit()
                return "skipped"

            with transaction(conn):
                entity_id = self._upsert_entity(conn, record); indicator_id = self._upsert_indicator(conn, record); period_id = self._upsert_period(conn, record)
                chain = record.get("evidence_chain") or {"sources": [{"role": "primary", "source": record["source"], "locator": {}, "supports": ["measurement.current"], "notes": None}], "relationships": [], "transformations": [], "gaps": []}
                source_rows: dict[str, tuple[int, int, bool]] = {}
                for link in chain["sources"]:
                    source = link["source"]
                    source_rows[source["id"]] = self._upsert_source(conn, source)
                primary_source_id = source_rows[record["source"]["id"]][0]
                measurement = record["measurement"]; method = record["method"]; review = record["review"]
                conn.execute("""
                    INSERT INTO measurements(canonical_id,entity_id,indicator_id,period_id,source_id,value,baseline_value,confidence,method,assumptions,limitations,uncertainty,quality_flags,reviewer_notes,updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(canonical_id) DO UPDATE SET entity_id=excluded.entity_id,indicator_id=excluded.indicator_id,
                        period_id=excluded.period_id,source_id=excluded.source_id,value=excluded.value,baseline_value=excluded.baseline_value,
                        confidence=excluded.confidence,method=excluded.method,assumptions=excluded.assumptions,limitations=excluded.limitations,
                        uncertainty=excluded.uncertainty,quality_flags=excluded.quality_flags,reviewer_notes=excluded.reviewer_notes,updated_at=excluded.updated_at
                """, (record["record_id"], entity_id, indicator_id, period_id, primary_source_id, measurement["current"], measurement.get("baseline"), record["confidence"]["score"], method.get("notes"), json.dumps(method.get("assumptions", []), ensure_ascii=False), json.dumps(method.get("limitations", []), ensure_ascii=False), method.get("uncertainty"), json.dumps(method.get("quality_flags", []), ensure_ascii=False), review.get("reviewer_notes"), record["updated_at"]))
                measurement_id = int(conn.execute("SELECT id FROM measurements WHERE canonical_id=?", (record["record_id"],)).fetchone()[0])
                action = "updated" if existing else "inserted"; payload_json = canonical_json(record)
                conn.execute("""
                    INSERT INTO data_records(record_id,schema_version,record_type,payload_json,payload_sha256,entity_id,indicator_id,period_id,source_id,measurement_id,created_at,updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(record_id) DO UPDATE SET schema_version=excluded.schema_version,record_type=excluded.record_type,
                        payload_json=excluded.payload_json,payload_sha256=excluded.payload_sha256,entity_id=excluded.entity_id,
                        indicator_id=excluded.indicator_id,period_id=excluded.period_id,source_id=excluded.source_id,
                        measurement_id=excluded.measurement_id,updated_at=excluded.updated_at
                """, (record["record_id"], record["schema_version"], record["record_type"], payload_json, digest, entity_id, indicator_id, period_id, primary_source_id, measurement_id, record["created_at"], record["updated_at"]))

                revision_number = int(conn.execute("SELECT COALESCE(MAX(revision_number),0)+1 FROM record_revisions WHERE record_id=?", (record["record_id"],)).fetchone()[0])
                conn.execute("INSERT INTO record_revisions(record_id,revision_number,action,payload_json,payload_sha256,import_run_id) VALUES (?,?,?,?,?,?)", (record["record_id"], revision_number, action, payload_json, digest, import_run_id))

                conn.execute("DELETE FROM measurement_sources WHERE measurement_id=?", (measurement_id,))
                for position, link in enumerate(chain["sources"]):
                    source = link["source"]; source_id, version_id, version_created = source_rows[source["id"]]
                    conn.execute("""
                        INSERT INTO measurement_sources(measurement_id,source_id,source_version_id,role,locator_json,supports_json,notes,position)
                        VALUES (?,?,?,?,?,?,?,?)
                    """, (measurement_id, source_id, version_id, link["role"], canonical_json(link["locator"]), json.dumps(link["supports"], ensure_ascii=False), link.get("notes"), position))
                    if version_created:
                        self._append_event(conn, record_id=record["record_id"], measurement_id=measurement_id, source_id=source_id, event_type="source_versioned", actor=record["producer"]["component"], occurred_at=record["updated_at"], digest=digest, details={"source_id": source["id"], "source_version_id": version_id})
                    self._append_event(conn, record_id=record["record_id"], measurement_id=measurement_id, source_id=source_id, event_type="source_linked", actor=record["producer"]["component"], occurred_at=record["updated_at"], digest=digest, details={"source_id": source["id"], "role": link["role"], "supports": link["supports"]})

                for relationship in chain["relationships"]:
                    subject = source_rows[relationship["subject_source_id"]][0]; obj = source_rows[relationship["object_source_id"]][0]
                    conn.execute("INSERT OR IGNORE INTO source_relationships(subject_source_id,predicate,object_source_id,notes) VALUES (?,?,?,?)", (subject, relationship["predicate"], obj, relationship.get("notes")))

                conn.execute("UPDATE evidence_gaps SET resolved_at=? WHERE measurement_id=? AND resolved_at IS NULL", (record["updated_at"], measurement_id))
                for gap in chain["gaps"]:
                    conn.execute("INSERT INTO evidence_gaps(measurement_id,gap_code,severity,description) VALUES (?,?,?,?)", (measurement_id, gap["code"], gap["severity"], gap["description"]))

                event_type = "record_updated" if existing else "record_created"
                self._append_event(conn, record_id=record["record_id"], measurement_id=measurement_id, event_type=event_type, actor=record["producer"]["component"], occurred_at=record["updated_at"], digest=digest, details={"revision": revision_number, "payload_sha256": digest})
                for transformation in chain["transformations"]:
                    self._append_event(conn, record_id=record["record_id"], measurement_id=measurement_id, event_type="transformed", actor=record["producer"]["component"], occurred_at=transformation.get("occurred_at") or record["updated_at"], digest=digest, details=transformation)
                if import_run_id is not None:
                    conn.execute("INSERT INTO import_records(import_run_id,row_number,record_id,action,payload_sha256) VALUES (?,?,?,?,?)", (import_run_id, row_number, record["record_id"], action, digest))
                    self._append_event(conn, record_id=record["record_id"], measurement_id=measurement_id, event_type="imported", actor="import-service", occurred_at=record["updated_at"], digest=digest, details={"import_run_id": import_run_id, "row_number": row_number})
            return action
        finally:
            if own_connection: conn.close()

    def add_source_snapshot(self, source_canonical_id: str, *, retrieved_at: str, content_sha256: str | None = None, storage_uri: str | None = None, media_type: str | None = None, byte_size: int | None = None, metadata: Mapping[str, Any] | None = None) -> str:
        with closing(connect(self.path)) as connection, transaction(connection):
            self._require_current(connection)
            row = connection.execute("""
                SELECT sv.id, sv.version_number, s.id AS source_row_id FROM source_versions sv JOIN sources s ON s.id=sv.source_id
                WHERE s.canonical_id=? ORDER BY sv.version_number DESC LIMIT 1
            """, (source_canonical_id,)).fetchone()
            if not row: raise RepositoryError(f"source not found: {source_canonical_id}")
            key = f"{source_canonical_id}|{row['version_number']}|{retrieved_at}|{content_sha256 or ''}|{storage_uri or ''}"
            snapshot_id = "snapshot:" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
            cursor = connection.execute("INSERT OR IGNORE INTO source_snapshots(snapshot_id,source_version_id,retrieved_at,content_sha256,storage_uri,media_type,byte_size,metadata_json) VALUES (?,?,?,?,?,?,?,?)", (snapshot_id, row["id"], retrieved_at, content_sha256, storage_uri, media_type, byte_size, canonical_json(metadata or {})))
            if cursor.rowcount:
                linked = connection.execute("""
                    SELECT DISTINCT m.id AS measurement_id, m.canonical_id AS record_id, dr.payload_sha256
                    FROM measurement_sources ms JOIN measurements m ON m.id=ms.measurement_id
                    JOIN data_records dr ON dr.record_id=m.canonical_id WHERE ms.source_id=?
                """, (row["source_row_id"],)).fetchall()
                for item in linked:
                    self._append_event(connection, record_id=item["record_id"], measurement_id=item["measurement_id"], source_id=row["source_row_id"], event_type="source_snapshot_added", actor="repository-service", occurred_at=retrieved_at, digest=item["payload_sha256"], details={"snapshot_id": snapshot_id, "source_id": source_canonical_id})
            return snapshot_id

    def get_record(self, record_id: str) -> dict[str, Any] | None:
        with closing(connect(self.path)) as connection:
            self._require_current(connection)
            row = connection.execute("SELECT payload_json FROM data_records WHERE record_id=?", (record_id,)).fetchone()
            return json.loads(row[0]) if row else None

    def list_records(self, *, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        with closing(connect(self.path)) as connection:
            self._require_current(connection)
            return [json.loads(row[0]) for row in connection.execute("SELECT payload_json FROM data_records ORDER BY updated_at DESC,record_id LIMIT ? OFFSET ?", (limit, offset))]

    def review_queue(self, *, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        with closing(connect(self.path)) as connection:
            self._require_current(connection); sql="SELECT * FROM measurement_review"; params=[]
            if status: sql += " WHERE review_status=?"; params.append(status)
            sql += " ORDER BY confidence ASC,measurement_id LIMIT ?"; params.append(limit)
            return [dict(row) for row in connection.execute(sql, params)]

    def source_history(self, source_id: str | None = None, *, limit: int = 100) -> list[dict[str, Any]]:
        with closing(connect(self.path)) as connection:
            self._require_current(connection)
            sql="""SELECT s.canonical_id AS source_id,s.name,sv.version_number,sv.payload_sha256,sv.payload_json,sv.created_at,
                (SELECT COUNT(*) FROM source_snapshots ss WHERE ss.source_version_id=sv.id) AS snapshot_count
                FROM source_versions sv JOIN sources s ON s.id=sv.source_id"""; params=[]
            if source_id: sql += " WHERE s.canonical_id=?"; params.append(source_id)
            sql += " ORDER BY s.canonical_id,sv.version_number DESC LIMIT ?"; params.append(limit)
            rows=[]
            for row in connection.execute(sql, params):
                item=dict(row); item["payload"]=json.loads(item.pop("payload_json")); rows.append(item)
            return rows

    def provenance(self, record_id: str, *, limit: int = 200) -> list[dict[str, Any]]:
        with closing(connect(self.path)) as connection:
            self._require_current(connection)
            rows=[]
            for row in connection.execute("SELECT event_id,event_type,actor,details_json,previous_event_id,occurred_at,created_at FROM provenance_events WHERE record_id=? ORDER BY id LIMIT ?", (record_id, limit)):
                item=dict(row); item["details"]=json.loads(item.pop("details_json")); rows.append(item)
            return rows

    def evidence(self, record_id: str) -> dict[str, Any] | None:
        with closing(connect(self.path)) as connection:
            self._require_current(connection)
            record = self.get_record(record_id)
            if record is None: return None
            summary = connection.execute("SELECT * FROM evidence_chain_summary WHERE record_id=?", (record_id,)).fetchone()
            gaps = [dict(row) for row in connection.execute("SELECT gap_code,severity,description,detected_at FROM open_evidence_gaps WHERE record_id=? ORDER BY severity DESC,gap_code", (record_id,))]
            revisions=[]
            for row in connection.execute("SELECT revision_number,action,payload_sha256,created_at FROM record_revisions WHERE record_id=? ORDER BY revision_number", (record_id,)):
                revisions.append(dict(row))
            return {"record_id": record_id, "chain": record.get("evidence_chain"), "summary": dict(summary) if summary else {}, "open_gaps": gaps, "revisions": revisions, "provenance": self.provenance(record_id)}

    def stats(self) -> dict[str, int]:
        with closing(connect(self.path)) as connection:
            self._require_current(connection)
            counts={"records":"data_records","entities":"entities","indicators":"indicators","sources":"sources","measurements":"measurements","import_runs":"import_runs","source_versions":"source_versions","source_snapshots":"source_snapshots","evidence_links":"measurement_sources","record_revisions":"record_revisions","provenance_events":"provenance_events","open_evidence_gaps":"open_evidence_gaps"}
            return {name:int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]) for name,table in counts.items()}
