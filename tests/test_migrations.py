from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

from catalyst_data.database import connect
from catalyst_data.migrations import MigrationManager, discover_migrations
from catalyst_data.repository import CatalystRepository


def test_migrations_are_contiguous_and_reversible(tmp_path):
    assert [item.version for item in discover_migrations()] == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23]
    database = tmp_path / "repository.sqlite3"
    with connect(database) as connection:
        manager = MigrationManager(connection)
        assert manager.current_version == 0
        assert manager.migrate() == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23]
        assert manager.current_version == 23
        assert connection.execute("SELECT repository_id FROM repository_metadata").fetchone()[0].startswith("repository:local:")
        assert manager.rollback(1) == [23]
        assert manager.current_version == 22
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='connected_graph_status'").fetchone() is None
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='entity_registry_status'").fetchone() is not None
        assert manager.rollback(1) == [22]
        assert manager.current_version == 21
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='entity_registry_status'").fetchone() is None
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='dataset_catalog_status'").fetchone() is not None
        assert manager.rollback(1) == [21]
        assert manager.current_version == 20
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='dataset_catalog_status'").fetchone() is None
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='space_science_status'").fetchone() is not None
        assert manager.rollback(1) == [20]
        assert manager.current_version == 19
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='space_science_status'").fetchone() is None
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='earth_climate_ocean_status'").fetchone() is not None
        assert manager.rollback(1) == [19]
        assert manager.current_version == 18
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='earth_climate_ocean_status'").fetchone() is None
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='us_public_data_status'").fetchone() is not None
        assert manager.rollback(1) == [18]
        assert manager.current_version == 17
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='us_public_data_status'").fetchone() is None
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='world_bank_observations'").fetchone() is not None
        assert manager.rollback(1) == [17]
        assert manager.current_version == 16
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='world_bank_observations'").fetchone() is None
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='un_sdg_observations'").fetchone() is None
        assert manager.rollback(1) == [16]
        assert manager.current_version == 15
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='internet_archive_items'").fetchone() is None
        assert manager.rollback(1) == [15]
        assert manager.current_version == 14
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='connector_adapter_bindings'").fetchone() is None
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='storage_backend_metadata'").fetchone() is not None
        assert manager.rollback(1) == [14]
        assert manager.current_version == 13
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='storage_backend_metadata'").fetchone() is None
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='platform_components'").fetchone() is not None
        assert manager.rollback(1) == [13]
        assert manager.current_version == 12
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='platform_components'").fetchone() is None
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='operational_backups'").fetchone() is not None
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='analysis_artifacts'").fetchone() is not None
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='connector_definitions'").fetchone() is not None
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='api_clients'").fetchone() is not None
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='review_cases'").fetchone() is not None
        assert manager.migrate() == [13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23]
        assert manager.current_version == 23


def test_repository_health_reports_current_schema(tmp_path):
    repository = CatalystRepository(tmp_path / "data.db")
    missing = repository.health()
    assert not missing.exists
    assert missing.latest_migration == 23
    repository.initialize()
    health = repository.health()
    assert health.healthy
    assert health.migration_version == 23
    assert health.repository_id


def test_migrations_three_through_five_rebuild_evidence_governance_and_lineage(tmp_path):
    import json
    from catalyst_data.engine import build_record

    repository = CatalystRepository(tmp_path / "upgrade.sqlite3")
    repository.initialize()
    record = build_record(json.loads((ROOT / "examples/sample_project.json").read_text(encoding="utf-8")))
    repository.upsert_record(record)

    assert repository.rollback(21) == [23, 22, 21, 20, 19, 18, 17, 16, 15, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3]
    with connect(repository.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM data_records").fetchone()[0] == 1
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='measurement_sources'").fetchone() is None
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='observation_batches'").fetchone() is None

    assert repository.migrate() == [3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23]
    evidence = repository.evidence(record["record_id"])
    assert evidence is not None
    assert evidence["summary"]["source_count"] == 2
    assert evidence["summary"]["revision_count"] == 1
    assert repository.stats()["indicator_versions"] == 1
    assert repository.stats()["observations"] == 2
