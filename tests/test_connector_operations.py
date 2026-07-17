from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

from catalyst_data.connectors import ConnectorError, ConnectorService
from catalyst_data.database import connect
from catalyst_data.repository import CatalystRepository


def fixture_definition(tmp_path: Path) -> tuple[dict, Path]:
    rows = json.loads((ROOT / "examples/connectors/open_metrics.json").read_text(encoding="utf-8"))
    source = tmp_path / "metrics.json"
    source.write_text(json.dumps(rows), encoding="utf-8")
    definition = json.loads((ROOT / "examples/connectors/open_metrics_connector.json").read_text(encoding="utf-8"))
    definition["source"]["uri"] = str(source)
    definition["schedule"] = {"enabled": False, "frequency_minutes": 60}
    return definition, source


def test_migration_ten_is_reversible_with_existing_records(tmp_path):
    repository = CatalystRepository(tmp_path / "migration.db")
    repository.initialize(target=10)
    assert repository.health().migration_version == 10
    assert repository.rollback(1) == [10]
    with connect(repository.path) as connection:
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='connector_definitions'").fetchone() is None
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='workspaces'").fetchone() is not None
    assert repository.migrate(target=10) == [10]


def test_connector_versions_are_immutable_and_activation_is_append_only(tmp_path):
    repository = CatalystRepository(tmp_path / "versions.db")
    service = ConnectorService(repository)
    definition, _ = fixture_definition(tmp_path)
    first = service.register(definition)
    assert first["version"] == "1.0.0"
    changed = deepcopy(definition)
    changed["governance"]["publisher"] = "Changed publisher"
    with pytest.raises(ConnectorError, match="immutable payload"):
        service.register(changed)
    changed["version"] = "1.0.1"
    second = service.register(changed, activate=False)
    assert second["version"] == "1.0.0"
    activated = service.activate_version(definition["connector_id"], "1.0.1")
    assert activated["version"] == "1.0.1"
    versions = service.versions(definition["connector_id"])
    assert [item["version"] for item in versions] == ["1.0.0", "1.0.1"]
    with connect(repository.path) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("UPDATE connector_versions SET version='9.9.9' WHERE version='1.0.0'")


def test_refresh_detects_inserts_skips_updates_and_population_drift(tmp_path):
    repository = CatalystRepository(tmp_path / "refresh.db")
    service = ConnectorService(repository)
    definition, source = fixture_definition(tmp_path)
    service.register(definition)
    first = service.run(definition["connector_id"])
    assert first["run"]["status"] == "succeeded"
    assert first["run"]["inserted_count"] == 2
    assert first["run"]["freshness_status"] == "current"
    repeated = service.run(definition["connector_id"])
    assert repeated["run"]["skipped_count"] == 2
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["records"][0]["current"] = 88
    payload["records"].pop()
    source.write_text(json.dumps(payload), encoding="utf-8")
    changed = service.run(definition["connector_id"])
    assert changed["run"]["updated_count"] == 1
    assert changed["reconciliation"]["missing_count"] == 1
    assert changed["run"]["drift_status"] == "changed"
    assert any(item["alert_type"] == "record-drift" for item in service.alerts(connector_id=definition["connector_id"]))


def test_invalid_rows_are_quarantined_and_recover_under_new_mapping(tmp_path):
    repository = CatalystRepository(tmp_path / "quarantine.db")
    service = ConnectorService(repository)
    definition, source = fixture_definition(tmp_path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["records"][0].pop("entity_name")
    source.write_text(json.dumps(payload), encoding="utf-8")
    service.register(definition)
    run = service.run(definition["connector_id"])
    assert run["run"]["status"] == "partial"
    items = service.quarantine(connector_id=definition["connector_id"])
    assert len(items) == 1
    corrected = deepcopy(definition)
    corrected["version"] = "1.0.1"
    corrected["mapping"]["entity.name"] = {"source": "entity_name", "default": "Recovered entity"}
    service.register(corrected)
    recovered = service.recover_quarantine(items[0]["quarantine_id"])
    assert recovered["run"]["status"] in ("succeeded", "partial")
    assert service.quarantine(connector_id=definition["connector_id"], status="resolved")


def test_payload_snapshots_support_offline_replay(tmp_path):
    repository = CatalystRepository(tmp_path / "replay.db")
    service = ConnectorService(repository)
    definition, source = fixture_definition(tmp_path)
    service.register(definition)
    first = service.run(definition["connector_id"])
    source.unlink()
    replay = service.replay(first["run"]["run_id"])
    assert replay["run"]["trigger_type"] == "replay"
    assert replay["run"]["status"] == "succeeded"
    assert replay["run"]["skipped_count"] == 2
    with connect(repository.path) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("DELETE FROM connector_payload_snapshots")


def test_schedule_and_rate_limit_are_operationally_visible(tmp_path):
    repository = CatalystRepository(tmp_path / "schedule.db")
    service = ConnectorService(repository)
    definition, _ = fixture_definition(tmp_path)
    definition["governance"]["rate_limit_per_hour"] = 1
    service.register(definition)
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    service.set_schedule(definition["connector_id"], 60, enabled=True, next_run_at=past)
    assert service.due()[0]["connector_id"] == definition["connector_id"]
    first = service.run_due()[0]
    assert first["run"]["status"] == "succeeded"
    limited = service.run(definition["connector_id"])
    assert limited["run"]["status"] == "failed"
    assert any(item["alert_type"] == "rate-limit" for item in service.alerts(connector_id=definition["connector_id"]))


def test_connector_cli_round_trip(tmp_path, capsys):
    from catalyst_data.cli import main

    database = tmp_path / "cli.db"
    definition, _ = fixture_definition(tmp_path)
    definition_path = tmp_path / "connector.json"
    definition_path.write_text(json.dumps(definition), encoding="utf-8")
    assert main(["connector-register", str(database), str(definition_path)]) == 0
    registered = json.loads(capsys.readouterr().out)
    assert registered["connector_id"] == definition["connector_id"]
    assert main(["connector-run", str(database), definition["connector_id"]]) == 0
    run = json.loads(capsys.readouterr().out)
    assert run["run"]["inserted_count"] == 2
    assert main(["connector-runs", str(database), "--connector-id", definition["connector_id"]]) == 0
    assert definition["connector_id"] in capsys.readouterr().out


def test_connector_http_api_is_scoped_and_workspace_bound(tmp_path):
    import threading
    from urllib.error import HTTPError
    from urllib.parse import quote
    from urllib.request import Request, urlopen
    from catalyst_data.public_api import ApiRegistry, CatalystApiServer

    repository = CatalystRepository(tmp_path / "connector-api.db")
    service = ConnectorService(repository)
    definition, _ = fixture_definition(tmp_path)
    service.register(definition)
    key = ApiRegistry(repository).create_key("connector integration", ["connectors:read", "connectors:run"])
    server = CatalystApiServer(("127.0.0.1", 0), repository)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    def call(path, *, method="GET", token=None):
        request = Request(base + path, data=b"{}" if method == "POST" else None, method=method, headers={"Content-Type":"application/json"})
        if token: request.add_header("Authorization", f"Bearer {token}")
        with urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read())
    try:
        with pytest.raises(HTTPError) as denied:
            call("/v1/connectors")
        assert denied.value.code == 401
        status, listing = call("/v1/connectors", token=key["token"])
        assert status == 200 and listing["connectors"][0]["connector_id"] == definition["connector_id"]
        status, result = call(f"/v1/connectors/{quote(definition['connector_id'], safe='')}/run", method="POST", token=key["token"])
        assert status == 200 and result["run"]["inserted_count"] == 2
        status, runs = call("/v1/connectors/runs", token=key["token"])
        assert status == 200 and runs["total"] == 1
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)
