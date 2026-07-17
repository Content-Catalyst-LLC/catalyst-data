from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from catalyst_data.database import connect
from catalyst_data.engine import build_record
from catalyst_data.migrations import MigrationManager
from catalyst_data.operations import OperationalError, OperationalService
from catalyst_data.repository import CatalystRepository

ROOT = Path(__file__).resolve().parents[1]


def sample_record() -> dict:
    return build_record(json.loads((ROOT / "examples/sample_project.json").read_text(encoding="utf-8")))


def test_backup_verify_restore_and_immutable_history(tmp_path: Path) -> None:
    repository = CatalystRepository(tmp_path / "source.sqlite3")
    repository.initialize()
    record = sample_record()
    repository.upsert_record(record)
    service = OperationalService(repository)

    backup_path = tmp_path / "backups" / "source.sqlite3"
    backup = service.create_backup(backup_path, actor="principal:operator")
    assert backup["status"] == "verified"
    assert backup_path.exists()
    assert Path(backup["manifest_path"]).exists()
    assert service.verify_backup(backup_path)["record_count"] == 1
    assert len(service.backups()) == 1

    restored_path = tmp_path / "restored.sqlite3"
    restored = service.restore_backup(backup_path, restored_path, actor="principal:operator")
    assert restored["migration_version"] == 13
    assert restored["record_count"] == 1
    assert CatalystRepository(restored_path).get_record(record["record_id"])["record_id"] == record["record_id"]
    restored_service = OperationalService(CatalystRepository(restored_path))
    assert len(restored_service.restore_history()) == 1

    with connect(repository.path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="backup history is append-only"):
            connection.execute("UPDATE operational_backups SET status='failed'")


def test_restore_refuses_overwrite_without_force(tmp_path: Path) -> None:
    repository = CatalystRepository(tmp_path / "source.sqlite3")
    repository.initialize()
    service = OperationalService(repository)
    backup_path = tmp_path / "backup.sqlite3"
    service.create_backup(backup_path)
    target = tmp_path / "target.sqlite3"
    CatalystRepository(target).initialize()
    with pytest.raises(OperationalError, match="force"):
        service.restore_backup(backup_path, target)
    result = service.restore_backup(backup_path, target, force=True)
    assert result["safety_backup"]
    assert Path(result["safety_backup"]).exists()


def test_offline_queue_sync_and_retry(tmp_path: Path) -> None:
    repository = CatalystRepository(tmp_path / "repository.sqlite3")
    repository.initialize()
    service = OperationalService(repository)
    record = sample_record()

    queued = service.queue_operation("record-upsert", {"record": record}, actor="principal:field-worker")
    assert queued["status"] == "queued"
    failed = service.queue_operation("custom", {"job": "external"}, max_attempts=2)
    first = service.sync_offline()
    assert first["status"] == "partial"
    assert first["succeeded_count"] == 1
    assert first["failed_count"] == 1
    assert repository.get_record(record["record_id"]) is not None
    assert service.operation(failed["operation_id"])["attempts"] == 1

    second = service.sync_offline(retry_failed=True)
    assert second["failed_count"] == 1
    assert service.operation(failed["operation_id"])["attempts"] == 2
    third = service.sync_offline(retry_failed=True)
    assert third["queued_count"] == 0
    assert len(service.sync_runs()) == 3


def test_benchmark_security_attestation_and_readiness(tmp_path: Path) -> None:
    repository = CatalystRepository(tmp_path / "repository.sqlite3")
    repository.initialize()
    repository.upsert_record(sample_record())
    service = OperationalService(repository)

    benchmark = service.benchmark(iterations=1)
    assert benchmark["status"] == "pass"
    assert benchmark["metrics"]["integrity"] == "ok"
    security = service.security_audit()
    assert security["status"] in {"pass", "warning"}
    assert not any(item["status"] == "fail" for item in security["checks"])

    attestation_path = tmp_path / "release-attestation.json"
    attestation = service.create_release_attestation(ROOT, attestation_path)
    assert attestation_path.exists()
    assert len(attestation["manifest"]["repository_sha256"]) == 64
    assert attestation["sbom"]["component"]["name"] == "catalyst-data"

    readiness = service.readiness()
    assert readiness["failed_benchmark_count"] == 0
    assert readiness["failed_security_check_count"] == 0
    assert readiness["release_attestation_count"] == 1
    stats = repository.stats()
    assert stats["performance_benchmarks"] == 1
    assert stats["release_attestations"] == 1


def test_migration_012_populated_rollback_and_reapply(tmp_path: Path) -> None:
    repository = CatalystRepository(tmp_path / "repository.sqlite3")
    repository.initialize()
    service = OperationalService(repository)
    service.benchmark(iterations=1)
    service.security_audit()
    with connect(repository.path) as connection:
        manager = MigrationManager(connection)
        assert manager.current_version == 13
        assert manager.rollback(2) == [13, 12]
        assert manager.current_version == 11
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='operational_backups'").fetchone() is None
        assert manager.migrate() == [12, 13]
        assert manager.current_version == 13
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='operational_readiness'").fetchone() is not None


def test_operational_cli_commands(tmp_path: Path, capsys) -> None:
    from catalyst_data.cli import main
    database = tmp_path / "cli.sqlite3"
    assert main(["init", str(database)]) == 0
    backup = tmp_path / "cli-backup.sqlite3"
    assert main(["backup-create", str(database), str(backup)]) == 0
    assert main(["backup-verify", str(database), str(backup)]) == 0
    assert main(["benchmark", str(database), "--iterations", "1"]) == 0
    assert main(["security-audit", str(database)]) == 0
    assert main(["operational-readiness", str(database)]) == 0
    output = capsys.readouterr().out
    assert "catalyst-data-operational-hardening/1.0" in output
