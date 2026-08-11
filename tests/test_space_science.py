from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

from catalyst_data.adapters import default_adapter_registry
from catalyst_data.database import connect
from catalyst_data.public_api import CatalystApiServer
from catalyst_data.repository import CatalystRepository
from catalyst_data.space_science import (
    JPLCloseApproachAdapter,
    JPLSBDBQueryAdapter,
    NASADONKIAdapter,
    NASAExoplanetTAPAdapter,
    SpaceScienceService,
)


class FakeResponse:
    def __init__(self, payload, headers=None):
        self.body = json.dumps(payload).encode("utf-8")
        self.status = 200
        self.headers = headers or {"Content-Type": "application/json"}

    def read(self, n=-1):
        return self.body if n < 0 else self.body[:n]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_space_science_provider_adapters_registered():
    ids = {item["adapter_id"] for item in default_adapter_registry().list()}
    assert {"nasa-donki-space-weather", "jpl-sbdb-query", "jpl-sbdb-close-approach", "nasa-exoplanet-tap"} <= ids


def test_space_provider_url_contracts():
    donki = NASADONKIAdapter()
    cfg = donki.normalize_config({"event_type": "CME", "startDate": "2026-08-01", "endDate": "2026-08-11"})
    q = parse_qs(urlparse(donki.request_uri(cfg, {})).query)
    assert q["startDate"] == ["2026-08-01"] and "api_key" not in q

    sbdb = JPLSBDBQueryAdapter()
    cfg = sbdb.normalize_config({"fields": ["spkid", "full_name", "neo"], "filters": {"sb-neo": "1"}, "limit": 25, "offset": 50})
    q = parse_qs(urlparse(sbdb.request_uri(cfg, {"cursor": 75})).query)
    assert q["fields"] == ["spkid,full_name,neo"] and q["limit"] == ["25"] and q["limit-from"] == ["75"]

    cad = JPLCloseApproachAdapter()
    cfg = cad.normalize_config({"params": {"date-min": "2026-08-01", "body": "Earth", "dist-max": "0.05"}, "limit": 100})
    q = parse_qs(urlparse(cad.request_uri(cfg, {"cursor": 0})).query)
    assert q["body"] == ["Earth"] and q["diameter"] == ["true"] and q["fullname"] == ["true"]

    exo = NASAExoplanetTAPAdapter()
    cfg = exo.normalize_config({"table": "pscomppars", "columns": ["pl_name", "hostname", "pl_rade"], "where": "pl_rade <= 2", "limit": 50})
    q = parse_qs(urlparse(exo.request_uri(cfg, {})).query)
    assert q["format"] == ["json"] and "select top 50 pl_name,hostname,pl_rade from pscomppars where pl_rade <= 2" in q["query"][0]


def test_space_weather_small_bodies_close_approaches_and_exoplanets_are_cached(tmp_path, monkeypatch):
    db = tmp_path / "space.sqlite3"
    monkeypatch.setenv("TEST_NASA_KEY", "secret-nasa-key")
    responses = [
        [{"activityID": "2026-08-11T01:00:00-CME-001", "startTime": "2026-08-11T01:00Z", "sourceLocation": "S10W20", "catalog": "M2M_CATALOG"}],
        {"signature": {"source": "NASA/JPL SBDB Query API", "version": "1.0"}, "fields": ["spkid", "full_name", "pdes", "name", "kind", "class", "neo", "pha", "H", "diameter", "a", "e", "i", "moid", "epoch", "orbit_id"], "data": [["2000433", "433 Eros", "433", "Eros", "an", "AMO", "Y", "N", "10.4", "16.84", "1.458", "0.223", "10.8", "0.148", "2460000.5", "659"]]},
        {"signature": {"source": "NASA/JPL SBDB Close Approach Data API", "version": "1.5"}, "count": 1, "fields": ["des", "orbit_id", "jd", "cd", "dist", "dist_min", "dist_max", "v_rel", "v_inf", "t_sigma_f", "h", "diameter", "diameter_sigma", "fullname"], "data": [["99942", "206", "2462240.407", "2029-Apr-13 21:46", "0.0002541", "0.0002540", "0.0002542", "7.42", "5.84", "< 00:01", "19.7", "0.34", "0.04", "99942 Apophis (2004 MN4)"]]},
        [{"pl_name": "TRAPPIST-1 e", "hostname": "TRAPPIST-1", "discoverymethod": "Transit", "disc_year": 2017, "pl_orbper": 6.1, "pl_rade": 0.92, "pl_masse": 0.69, "st_teff": 2566, "st_rad": 0.12, "sy_dist": 12.43, "ra": 346.62, "dec": -5.04}],
    ]
    calls = []

    def opener(req, timeout=0):
        calls.append(req.full_url)
        return FakeResponse(responses.pop(0))

    svc = SpaceScienceService(CatalystRepository(db), opener=opener, sleeper=lambda _: None)
    assert svc.fetch_donki(event_type="CME", start_date="2026-08-01", end_date="2026-08-11", credential_env="TEST_NASA_KEY")["events"] == 1
    assert svc.fetch_small_bodies(limit=1000, max_pages=1)["objects"] == 1
    assert svc.fetch_close_approaches(limit=1000, max_pages=1)["approaches"] == 1
    assert svc.fetch_exoplanets(limit=100)["planets"] == 1

    assert svc.space_weather_events()[0]["source_native_id"] == "2026-08-11T01:00:00-CME-001"
    body = svc.small_bodies(query="Eros")[0]
    assert body["spkid"] == "2000433" and body["is_neo"] == 1 and body["diameter_km"] == 16.84
    approach = svc.close_approaches(body="Earth")[0]
    assert approach["designation"] == "99942" and approach["distance_au"] == 0.0002541
    planet = svc.exoplanets(query="TRAPPIST")[0]
    assert planet["planet_name"] == "TRAPPIST-1 e" and planet["radius_earth"] == 0.92
    status = svc.status()
    assert status["nasa_space_weather_event_count"] == 1 and status["jpl_small_body_count"] == 1 and status["jpl_close_approach_count"] == 1 and status["nasa_exoplanet_count"] == 1
    assert "secret-nasa-key" in calls[0]
    with connect(db, readonly=True) as connection:
        uris = [row[0] for row in connection.execute("SELECT source_uri FROM space_science_fetches ORDER BY id")]
    assert all("secret-nasa-key" not in uri for uri in uris)
    assert "REDACTED" in uris[0]


def test_migration_twenty_rollback_and_reapply(tmp_path):
    repository = CatalystRepository(tmp_path / "migration20.sqlite3")
    repository.initialize(target=20)
    assert repository.health().migration_version == 20
    with connect(repository.path, readonly=True) as connection:
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='space_science_status'").fetchone()
    assert repository.rollback(1) == [20]
    with connect(repository.path, readonly=True) as connection:
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='space_science_status'").fetchone() is None
    assert repository.migrate(target=20) == [20]


def test_public_space_api_reads_cache_only(tmp_path):
    db = tmp_path / "public-space.sqlite3"
    payload = {"signature": {"version": "1.0"}, "fields": ["spkid", "full_name", "pdes", "name", "kind", "class", "neo", "pha", "H", "diameter", "a", "e", "i", "moid", "epoch", "orbit_id"], "data": [["2000433", "433 Eros", "433", "Eros", "an", "AMO", "Y", "N", "10.4", "16.84", "1.458", "0.223", "10.8", "0.148", "2460000.5", "659"]]}
    svc = SpaceScienceService(CatalystRepository(db), opener=lambda req, timeout=0: FakeResponse(payload), sleeper=lambda _: None)
    svc.fetch_small_bodies(limit=1000, max_pages=1)
    server = CatalystApiServer(("127.0.0.1", 0), svc.repository, allow_origin="https://sustainablecatalyst.com")
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start(); base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with urlopen(base + "/v1/space/small-bodies?query=Eros", timeout=5) as response:
            body = json.loads(response.read())
        assert body["objects"][0]["spkid"] == "2000433"
        with urlopen(base + "/v1/space/status", timeout=5) as response:
            status = json.loads(response.read())
        assert status["jpl_small_body_count"] == 1
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)
