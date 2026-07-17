from __future__ import annotations

import hashlib
import json
import sqlite3
from copy import deepcopy
from contextlib import closing
from pathlib import Path
from typing import Any, Mapping

from .database import DatabaseHealth, connect, transaction
from .engine import validate_record_semantics
from .migrations import MigrationManager, discover_migrations
from .provenance import normalize_evidence_chain, source_digest, source_payload
from .governance import (
    compare_governance,
    convert_value as convert_unit_value,
    governance_digest,
    normalize_indicator_governance,
)
from .validation import validate_record
from .lineage import normalize_observation_lineage, lineage_completeness
from .review import append_comment, append_decision, derive_quality, normalize_review_workflow, publication_gate, quality_overall, review_digest


def canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def payload_hash(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _event_id(record_id: str, event_type: str, occurred_at: str, digest: str, source_id: int | None = None) -> str:
    value = f"{record_id}|{event_type}|{occurred_at}|{digest}|{source_id or ''}"
    return "event:" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


def _governance_event_id(indicator_id: str, event_type: str, occurred_at: str, digest: str) -> str:
    value = f"{indicator_id}|{event_type}|{occurred_at}|{digest}"
    return "governance-event:" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


def _lineage_event_id(record_id: str, event_type: str, occurred_at: str, digest: str) -> str:
    value = f"{record_id}|{event_type}|{occurred_at}|{digest}"
    return "lineage-event:" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


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
        latest = discover_migrations()[-1].version
        if current == latest and current >= 3:
            self._backfill_evidence_storage()
        if current == latest and current >= 4:
            self._backfill_governance_storage()
        if current == latest and current >= 5:
            self._backfill_observation_storage()
        if current == latest and current >= 6:
            self._backfill_review_storage()
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


    def _backfill_governance_storage(self) -> int:
        """Enrich v1.3 records and populate the governed indicator registry."""
        with closing(connect(self.path)) as connection:
            rows = connection.execute(
                """
                SELECT dr.payload_json
                FROM data_records dr
                JOIN indicators i ON i.id = dr.indicator_id
                WHERE json_extract(dr.payload_json, '$.indicator_governance') IS NULL
                   OR NOT EXISTS (SELECT 1 FROM indicator_versions iv WHERE iv.indicator_id = i.id)
                ORDER BY dr.record_id
                """
            ).fetchall()
        count = 0
        for row in rows:
            record = json.loads(row[0])
            if "indicator_governance" not in record:
                record["indicator_governance"] = normalize_indicator_governance(
                    record["indicator"], record["method"], None
                )
            self.upsert_record(record, _force_governance_rebuild=True)
            count += 1
        return count

    def _backfill_observation_storage(self) -> int:
        """Enrich v1.4 records and persist question-to-observation lineage."""
        with closing(connect(self.path)) as connection:
            rows = connection.execute(
                """
                SELECT dr.payload_json
                FROM data_records dr
                JOIN measurements m ON m.id = dr.measurement_id
                WHERE json_extract(dr.payload_json, '$.observation_lineage') IS NULL
                   OR NOT EXISTS (SELECT 1 FROM measurement_observations mo WHERE mo.measurement_id = m.id)
                ORDER BY dr.record_id
                """
            ).fetchall()
        count = 0
        for row in rows:
            record = json.loads(row[0])
            if "observation_lineage" not in record:
                record["observation_lineage"] = normalize_observation_lineage(record, None)
            self.upsert_record(record, _force_lineage_rebuild=True)
            count += 1
        return count


    def _backfill_review_storage(self) -> int:
        """Enrich v1.5 records and populate review, quality, and revision workflow tables."""
        with closing(connect(self.path)) as connection:
            rows = connection.execute(
                """
                SELECT dr.payload_json
                FROM data_records dr
                WHERE json_extract(dr.payload_json, '$.review_workflow') IS NULL
                   OR NOT EXISTS (SELECT 1 FROM review_cases rc WHERE rc.record_id=dr.record_id)
                ORDER BY dr.record_id
                """
            ).fetchall()
        count = 0
        for row in rows:
            record = json.loads(row[0])
            if "review_workflow" not in record:
                record["review_workflow"] = normalize_review_workflow(record, None)
            self.upsert_record(record, _force_review_rebuild=True)
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
        governance = record["indicator_governance"]
        connection.execute("""
            INSERT INTO indicators(canonical_id, code, name, framework, unit, direction, version, namespace, domain, custodian, status, definition, frequency, aggregation, disaggregation_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(canonical_id) DO UPDATE SET code=excluded.code, name=excluded.name, framework=excluded.framework,
                unit=excluded.unit, direction=excluded.direction, version=excluded.version, namespace=excluded.namespace,
                domain=excluded.domain, custodian=excluded.custodian, status=excluded.status, definition=excluded.definition,
                frequency=excluded.frequency, aggregation=excluded.aggregation, disaggregation_json=excluded.disaggregation_json
        """, (
            indicator["id"], governance["code"], indicator["name"], indicator.get("framework"),
            indicator.get("unit"), indicator["direction"], indicator["version"], governance["namespace"],
            governance["domain"], governance["custodian"], governance["status"], governance["definition"],
            governance["frequency"], governance["aggregation"], json.dumps(governance["disaggregation_dimensions"], ensure_ascii=False),
        ))
        return int(connection.execute("SELECT id FROM indicators WHERE canonical_id = ?", (indicator["id"],)).fetchone()[0])

    @staticmethod
    def _append_governance_event(
        connection: sqlite3.Connection, *, indicator_id: int, indicator_canonical_id: str,
        event_type: str, actor: str, occurred_at: str, digest: str, details: Mapping[str, Any],
        indicator_version_id: int | None = None, methodology_version_id: int | None = None, unit_id: int | None = None,
    ) -> None:
        event_id = _governance_event_id(indicator_canonical_id, event_type, occurred_at, digest + canonical_json(details))
        connection.execute(
            """INSERT OR IGNORE INTO governance_events(
                event_id, indicator_id, indicator_version_id, methodology_version_id, unit_id, event_type, actor, details_json, occurred_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (event_id, indicator_id, indicator_version_id, methodology_version_id, unit_id, event_type, actor, canonical_json(details), occurred_at),
        )

    @classmethod
    def _persist_indicator_governance(
        cls, connection: sqlite3.Connection, record: Mapping[str, Any], indicator_id: int
    ) -> tuple[int, int, int]:
        governance = record["indicator_governance"]
        indicator = record["indicator"]
        digest = governance_digest(governance)
        actor = record["producer"]["component"]
        occurred_at = record["updated_at"]

        unit = governance["unit"]
        existing_unit = connection.execute("SELECT id FROM unit_definitions WHERE canonical_id=?", (unit["id"],)).fetchone()
        connection.execute("""
            INSERT INTO unit_definitions(canonical_id,symbol,name,dimension,canonical_unit_id,conversion_factor,conversion_offset,updated_at)
            VALUES (?,?,?,?,?,?,?,?)
            ON CONFLICT(canonical_id) DO UPDATE SET symbol=excluded.symbol,name=excluded.name,dimension=excluded.dimension,
                canonical_unit_id=excluded.canonical_unit_id,conversion_factor=excluded.conversion_factor,
                conversion_offset=excluded.conversion_offset,updated_at=excluded.updated_at
        """, (unit["id"], unit["symbol"], unit["name"], unit["dimension"], unit["canonical_unit_id"], unit["conversion_factor"], unit["conversion_offset"], occurred_at))
        unit_id = int(connection.execute("SELECT id FROM unit_definitions WHERE canonical_id=?", (unit["id"],)).fetchone()[0])
        if existing_unit is None:
            cls._append_governance_event(connection, indicator_id=indicator_id, indicator_canonical_id=indicator["id"], event_type="unit_registered", actor=actor, occurred_at=occurred_at, digest=digest, details={"unit_id": unit["id"]}, unit_id=unit_id)

        version_row = connection.execute("SELECT id FROM indicator_versions WHERE indicator_id=? AND payload_sha256=?", (indicator_id, digest)).fetchone()
        version_created = version_row is None
        if version_row is None:
            revision = int(connection.execute("SELECT COALESCE(MAX(revision_number),0)+1 FROM indicator_versions WHERE indicator_id=? AND version=?", (indicator_id, indicator["version"])).fetchone()[0])
            cursor = connection.execute("""
                INSERT INTO indicator_versions(indicator_id,version,revision_number,status,payload_json,payload_sha256,effective_from)
                VALUES (?,?,?,?,?,?,?)
            """, (indicator_id, indicator["version"], revision, governance["status"], canonical_json(governance), digest, occurred_at))
            indicator_version_id = int(cursor.lastrowid)
        else:
            indicator_version_id = int(version_row[0])

        methodology = governance["methodology"]
        connection.execute("""
            INSERT INTO methodologies(canonical_id,title,current_status,updated_at) VALUES (?,?,?,?)
            ON CONFLICT(canonical_id) DO UPDATE SET title=excluded.title,current_status=excluded.current_status,updated_at=excluded.updated_at
        """, (methodology["id"], methodology["title"], methodology["status"], occurred_at))
        methodology_id = int(connection.execute("SELECT id FROM methodologies WHERE canonical_id=?", (methodology["id"],)).fetchone()[0])
        methodology_digest = hashlib.sha256(canonical_json(methodology).encode("utf-8")).hexdigest()
        methodology_row = connection.execute("SELECT id FROM methodology_versions WHERE methodology_id=? AND payload_sha256=?", (methodology_id, methodology_digest)).fetchone()
        methodology_created = methodology_row is None
        if methodology_row is None:
            revision = int(connection.execute("SELECT COALESCE(MAX(revision_number),0)+1 FROM methodology_versions WHERE methodology_id=? AND version=?", (methodology_id, methodology["version"])).fetchone()[0])
            cursor = connection.execute("""
                INSERT INTO methodology_versions(methodology_id,version,revision_number,status,payload_json,payload_sha256,approved_by,approved_at)
                VALUES (?,?,?,?,?,?,?,?)
            """, (methodology_id, methodology["version"], revision, methodology["status"], canonical_json(methodology), methodology_digest, methodology.get("approved_by"), methodology.get("approved_at")))
            methodology_version_id = int(cursor.lastrowid)
        else:
            methodology_version_id = int(methodology_row[0])

        connection.execute("INSERT OR IGNORE INTO indicator_unit_assignments(indicator_version_id,unit_id,role) VALUES (?,?,'reporting')", (indicator_version_id, unit_id))
        connection.execute("INSERT OR IGNORE INTO indicator_methodologies(indicator_version_id,methodology_version_id,role) VALUES (?,?,'primary')", (indicator_version_id, methodology_version_id))
        for alias in governance["aliases"]:
            connection.execute("INSERT OR IGNORE INTO indicator_aliases(indicator_id,alias) VALUES (?,?)", (indicator_id, alias))
        for mapping in governance["framework_mappings"]:
            cursor = connection.execute("""INSERT OR IGNORE INTO framework_mappings(indicator_version_id,framework,mapping_code,relationship,notes) VALUES (?,?,?,?,?)""", (indicator_version_id, mapping["framework"], mapping["code"], mapping["relationship"], mapping.get("notes")))
            if cursor.rowcount:
                cls._append_governance_event(connection, indicator_id=indicator_id, indicator_canonical_id=indicator["id"], event_type="framework_mapped", actor=actor, occurred_at=occurred_at, digest=digest, details=mapping, indicator_version_id=indicator_version_id)
        compatibility = governance["compatibility"]
        for comparable_version in compatibility["comparable_versions"]:
            cursor = connection.execute("""
                INSERT OR IGNORE INTO indicator_compatibility_rules(indicator_version_id,comparable_version,required_dimensions_json,methodology_equivalence_json,notes)
                VALUES (?,?,?,?,?)
            """, (indicator_version_id, comparable_version, json.dumps(compatibility["required_dimensions"], ensure_ascii=False), json.dumps(compatibility["methodology_equivalence"], ensure_ascii=False), compatibility.get("notes")))
            if cursor.rowcount:
                cls._append_governance_event(connection, indicator_id=indicator_id, indicator_canonical_id=indicator["id"], event_type="compatibility_rule_added", actor=actor, occurred_at=occurred_at, digest=digest, details={"comparable_version": comparable_version}, indicator_version_id=indicator_version_id)
        if version_created:
            event_type = "indicator_registered" if connection.execute("SELECT COUNT(*) FROM indicator_versions WHERE indicator_id=?", (indicator_id,)).fetchone()[0] == 1 else "indicator_versioned"
            cls._append_governance_event(connection, indicator_id=indicator_id, indicator_canonical_id=indicator["id"], event_type=event_type, actor=actor, occurred_at=occurred_at, digest=digest, details={"version": indicator["version"], "payload_sha256": digest}, indicator_version_id=indicator_version_id)
        if methodology_created:
            cls._append_governance_event(connection, indicator_id=indicator_id, indicator_canonical_id=indicator["id"], event_type="methodology_versioned", actor=actor, occurred_at=occurred_at, digest=methodology_digest, details={"methodology_id": methodology["id"], "version": methodology["version"]}, indicator_version_id=indicator_version_id, methodology_version_id=methodology_version_id)
        return indicator_version_id, methodology_version_id, unit_id


    @staticmethod
    def _append_lineage_event(
        connection: sqlite3.Connection, *, record_id: str, measurement_id: int,
        event_type: str, actor: str, occurred_at: str, details: Mapping[str, Any]
    ) -> None:
        previous = connection.execute(
            "SELECT event_id FROM lineage_events WHERE record_id=? ORDER BY id DESC LIMIT 1", (record_id,)
        ).fetchone()
        digest = hashlib.sha256(canonical_json(details).encode("utf-8")).hexdigest()
        event_id = _lineage_event_id(record_id, event_type, occurred_at, digest)
        connection.execute(
            """
            INSERT OR IGNORE INTO lineage_events(
                event_id,record_id,measurement_id,event_type,actor,details_json,previous_event_id,occurred_at
            ) VALUES (?,?,?,?,?,?,?,?)
            """,
            (event_id, record_id, measurement_id, event_type, actor, canonical_json(details), previous[0] if previous else None, occurred_at),
        )

    @classmethod
    def _persist_observation_lineage(
        cls, connection: sqlite3.Connection, record: Mapping[str, Any], measurement_id: int
    ) -> None:
        lineage = record["observation_lineage"]
        actor = record["producer"]["component"]
        occurred_at = record["updated_at"]

        connection.execute("DELETE FROM measurement_questions WHERE measurement_id=?", (measurement_id,))
        for position, question in enumerate(lineage["questions"]):
            connection.execute(
                """
                INSERT INTO research_questions(canonical_id,question_text,question_type,decision_context,status,owner,updated_at)
                VALUES (?,?,?,?,?,?,?)
                ON CONFLICT(canonical_id) DO UPDATE SET question_text=excluded.question_text,
                    question_type=excluded.question_type,decision_context=excluded.decision_context,
                    status=excluded.status,owner=excluded.owner,updated_at=excluded.updated_at
                """,
                (question["id"], question["text"], question["type"], question.get("decision_context"), question["status"], question.get("owner"), occurred_at),
            )
            question_row_id = int(connection.execute("SELECT id FROM research_questions WHERE canonical_id=?", (question["id"],)).fetchone()[0])
            role = "primary" if position == 0 else "supporting"
            connection.execute("INSERT INTO measurement_questions(measurement_id,question_id,role) VALUES (?,?,?)", (measurement_id, question_row_id, role))
            cls._append_lineage_event(connection, record_id=record["record_id"], measurement_id=measurement_id, event_type="question_linked", actor=actor, occurred_at=occurred_at, details={"question_id": question["id"], "role": role})

        instrument_versions: dict[str, int] = {}
        for instrument in lineage["instruments"]:
            connection.execute(
                """
                INSERT INTO instruments(canonical_id,name,instrument_type,current_version,description,provider,updated_at)
                VALUES (?,?,?,?,?,?,?)
                ON CONFLICT(canonical_id) DO UPDATE SET name=excluded.name,instrument_type=excluded.instrument_type,
                    current_version=excluded.current_version,description=excluded.description,provider=excluded.provider,updated_at=excluded.updated_at
                """,
                (instrument["id"], instrument["name"], instrument["type"], instrument["version"], instrument.get("description"), instrument.get("provider"), occurred_at),
            )
            instrument_id = int(connection.execute("SELECT id FROM instruments WHERE canonical_id=?", (instrument["id"],)).fetchone()[0])
            payload = canonical_json(instrument); digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
            row = connection.execute("SELECT id FROM instrument_versions WHERE instrument_id=? AND payload_sha256=?", (instrument_id,digest)).fetchone()
            created = row is None
            if row is None:
                revision = int(connection.execute("SELECT COALESCE(MAX(revision_number),0)+1 FROM instrument_versions WHERE instrument_id=? AND version=?", (instrument_id,instrument["version"])).fetchone()[0])
                cursor = connection.execute("INSERT INTO instrument_versions(instrument_id,version,revision_number,payload_json,payload_sha256) VALUES (?,?,?,?,?)", (instrument_id,instrument["version"],revision,payload,digest))
                version_id = int(cursor.lastrowid)
                for pos, field in enumerate(instrument["fields"]):
                    unit_row = connection.execute("SELECT id FROM unit_definitions WHERE canonical_id=?", (field.get("unit_id"),)).fetchone() if field.get("unit_id") else None
                    connection.execute("INSERT INTO instrument_fields(instrument_version_id,field_name,data_type,unit_id,description,required,position) VALUES (?,?,?,?,?,?,?)", (version_id,field["name"],field["data_type"],int(unit_row[0]) if unit_row else None,field.get("description"),int(field.get("required",False)),pos))
            else:
                version_id = int(row[0])
            instrument_versions[instrument["id"]] = version_id
            if created:
                cls._append_lineage_event(connection, record_id=record["record_id"], measurement_id=measurement_id, event_type="instrument_versioned", actor=actor, occurred_at=occurred_at, details={"instrument_id": instrument["id"], "version": instrument["version"], "payload_sha256": digest})

        dataset_versions: dict[str, int] = {}
        for dataset in lineage["datasets"]:
            connection.execute(
                """
                INSERT INTO datasets(canonical_id,name,current_version,description,license,access_classification,checksum,updated_at)
                VALUES (?,?,?,?,?,?,?,?)
                ON CONFLICT(canonical_id) DO UPDATE SET name=excluded.name,current_version=excluded.current_version,
                    description=excluded.description,license=excluded.license,access_classification=excluded.access_classification,
                    checksum=excluded.checksum,updated_at=excluded.updated_at
                """,
                (dataset["id"],dataset["name"],dataset["version"],dataset.get("description"),dataset.get("license"),dataset["access"],dataset.get("checksum"),occurred_at),
            )
            dataset_id = int(connection.execute("SELECT id FROM datasets WHERE canonical_id=?", (dataset["id"],)).fetchone()[0])
            payload=canonical_json(dataset); digest=hashlib.sha256(payload.encode("utf-8")).hexdigest()
            row=connection.execute("SELECT id FROM dataset_versions WHERE dataset_id=? AND payload_sha256=?", (dataset_id,digest)).fetchone()
            created=row is None
            if row is None:
                revision=int(connection.execute("SELECT COALESCE(MAX(revision_number),0)+1 FROM dataset_versions WHERE dataset_id=? AND version=?", (dataset_id,dataset["version"])).fetchone()[0])
                cursor=connection.execute("INSERT INTO dataset_versions(dataset_id,version,revision_number,payload_json,payload_sha256) VALUES (?,?,?,?,?)", (dataset_id,dataset["version"],revision,payload,digest))
                version_id=int(cursor.lastrowid)
                for pos, field in enumerate(dataset["fields"]):
                    unit_row=connection.execute("SELECT id FROM unit_definitions WHERE canonical_id=?", (field.get("unit_id"),)).fetchone() if field.get("unit_id") else None
                    connection.execute("INSERT INTO dataset_fields(dataset_version_id,field_name,data_type,unit_id,description,nullable,position) VALUES (?,?,?,?,?,?,?)", (version_id,field["name"],field["data_type"],int(unit_row[0]) if unit_row else None,field.get("description"),int(field.get("nullable",True)),pos))
            else:
                version_id=int(row[0])
            dataset_versions[dataset["id"]]=version_id
            if created:
                cls._append_lineage_event(connection, record_id=record["record_id"], measurement_id=measurement_id, event_type="dataset_versioned", actor=actor, occurred_at=occurred_at, details={"dataset_id":dataset["id"],"version":dataset["version"],"payload_sha256":digest})

        batch_rows: dict[str, int] = {}
        for batch in lineage["batches"]:
            payload=canonical_json(batch)
            connection.execute(
                """
                INSERT INTO observation_batches(canonical_id,dataset_version_id,instrument_version_id,collected_at,received_at,collector,protocol,record_count,notes,payload_json)
                VALUES (?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(canonical_id) DO UPDATE SET dataset_version_id=excluded.dataset_version_id,
                    instrument_version_id=excluded.instrument_version_id,collected_at=excluded.collected_at,
                    received_at=excluded.received_at,collector=excluded.collector,protocol=excluded.protocol,
                    record_count=excluded.record_count,notes=excluded.notes,payload_json=excluded.payload_json
                """,
                (batch["id"],dataset_versions[batch["dataset_id"]],instrument_versions[batch["instrument_id"]],batch.get("collected_at"),batch.get("received_at"),batch.get("collector"),batch.get("protocol"),batch["record_count"],batch.get("notes"),payload),
            )
            batch_rows[batch["id"]]=int(connection.execute("SELECT id FROM observation_batches WHERE canonical_id=?", (batch["id"],)).fetchone()[0])
            cls._append_lineage_event(connection, record_id=record["record_id"], measurement_id=measurement_id, event_type="batch_registered", actor=actor, occurred_at=occurred_at, details={"batch_id":batch["id"],"record_count":batch["record_count"]})

        connection.execute("DELETE FROM measurement_observations WHERE measurement_id=?", (measurement_id,))
        observation_rows: dict[str, int] = {}
        for observation in lineage["observations"]:
            unit_row=connection.execute("SELECT id FROM unit_definitions WHERE canonical_id=?", (observation.get("unit_id"),)).fetchone() if observation.get("unit_id") else None
            connection.execute(
                """
                INSERT INTO observations(canonical_id,batch_id,observed_at,role,value_numeric,value_text,unit_id,quality_status,missing_reason,censoring,outlier,imputation,raw_payload_json,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(canonical_id) DO UPDATE SET batch_id=excluded.batch_id,observed_at=excluded.observed_at,
                    role=excluded.role,value_numeric=excluded.value_numeric,value_text=excluded.value_text,unit_id=excluded.unit_id,
                    quality_status=excluded.quality_status,missing_reason=excluded.missing_reason,censoring=excluded.censoring,
                    outlier=excluded.outlier,imputation=excluded.imputation,raw_payload_json=excluded.raw_payload_json,updated_at=excluded.updated_at
                """,
                (observation["id"],batch_rows[observation["batch_id"]],observation.get("observed_at"),observation["role"],observation.get("value"),observation.get("value_text"),int(unit_row[0]) if unit_row else None,observation["quality_status"],observation.get("missing_reason"),observation.get("censoring"),int(observation.get("outlier",False)),observation.get("imputation"),canonical_json(observation.get("raw_payload",{})),occurred_at),
            )
            observation_id=int(connection.execute("SELECT id FROM observations WHERE canonical_id=?", (observation["id"],)).fetchone()[0])
            observation_rows[observation["id"]]=observation_id
            connection.execute("DELETE FROM observation_dimensions WHERE observation_id=?", (observation_id,))
            for name,value in observation["dimensions"].items():
                connection.execute("INSERT INTO observation_dimensions(observation_id,dimension_name,dimension_value) VALUES (?,?,?)", (observation_id,name,str(value)))
            connection.execute("INSERT INTO measurement_observations(measurement_id,observation_id,role) VALUES (?,?,?)", (measurement_id,observation_id,observation["role"]))
            cls._append_lineage_event(connection, record_id=record["record_id"], measurement_id=measurement_id, event_type="observation_recorded", actor=actor, occurred_at=observation.get("observed_at") or occurred_at, details={"observation_id":observation["id"],"role":observation["role"],"quality_status":observation["quality_status"]})
            cls._append_lineage_event(connection, record_id=record["record_id"], measurement_id=measurement_id, event_type="observation_linked", actor=actor, occurred_at=occurred_at, details={"observation_id":observation["id"],"role":observation["role"]})

        for transformation in lineage["transformations"]:
            connection.execute(
                """
                INSERT INTO observation_transformations(canonical_id,measurement_id,operation,description,software,parameters_json,output_fields_json,occurred_at)
                VALUES (?,?,?,?,?,?,?,?)
                ON CONFLICT(canonical_id) DO UPDATE SET measurement_id=excluded.measurement_id,operation=excluded.operation,
                    description=excluded.description,software=excluded.software,parameters_json=excluded.parameters_json,
                    output_fields_json=excluded.output_fields_json,occurred_at=excluded.occurred_at
                """,
                (transformation["id"],measurement_id,transformation["operation"],transformation["description"],transformation.get("software"),canonical_json(transformation["parameters"]),json.dumps(transformation["output_measurement_fields"],ensure_ascii=False),transformation.get("occurred_at")),
            )
            transformation_id=int(connection.execute("SELECT id FROM observation_transformations WHERE canonical_id=?", (transformation["id"],)).fetchone()[0])
            connection.execute("DELETE FROM transformation_inputs WHERE transformation_id=?", (transformation_id,))
            for pos, observation_id in enumerate(transformation["input_observation_ids"]):
                connection.execute("INSERT INTO transformation_inputs(transformation_id,observation_id,position) VALUES (?,?,?)", (transformation_id,observation_rows[observation_id],pos))
            cls._append_lineage_event(connection, record_id=record["record_id"], measurement_id=measurement_id, event_type="transformation_recorded", actor=actor, occurred_at=transformation.get("occurred_at") or occurred_at, details={"transformation_id":transformation["id"],"operation":transformation["operation"],"inputs":transformation["input_observation_ids"]})



    @staticmethod
    def _changed_paths(before: Any, after: Any, prefix: str = "") -> list[str]:
        if type(before) is not type(after):
            return [prefix or "$record"]
        if isinstance(before, Mapping):
            paths: list[str] = []
            for key in sorted(set(before) | set(after)):
                path = f"{prefix}.{key}" if prefix else str(key)
                if key not in before or key not in after:
                    paths.append(path)
                else:
                    paths.extend(CatalystRepository._changed_paths(before[key], after[key], path))
            return paths
        if isinstance(before, list):
            return [] if before == after else [prefix or "$record"]
        return [] if before == after else [prefix or "$record"]

    @classmethod
    def _persist_review_workflow(
        cls, connection: sqlite3.Connection, record: Mapping[str, Any], measurement_id: int,
        revision_id: int, previous_revision_id: int | None
    ) -> None:
        workflow = record["review_workflow"]
        case_id_value = "review:" + hashlib.sha256(record["record_id"].encode("utf-8")).hexdigest()[:24]
        gate = workflow["publication_gate"]
        connection.execute(
            """
            INSERT INTO review_cases(canonical_id,record_id,measurement_id,current_state,priority,assigned_reviewers_json,publication_status,publication_reasons_json,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(record_id) DO UPDATE SET measurement_id=excluded.measurement_id,current_state=excluded.current_state,
                priority=excluded.priority,assigned_reviewers_json=excluded.assigned_reviewers_json,
                publication_status=excluded.publication_status,publication_reasons_json=excluded.publication_reasons_json,updated_at=excluded.updated_at
            """,
            (case_id_value, record["record_id"], measurement_id, workflow["state"], workflow["priority"],
             json.dumps(workflow["assigned_reviewers"], ensure_ascii=False), gate["status"],
             json.dumps(gate["reasons"], ensure_ascii=False), record["created_at"], record["updated_at"]),
        )
        case_id = int(connection.execute("SELECT id FROM review_cases WHERE record_id=?", (record["record_id"],)).fetchone()[0])

        actor = record["producer"]["component"]
        for reviewer in workflow["assigned_reviewers"]:
            assignment_id = "assignment:" + hashlib.sha256(f"{case_id_value}|{reviewer}|assigned".encode()).hexdigest()[:24]
            connection.execute(
                "INSERT OR IGNORE INTO review_assignments(assignment_id,review_case_id,reviewer,action,actor,occurred_at) VALUES (?,?,?,?,?,?)",
                (assignment_id, case_id, reviewer, "assigned", actor, record["updated_at"]),
            )

        quality = workflow["quality"]
        quality_json = canonical_json(quality)
        quality_sha = hashlib.sha256(quality_json.encode("utf-8")).hexdigest()
        assessment_id = "quality:" + hashlib.sha256(f"{case_id_value}|{quality_sha}".encode()).hexdigest()[:24]
        connection.execute(
            """INSERT OR IGNORE INTO quality_assessments(assessment_id,review_case_id,completeness,validity,consistency,timeliness,provenance,uncertainty,overall,basis_json,assessed_by,assessed_at,payload_sha256)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (assessment_id, case_id, quality["completeness"], quality["validity"], quality["consistency"],
             quality["timeliness"], quality["provenance"], quality["uncertainty"], quality["overall"],
             canonical_json(quality["basis"]), quality["assessed_by"], quality["assessed_at"], quality_sha),
        )

        for comment in workflow["comments"]:
            connection.execute(
                "INSERT OR IGNORE INTO review_comments(comment_id,review_case_id,actor,body,visibility,occurred_at) VALUES (?,?,?,?,?,?)",
                (comment["id"], case_id, comment["actor"], comment["body"], comment["visibility"], comment["occurred_at"]),
            )

        previous_decision = connection.execute("SELECT decision_id FROM review_decisions WHERE review_case_id=? ORDER BY id DESC LIMIT 1", (case_id,)).fetchone()
        for decision in workflow["decisions"]:
            existing = connection.execute("SELECT 1 FROM review_decisions WHERE decision_id=?", (decision["id"],)).fetchone()
            if existing:
                previous_decision = (decision["id"],)
                continue
            connection.execute(
                """INSERT INTO review_decisions(decision_id,review_case_id,decision_type,actor,reason,notes,previous_decision_id,occurred_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (decision["id"], case_id, decision["type"], decision["actor"], decision.get("reason"),
                 decision.get("notes"), previous_decision[0] if previous_decision else None, decision["occurred_at"]),
            )
            previous_decision = (decision["id"],)

        previous_payload = None
        if previous_revision_id is not None:
            row = connection.execute("SELECT payload_json FROM record_revisions WHERE id=?", (previous_revision_id,)).fetchone()
            previous_payload = json.loads(row[0]) if row else None
        revision = workflow["revision"]
        changed_paths = cls._changed_paths(previous_payload, record) if previous_payload is not None else ["$record"]
        diff_key = f"{record['record_id']}|{revision_id}|{canonical_json(changed_paths)}"
        diff_id = "revision-diff:" + hashlib.sha256(diff_key.encode()).hexdigest()[:24]
        connection.execute(
            """INSERT OR IGNORE INTO revision_diffs(diff_id,record_id,from_revision_id,to_revision_id,action,change_summary,reason,changed_by,changes_json)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (diff_id, record["record_id"], previous_revision_id, revision_id, revision["action"], revision["change_summary"],
             revision.get("reason"), revision["changed_by"], canonical_json({"changed_paths": changed_paths})),
        )

        approved_decisions = [item for item in workflow["decisions"] if item["type"] == "approved"]
        for decision in approved_decisions:
            snapshot_id = "approval:" + hashlib.sha256(f"{case_id_value}|{decision['id']}|{revision_id}".encode()).hexdigest()[:24]
            connection.execute(
                """INSERT OR IGNORE INTO approval_snapshots(snapshot_id,review_case_id,decision_id,record_revision_id,record_payload_json,record_payload_sha256,approved_by,approved_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (snapshot_id, case_id, decision["id"], revision_id, canonical_json(record), payload_hash(record), decision["actor"], decision["occurred_at"]),
            )

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

    def upsert_record(self, record: Mapping[str, Any], *, connection: sqlite3.Connection | None = None, import_run_id: int | None = None, row_number: int | None = None, _force_evidence_rebuild: bool = False, _force_governance_rebuild: bool = False, _force_lineage_rebuild: bool = False, _force_review_rebuild: bool = False) -> str:
        record = deepcopy(dict(record))
        if "observation_lineage" not in record:
            record["observation_lineage"] = normalize_observation_lineage(record, None)
        else:
            lineage = record["observation_lineage"]
            for observation in lineage.get("observations", []):
                if observation.get("role") == "current":
                    observation["value"] = record["measurement"]["current"]
                    observation["quality_status"] = "valid"
                    observation["missing_reason"] = None
                elif observation.get("role") == "baseline":
                    observation["value"] = record["measurement"].get("baseline")
                    observation["quality_status"] = "missing" if record["measurement"].get("baseline") is None else "valid"
                    observation["missing_reason"] = "baseline not supplied" if record["measurement"].get("baseline") is None else None
            lineage["completeness_score"] = lineage_completeness(lineage)
        if "review_workflow" not in record:
            record["review_workflow"] = normalize_review_workflow(record, None)
        validate_record(record); validate_record_semantics(record)
        own_connection = connection is None; conn = connection or connect(self.path)
        try:
            self._require_current(conn)
            digest = payload_hash(record)
            existing = conn.execute("SELECT payload_sha256 FROM data_records WHERE record_id=?", (record["record_id"],)).fetchone()
            same_payload = bool(existing and existing[0] == digest)
            revision_exists = bool(conn.execute(
                "SELECT 1 FROM record_revisions WHERE record_id=? AND payload_sha256=? LIMIT 1",
                (record["record_id"], digest),
            ).fetchone())
            provenance_exists = bool(conn.execute(
                "SELECT 1 FROM provenance_events WHERE record_id=? LIMIT 1",
                (record["record_id"],),
            ).fetchone())
            if same_payload and not _force_evidence_rebuild and not _force_governance_rebuild and not _force_lineage_rebuild and not _force_review_rebuild:
                if import_run_id is not None:
                    conn.execute("INSERT INTO import_records(import_run_id,row_number,record_id,action,payload_sha256) VALUES (?,?,?,?,?)", (import_run_id, row_number, record["record_id"], "skipped", digest))
                if own_connection: conn.commit()
                return "skipped"

            with transaction(conn):
                entity_id = self._upsert_entity(conn, record); indicator_id = self._upsert_indicator(conn, record); period_id = self._upsert_period(conn, record)
                self._persist_indicator_governance(conn, record, indicator_id)
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
                action = "skipped" if same_payload else ("updated" if existing else "inserted"); payload_json = canonical_json(record)
                conn.execute("""
                    INSERT INTO data_records(record_id,schema_version,record_type,payload_json,payload_sha256,entity_id,indicator_id,period_id,source_id,measurement_id,created_at,updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(record_id) DO UPDATE SET schema_version=excluded.schema_version,record_type=excluded.record_type,
                        payload_json=excluded.payload_json,payload_sha256=excluded.payload_sha256,entity_id=excluded.entity_id,
                        indicator_id=excluded.indicator_id,period_id=excluded.period_id,source_id=excluded.source_id,
                        measurement_id=excluded.measurement_id,updated_at=excluded.updated_at
                """, (record["record_id"], record["schema_version"], record["record_type"], payload_json, digest, entity_id, indicator_id, period_id, primary_source_id, measurement_id, record["created_at"], record["updated_at"]))

                self._persist_observation_lineage(conn, record, measurement_id)

                previous_revision_row = conn.execute("SELECT id FROM record_revisions WHERE record_id=? ORDER BY revision_number DESC LIMIT 1", (record["record_id"],)).fetchone()
                previous_revision_id = int(previous_revision_row[0]) if previous_revision_row else None
                revision_number = int(conn.execute("SELECT COALESCE(MAX(revision_number),0)+1 FROM record_revisions WHERE record_id=?", (record["record_id"],)).fetchone()[0])
                if not same_payload or not revision_exists:
                    revision_action = action if not same_payload else ("inserted" if revision_number == 1 else "updated")
                    cursor = conn.execute("INSERT INTO record_revisions(record_id,revision_number,action,payload_json,payload_sha256,import_run_id) VALUES (?,?,?,?,?,?)", (record["record_id"], revision_number, revision_action, payload_json, digest, import_run_id))
                    revision_id = int(cursor.lastrowid)
                else:
                    revision_number = max(1, revision_number - 1)
                    revision_id = int(conn.execute("SELECT id FROM record_revisions WHERE record_id=? AND payload_sha256=?", (record["record_id"], digest)).fetchone()[0])

                self._persist_review_workflow(conn, record, measurement_id, revision_id, previous_revision_id if previous_revision_id != revision_id else None)

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

                if not same_payload or not provenance_exists:
                    event_type = "record_updated" if existing and provenance_exists else "record_created"
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

    def indicator_registry(self, indicator_id: str | None = None, *, limit: int = 100) -> list[dict[str, Any]]:
        with closing(connect(self.path)) as connection:
            self._require_current(connection)
            sql = "SELECT * FROM indicator_registry_current"; params: list[Any] = []
            if indicator_id:
                sql += " WHERE indicator_id=?"; params.append(indicator_id)
            sql += " ORDER BY indicator_id LIMIT ?"; params.append(limit)
            rows = []
            for row in connection.execute(sql, params):
                item = dict(row); item["disaggregation_dimensions"] = json.loads(item.pop("disaggregation_json")); rows.append(item)
            return rows

    def methodology_history(self, methodology_id: str | None = None, *, limit: int = 100) -> list[dict[str, Any]]:
        with closing(connect(self.path)) as connection:
            self._require_current(connection)
            sql = """SELECT m.canonical_id AS methodology_id,m.title,m.current_status,mv.version,mv.revision_number,mv.status,mv.payload_json,mv.payload_sha256,mv.approved_by,mv.approved_at,mv.created_at FROM methodology_versions mv JOIN methodologies m ON m.id=mv.methodology_id"""; params: list[Any] = []
            if methodology_id:
                sql += " WHERE m.canonical_id=?"; params.append(methodology_id)
            sql += " ORDER BY m.canonical_id,mv.created_at DESC,mv.id DESC LIMIT ?"; params.append(limit)
            rows=[]
            for row in connection.execute(sql, params):
                item=dict(row); item["payload"] = json.loads(item.pop("payload_json")); rows.append(item)
            return rows

    def unit_registry(self, unit_id: str | None = None, *, limit: int = 100) -> list[dict[str, Any]]:
        with closing(connect(self.path)) as connection:
            self._require_current(connection)
            sql="SELECT canonical_id AS unit_id,symbol,name,dimension,canonical_unit_id,conversion_factor,conversion_offset,created_at,updated_at FROM unit_definitions"; params: list[Any]=[]
            if unit_id:
                sql += " WHERE canonical_id=?"; params.append(unit_id)
            sql += " ORDER BY dimension,symbol LIMIT ?"; params.append(limit)
            return [dict(row) for row in connection.execute(sql, params)]

    def convert(self, value: float, from_unit_id: str, to_unit_id: str) -> float:
        with closing(connect(self.path)) as connection:
            self._require_current(connection)
            rows = connection.execute("SELECT canonical_id AS id,symbol,name,dimension,canonical_unit_id,conversion_factor,conversion_offset FROM unit_definitions WHERE canonical_id IN (?,?)", (from_unit_id,to_unit_id)).fetchall()
            units={row["id"]:dict(row) for row in rows}
            if from_unit_id not in units or to_unit_id not in units:
                raise RepositoryError("one or both units were not found")
            return convert_unit_value(value, units[from_unit_id], units[to_unit_id])

    def compare(self, left_record_id: str, right_record_id: str) -> dict[str, Any]:
        left=self.get_record(left_record_id); right=self.get_record(right_record_id)
        if left is None or right is None:
            raise RepositoryError("one or both records were not found")
        result=compare_governance(left,right)
        result.update({"left_record_id":left_record_id,"right_record_id":right_record_id})
        if result["conversion_available"] and left["indicator_governance"]["unit"]["id"] != right["indicator_governance"]["unit"]["id"]:
            result["right_value_in_left_unit"] = convert_unit_value(right["measurement"]["current"], right["indicator_governance"]["unit"], left["indicator_governance"]["unit"])
        return result

    def governance_events(self, indicator_id: str, *, limit: int = 200) -> list[dict[str, Any]]:
        with closing(connect(self.path)) as connection:
            self._require_current(connection)
            rows=[]
            for row in connection.execute("""SELECT ge.event_id,ge.event_type,ge.actor,ge.details_json,ge.occurred_at,ge.created_at FROM governance_events ge JOIN indicators i ON i.id=ge.indicator_id WHERE i.canonical_id=? ORDER BY ge.id LIMIT ?""", (indicator_id,limit)):
                item=dict(row); item["details"]=json.loads(item.pop("details_json")); rows.append(item)
            return rows


    def questions(self, question_id: str | None = None, *, limit: int = 100) -> list[dict[str, Any]]:
        with closing(connect(self.path)) as connection:
            self._require_current(connection)
            sql="SELECT canonical_id AS question_id,question_text,question_type,decision_context,status,owner,created_at,updated_at FROM research_questions"; params=[]
            if question_id: sql += " WHERE canonical_id=?"; params.append(question_id)
            sql += " ORDER BY updated_at DESC,canonical_id LIMIT ?"; params.append(limit)
            return [dict(row) for row in connection.execute(sql,params)]

    def instruments(self, instrument_id: str | None = None, *, limit: int = 100) -> list[dict[str, Any]]:
        with closing(connect(self.path)) as connection:
            self._require_current(connection)
            sql="SELECT * FROM instrument_registry_current"; params=[]
            if instrument_id: sql += " WHERE instrument_id=?"; params.append(instrument_id)
            sql += " ORDER BY instrument_id LIMIT ?"; params.append(limit)
            return [dict(row) for row in connection.execute(sql,params)]

    def datasets(self, dataset_id: str | None = None, *, limit: int = 100) -> list[dict[str, Any]]:
        with closing(connect(self.path)) as connection:
            self._require_current(connection)
            sql="SELECT * FROM dataset_registry_current"; params=[]
            if dataset_id: sql += " WHERE dataset_id=?"; params.append(dataset_id)
            sql += " ORDER BY dataset_id LIMIT ?"; params.append(limit)
            return [dict(row) for row in connection.execute(sql,params)]

    def observations(self, record_id: str | None = None, *, quality_status: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        with closing(connect(self.path)) as connection:
            self._require_current(connection)
            sql="""SELECT dr.record_id,o.canonical_id AS observation_id,o.role,o.observed_at,o.value_numeric AS value,o.value_text,
                ud.canonical_id AS unit_id,o.quality_status,o.missing_reason,o.censoring,o.outlier,o.imputation,ob.canonical_id AS batch_id
                FROM observations o JOIN observation_batches ob ON ob.id=o.batch_id
                LEFT JOIN unit_definitions ud ON ud.id=o.unit_id
                JOIN measurement_observations mo ON mo.observation_id=o.id JOIN measurements m ON m.id=mo.measurement_id
                JOIN data_records dr ON dr.measurement_id=m.id"""; params=[]; clauses=[]
            if record_id: clauses.append("dr.record_id=?"); params.append(record_id)
            if quality_status: clauses.append("o.quality_status=?"); params.append(quality_status)
            if clauses: sql += " WHERE " + " AND ".join(clauses)
            sql += " ORDER BY o.observed_at,o.id LIMIT ?"; params.append(limit)
            rows=[]
            for row in connection.execute(sql,params):
                item=dict(row)
                dims=connection.execute("SELECT dimension_name,dimension_value FROM observation_dimensions WHERE observation_id=(SELECT id FROM observations WHERE canonical_id=?)", (item["observation_id"],)).fetchall()
                item["dimensions"]={dim[0]:dim[1] for dim in dims}; item["outlier"]=bool(item["outlier"]); rows.append(item)
            return rows

    def lineage(self, record_id: str) -> dict[str, Any] | None:
        record=self.get_record(record_id)
        if record is None: return None
        with closing(connect(self.path)) as connection:
            self._require_current(connection)
            summary=connection.execute("SELECT * FROM observation_lineage_summary WHERE record_id=?", (record_id,)).fetchone()
            events=[]
            for row in connection.execute("SELECT event_id,event_type,actor,details_json,previous_event_id,occurred_at,created_at FROM lineage_events WHERE record_id=? ORDER BY id", (record_id,)):
                item=dict(row); item["details"]=json.loads(item.pop("details_json")); events.append(item)
            return {"record_id":record_id,"lineage":record.get("observation_lineage"),"summary":dict(summary) if summary else {},"events":events}


    def review_cases(self, *, state: str | None = None, reviewer: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        with closing(connect(self.path)) as connection:
            self._require_current(connection)
            sql = "SELECT * FROM review_queue_current"; params: list[Any] = []; clauses=[]
            if state: clauses.append("current_state=?"); params.append(state)
            if reviewer: clauses.append("assigned_reviewers_json LIKE ?"); params.append(f'%"{reviewer}"%')
            if clauses: sql += " WHERE " + " AND ".join(clauses)
            sql += " ORDER BY CASE priority WHEN 'critical' THEN 1 WHEN 'high' THEN 2 WHEN 'normal' THEN 3 ELSE 4 END, updated_at LIMIT ?"; params.append(limit)
            rows=[]
            for row in connection.execute(sql, params):
                item=dict(row); item["assigned_reviewers"]=json.loads(item.pop("assigned_reviewers_json")); item["publication_reasons"]=json.loads(item.pop("publication_reasons_json")); rows.append(item)
            return rows

    def review_history(self, record_id: str) -> dict[str, Any] | None:
        record=self.get_record(record_id)
        if record is None: return None
        with closing(connect(self.path)) as connection:
            self._require_current(connection)
            case=connection.execute("SELECT * FROM review_cases WHERE record_id=?", (record_id,)).fetchone()
            if not case: return {"record_id":record_id,"workflow":record.get("review_workflow"),"decisions":[],"comments":[],"quality_assessments":[],"approval_snapshots":[]}
            cid=case["id"]
            decisions=[]
            for row in connection.execute("SELECT decision_id,decision_type,actor,reason,notes,previous_decision_id,occurred_at,created_at FROM review_decisions WHERE review_case_id=? ORDER BY id", (cid,)):
                decisions.append(dict(row))
            comments=[dict(row) for row in connection.execute("SELECT comment_id,actor,body,visibility,occurred_at,created_at FROM review_comments WHERE review_case_id=? ORDER BY id", (cid,))]
            quality=[]
            for row in connection.execute("SELECT * FROM quality_assessments WHERE review_case_id=? ORDER BY id", (cid,)):
                item=dict(row); item["basis"]=json.loads(item.pop("basis_json")); quality.append(item)
            snapshots=[dict(row) for row in connection.execute("SELECT snapshot_id,decision_id,record_payload_sha256,approved_by,approved_at,created_at FROM approval_snapshots WHERE review_case_id=? ORDER BY id", (cid,))]
            case_item=dict(case); case_item["assigned_reviewers"]=json.loads(case_item.pop("assigned_reviewers_json")); case_item["publication_reasons"]=json.loads(case_item.pop("publication_reasons_json"))
            return {"record_id":record_id,"workflow":record.get("review_workflow"),"case":case_item,"decisions":decisions,"comments":comments,"quality_assessments":quality,"approval_snapshots":snapshots}

    def revision_history(self, record_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        with closing(connect(self.path)) as connection:
            self._require_current(connection)
            rows=[]
            for row in connection.execute("SELECT * FROM record_revision_history WHERE record_id=? ORDER BY revision_number DESC LIMIT ?", (record_id,limit)):
                item=dict(row); item["changes"]=json.loads(item.pop("changes_json")) if item.get("changes_json") else None; rows.append(item)
            return rows

    def _mutate_review(self, record_id: str, actor: str, mutator: Any, *, summary: str, reason: str | None = None) -> str:
        record=self.get_record(record_id)
        if record is None: raise RepositoryError(f"record not found: {record_id}")
        previous_sha=payload_hash(record)
        workflow=deepcopy(record["review_workflow"]); workflow=mutator(workflow)
        workflow["publication_gate"] = publication_gate(record, workflow["state"], workflow["quality"])
        if workflow["state"] == "approved" and workflow["publication_gate"]["status"] == "external":
            approved=[item for item in workflow["decisions"] if item["type"]=="approved"][-1]
            workflow["publication_gate"]["approved_by"]=approved["actor"]; workflow["publication_gate"]["approved_at"]=approved["occurred_at"]
        workflow["revision"] = {"number": int(workflow["revision"]["number"])+1, "action": "updated", "change_summary": summary, "reason": reason, "changed_by": actor, "compared_to_sha256": previous_sha}
        record["review_workflow"]=workflow
        from datetime import datetime, timezone
        record["updated_at"]=datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00","Z")
        record["producer"]["component"]="repository-service"
        action = self.upsert_record(record)
        return action

    def assign_review(self, record_id: str, reviewer: str, actor: str) -> str:
        def mutate(workflow: dict[str, Any]) -> dict[str, Any]:
            if reviewer not in workflow["assigned_reviewers"]: workflow["assigned_reviewers"].append(reviewer)
            return append_decision(workflow, "assigned", actor, reason=f"Assigned to {reviewer}")
        return self._mutate_review(record_id, actor, mutate, summary=f"Assigned review to {reviewer}.")

    def submit_review(self, record_id: str, actor: str, notes: str | None = None) -> str:
        return self._mutate_review(record_id, actor, lambda workflow: append_decision(workflow,"submitted",actor,notes=notes), summary="Submitted record for review.")

    def start_review(self, record_id: str, actor: str, notes: str | None = None) -> str:
        return self._mutate_review(record_id, actor, lambda workflow: append_decision(workflow,"review_started",actor,notes=notes), summary="Review started.")

    def decide_review(self, record_id: str, decision: str, actor: str, *, reason: str | None = None, notes: str | None = None) -> str:
        return self._mutate_review(record_id, actor, lambda workflow: append_decision(workflow,decision,actor,reason=reason,notes=notes), summary=f"Review decision: {decision}.", reason=reason)

    def add_review_comment(self, record_id: str, actor: str, body: str, *, visibility: str = "internal") -> str:
        def mutate(workflow: dict[str, Any]) -> dict[str, Any]:
            updated=append_comment(workflow,actor,body,visibility=visibility)
            return append_decision(updated,"commented",actor,notes=body)
        return self._mutate_review(record_id, actor, mutate, summary="Added review comment.")

    def assess_quality(self, record_id: str, actor: str, scores: Mapping[str, int], *, basis: Mapping[str, str] | None = None) -> str:
        def mutate(workflow: dict[str, Any]) -> dict[str, Any]:
            quality=deepcopy(workflow["quality"])
            for name,value in scores.items():
                if name not in {"completeness","validity","consistency","timeliness","provenance","uncertainty"}: raise RepositoryError(f"unknown quality dimension: {name}")
                quality[name]=int(value)
            quality["overall"]=quality_overall(quality); quality["basis"].update(dict(basis or {})); quality["assessed_by"]=actor
            from datetime import datetime, timezone
            quality["assessed_at"]=datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00","Z")
            workflow["quality"]=quality
            return append_decision(workflow,"quality_assessed",actor,notes=f"Overall quality: {quality['overall']}")
        return self._mutate_review(record_id, actor, mutate, summary="Updated quality assessment.")

    def stats(self) -> dict[str, int]:
        with closing(connect(self.path)) as connection:
            self._require_current(connection)
            counts={"records":"data_records","entities":"entities","indicators":"indicators","indicator_versions":"indicator_versions","methodologies":"methodologies","methodology_versions":"methodology_versions","units":"unit_definitions","framework_mappings":"framework_mappings","governance_events":"governance_events","sources":"sources","measurements":"measurements","import_runs":"import_runs","source_versions":"source_versions","source_snapshots":"source_snapshots","evidence_links":"measurement_sources","record_revisions":"record_revisions","provenance_events":"provenance_events","open_evidence_gaps":"open_evidence_gaps","questions":"research_questions","instruments":"instruments","instrument_versions":"instrument_versions","datasets":"datasets","dataset_versions":"dataset_versions","observation_batches":"observation_batches","observations":"observations","observation_transformations":"observation_transformations","lineage_events":"lineage_events","review_cases":"review_cases","review_assignments":"review_assignments","review_comments":"review_comments","review_decisions":"review_decisions","quality_assessments":"quality_assessments","approval_snapshots":"approval_snapshots","revision_diffs":"revision_diffs","saved_queries":"saved_queries","saved_query_versions":"saved_query_versions","query_runs":"query_runs","query_run_records":"query_run_records","query_run_warnings":"query_run_warnings","export_bundles":"export_bundles","api_clients":"api_clients","api_audit_events":"api_audit_events","embed_profiles":"embed_profiles","handoff_receipts":"handoff_receipts","institutions":"institutions","principals":"principals","retention_policies":"retention_policies","workspaces":"workspaces","projects":"projects","workspace_memberships":"workspace_memberships","record_access_governance":"record_access_governance","api_client_workspace_bindings":"api_client_workspace_bindings","access_governance_events":"access_governance_events","workspace_transfer_events":"workspace_transfer_events","connectors":"connector_definitions","connector_versions":"connector_versions","connector_version_activations":"connector_version_activations","connector_schedules":"connector_schedules","connector_runs":"connector_runs","connector_run_logs":"connector_run_logs","connector_payload_snapshots":"connector_payload_snapshots","connector_run_records":"connector_run_records","connector_record_state":"connector_record_state","connector_quarantine":"connector_quarantine","connector_dead_letters":"connector_dead_letters","connector_reconciliations":"connector_reconciliations","connector_alerts":"connector_alerts","analysis_artifacts":"analysis_artifacts","analysis_versions":"analysis_versions","analysis_version_activations":"analysis_version_activations","analysis_runs":"analysis_runs","analysis_run_inputs":"analysis_run_inputs","analysis_outputs":"analysis_outputs","derived_measurement_lineage":"derived_measurement_lineage","analysis_platform_links":"analysis_platform_links","analysis_replication_reviews":"analysis_replication_reviews","analysis_invalidation_events":"analysis_invalidation_events","analysis_package_exports":"analysis_package_exports","operational_backups":"operational_backups","restore_events":"restore_events","offline_operations":"offline_operations","offline_sync_runs":"offline_sync_runs","performance_benchmarks":"performance_benchmarks","security_audit_events":"security_audit_events","release_attestations":"release_attestations"}
            return {name:int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]) for name,table in counts.items()}
