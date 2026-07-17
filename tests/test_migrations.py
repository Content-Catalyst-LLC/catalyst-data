from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

from catalyst_data.database import connect
from catalyst_data.migrations import MigrationManager, discover_migrations
from catalyst_data.repository import CatalystRepository


def test_migrations_are_contiguous_and_reversible(tmp_path):
    assert [item.version for item in discover_migrations()] == [1, 2, 3, 4, 5, 6, 7]
    database = tmp_path / "repository.sqlite3"
    with connect(database) as connection:
        manager = MigrationManager(connection)
        assert manager.current_version == 0
        assert manager.migrate() == [1, 2, 3, 4, 5, 6, 7]
        assert manager.current_version == 7
        assert connection.execute("SELECT repository_id FROM repository_metadata").fetchone()[0].startswith("repository:local:")
        assert manager.rollback(1) == [7]
        assert manager.current_version == 6
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='saved_queries'").fetchone() is None
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='review_cases'").fetchone() is not None
        assert manager.migrate() == [7]
        assert manager.current_version == 7


def test_repository_health_reports_current_schema(tmp_path):
    repository = CatalystRepository(tmp_path / "data.db")
    missing = repository.health()
    assert not missing.exists
    assert missing.latest_migration == 7
    repository.initialize()
    health = repository.health()
    assert health.healthy
    assert health.migration_version == 7
    assert health.repository_id


def test_migrations_three_through_five_rebuild_evidence_governance_and_lineage(tmp_path):
    import json
    from catalyst_data.engine import build_record

    repository = CatalystRepository(tmp_path / "upgrade.sqlite3")
    repository.initialize()
    record = build_record(json.loads((ROOT / "examples/sample_project.json").read_text(encoding="utf-8")))
    repository.upsert_record(record)

    assert repository.rollback(5) == [7, 6, 5, 4, 3]
    with connect(repository.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM data_records").fetchone()[0] == 1
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='measurement_sources'").fetchone() is None
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='observation_batches'").fetchone() is None

    assert repository.migrate() == [3, 4, 5, 6, 7]
    evidence = repository.evidence(record["record_id"])
    assert evidence is not None
    assert evidence["summary"]["source_count"] == 2
    assert evidence["summary"]["revision_count"] == 1
    assert repository.stats()["indicator_versions"] == 1
    assert repository.stats()["observations"] == 2
