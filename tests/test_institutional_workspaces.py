from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

ROOT = Path(__file__).resolve().parents[1]

from catalyst_data.database import connect
from catalyst_data.engine import build_record
from catalyst_data.public_api import ApiRegistry, CatalystApiServer
from catalyst_data.repository import CatalystRepository
from catalyst_data.workspaces import AccessDenied, WorkspaceService


def sample_record() -> dict:
    return build_record(json.loads((ROOT / "examples/sample_project.json").read_text(encoding="utf-8")))


def make_workspace(repository: CatalystRepository, suffix: str, role: str = "administrator") -> tuple[WorkspaceService, str, str]:
    service = WorkspaceService(repository)
    institution_id = f"institution:{suffix}"
    workspace_id = f"workspace:{suffix}"
    principal_id = f"principal:{suffix}"
    service.create_institution(f"{suffix.title()} Institute", institution_id=institution_id)
    service.create_workspace(institution_id, f"{suffix.title()} Workspace", workspace_id=workspace_id)
    service.create_principal(f"{suffix.title()} User", principal_id=principal_id, email=f"{suffix}@example.org")
    service.add_member(workspace_id, principal_id, role, actor="principal:system")
    return service, workspace_id, principal_id


def request_json(url: str, *, token: str | None = None):
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with urlopen(Request(url, headers=headers), timeout=5) as response:
        return response.status, json.loads(response.read())


def test_migration_009_backfills_existing_records_and_api_keys(tmp_path):
    repository = CatalystRepository(tmp_path / "upgrade.sqlite3")
    repository.initialize()
    record = sample_record(); repository.upsert_record(record)
    assert repository.rollback(1) == [9]
    assert repository.migrate() == [9]
    service = WorkspaceService(repository)
    access = service.record_access(record["record_id"])
    assert access["workspace_id"] == "workspace:default"
    assert access["visibility"] == "private"
    assert repository.stats()["workspaces"] == 1
    assert repository.stats()["record_access_governance"] == 1


def test_roles_enforce_workspace_isolation(tmp_path):
    repository = CatalystRepository(tmp_path / "roles.sqlite3"); repository.initialize()
    service, workspace_a, alice = make_workspace(repository, "alpha", role="contributor")
    _, workspace_b, bob = make_workspace(repository, "beta", role="viewer")
    record = sample_record(); repository.upsert_record(record)
    service.assign_record(record["record_id"], workspace_a, actor=alice, owner_principal_id=alice)
    assert service.authorize(alice, workspace_a, "records:write").role == "contributor"
    with pytest.raises(AccessDenied):
        service.authorize(alice, workspace_b, "records:read")
    with pytest.raises(AccessDenied):
        service.authorize(bob, workspace_b, "records:write")
    assert len(service.records(workspace_a, principal_id=alice)) == 1
    assert service.records(workspace_b, principal_id=bob) == []


def test_visibility_classification_and_public_api_gate(tmp_path):
    repository = CatalystRepository(tmp_path / "public.sqlite3"); repository.initialize()
    record = sample_record(); repository.upsert_record(record)
    record_id = record["record_id"]
    repository.assign_review(record_id, "reviewer@example.org", "coordinator@example.org")
    repository.submit_review(record_id, "author@example.org")
    repository.start_review(record_id, "reviewer@example.org")
    repository.decide_review(record_id, "approved", "reviewer@example.org", reason="Approved")
    with connect(repository.path, readonly=True) as connection:
        assert connection.execute("SELECT COUNT(*) FROM public_api_records").fetchone()[0] == 0
    service = WorkspaceService(repository)
    service.set_visibility(record_id, "public", "public", actor="principal:system")
    with connect(repository.path, readonly=True) as connection:
        assert connection.execute("SELECT COUNT(*) FROM public_api_records").fetchone()[0] == 1
    service.set_visibility(record_id, "public", "restricted", actor="principal:system")
    with connect(repository.path, readonly=True) as connection:
        assert connection.execute("SELECT COUNT(*) FROM public_api_records").fetchone()[0] == 0


def test_retention_legal_hold_and_append_only_audit(tmp_path):
    repository = CatalystRepository(tmp_path / "retention.sqlite3"); repository.initialize()
    service = WorkspaceService(repository)
    record = sample_record(); repository.upsert_record(record)
    record_id = record["record_id"]
    service.set_legal_hold(record_id, True, actor="principal:system", reason="Litigation preservation")
    result = service.can_dispose(record_id, as_of="2099-01-01T00:00:00Z")
    assert not result["eligible"] and "legal hold is active" in result["reasons"]
    service.set_legal_hold(record_id, False, actor="principal:system")
    events = service.events(record_id=record_id)
    assert {event["event_type"] for event in events} >= {"legal_hold_set", "legal_hold_released"}
    connection = sqlite3.connect(repository.path)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        connection.execute("DELETE FROM access_governance_events")
    connection.close()


def test_workspace_transfer_is_immutable_and_preserves_record(tmp_path):
    repository = CatalystRepository(tmp_path / "transfer.sqlite3"); repository.initialize()
    service, workspace_a, alice = make_workspace(repository, "one")
    _, workspace_b, bob = make_workspace(repository, "two")
    record = sample_record(); repository.upsert_record(record)
    service.assign_record(record["record_id"], workspace_a, actor=alice, owner_principal_id=alice)
    service.assign_record(record["record_id"], workspace_b, actor=bob, owner_principal_id=bob)
    assert service.record_access(record["record_id"])["workspace_id"] == workspace_b
    assert repository.get_record(record["record_id"]) is not None
    with connect(repository.path, readonly=True) as connection:
        assert connection.execute("SELECT COUNT(*) FROM workspace_transfer_events").fetchone()[0] == 2
    connection = sqlite3.connect(repository.path)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        connection.execute("UPDATE workspace_transfer_events SET reason='changed'")
    connection.close()


def test_api_key_is_bound_to_one_workspace(tmp_path):
    repository = CatalystRepository(tmp_path / "api.sqlite3"); repository.initialize()
    service, workspace_a, alice = make_workspace(repository, "api-a", role="administrator")
    _, workspace_b, bob = make_workspace(repository, "api-b", role="administrator")
    record = sample_record(); repository.upsert_record(record)
    service.assign_record(record["record_id"], workspace_a, actor=alice, owner_principal_id=alice)
    key = ApiRegistry(repository).create_key("Alpha API", ["records:read", "records:write"], workspace_id=workspace_a, principal_id=alice)
    server = CatalystApiServer(("127.0.0.1", 0), repository)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        status, payload = request_json(base + f"/v1/workspaces/{workspace_a}/records", token=key["token"])
        assert status == 200 and payload["total"] == 1
        with pytest.raises(HTTPError) as exc:
            request_json(base + f"/v1/workspaces/{workspace_b}/records", token=key["token"])
        assert exc.value.code == 403
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)


def test_migration_009_populated_rollback_and_reapply(tmp_path):
    repository = CatalystRepository(tmp_path / "rollback.sqlite3"); repository.initialize()
    record = sample_record(); repository.upsert_record(record)
    assert repository.rollback(1) == [9]
    with connect(repository.path) as connection:
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='workspaces'").fetchone() is None
        assert connection.execute("SELECT COUNT(*) FROM data_records").fetchone()[0] == 1
    assert repository.migrate() == [9]
    assert WorkspaceService(repository).record_access(record["record_id"])["workspace_id"] == "workspace:default"
