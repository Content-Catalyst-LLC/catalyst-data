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
from catalyst_data.earth_climate_ocean import (
    EarthClimateOceanService,
    ERDDAPCatalogAdapter,
    ERDDAPTabledapAdapter,
    IOOSCatalogAdapter,
    NCEICDODataAdapter,
    USGSEarthquakeAdapter,
)
from catalyst_data.public_api import CatalystApiServer
from catalyst_data.repository import CatalystRepository


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


def erddap_table(rows):
    return {"table": {"columnNames": list(rows[0]) if rows else [], "rows": [list(row.values()) for row in rows]}}


def test_earth_network_provider_adapters_registered():
    ids = {item["adapter_id"] for item in default_adapter_registry().list()}
    assert {"noaa-ncei-cdo-v2", "noaa-erddap-catalog", "erddap-tabledap-json", "ioos-data-catalog", "usgs-earthquake-fdsn"} <= ids


def test_provider_url_contracts():
    ncei = NCEICDODataAdapter()
    cfg = ncei.normalize_config({"endpoint": "data", "params": {"datasetid": "GHCND", "startdate": "2026-08-01", "enddate": "2026-08-02"}, "limit": 100})
    q = parse_qs(urlparse(ncei.request_uri(cfg, {"cursor": 1})).query)
    assert q["datasetid"] == ["GHCND"] and q["limit"] == ["100"] and q["offset"] == ["1"]

    erddap = ERDDAPTabledapAdapter()
    cfg = erddap.normalize_config({"server": "https://www.ncei.noaa.gov/erddap", "dataset_id": "sample_dataset", "variables": ["time", "latitude", "longitude", "temperature"], "constraints": ['time>=2026-08-01T00:00:00Z']})
    uri = erddap.request_uri(cfg, {})
    assert "/tabledap/sample_dataset.json?" in uri and "temperature" in uri and "time>=" in uri

    ioos = IOOSCatalogAdapter()
    cfg = ioos.normalize_config({"query": "temperature", "rows": 50, "start": 0})
    q = parse_qs(urlparse(ioos.request_uri(cfg, {"cursor": 50})).query)
    assert q["q"] == ["temperature"] and q["rows"] == ["50"] and q["start"] == ["50"]

    quake = USGSEarthquakeAdapter()
    cfg = quake.normalize_config({"starttime": "2026-08-01", "minmagnitude": 4.5, "limit": 100})
    q = parse_qs(urlparse(quake.request_uri(cfg, {"cursor": 1})).query)
    assert q["format"] == ["geojson"] and q["minmagnitude"] == ["4.5"] and q["offset"] == ["1"]


def test_ncei_and_erddap_observations_are_cached(tmp_path, monkeypatch):
    db = tmp_path / "earth.sqlite3"
    monkeypatch.setenv("TEST_NCEI_TOKEN", "ncei-secret")
    responses = [
        {"metadata": {"resultset": {"offset": 1, "limit": 100, "count": 1}}, "results": [{"date": "2026-08-10T00:00:00", "datatype": "TAVG", "station": "GHCND:USW00094846", "value": 241}]},
        {"table": {"columnNames": ["time", "latitude", "longitude", "station", "sea_surface_temperature"], "rows": [["2026-08-10T12:00:00Z", 41.8, -87.6, "buoy-1", 22.4]]}},
    ]
    calls = []

    def opener(req, timeout=0):
        calls.append((req.full_url, dict(req.headers)))
        return FakeResponse(responses.pop(0))

    svc = EarthClimateOceanService(CatalystRepository(db), opener=opener, sleeper=lambda _: None)
    result = svc.fetch_ncei_cdo(endpoint="data", params={"datasetid": "GHCND"}, limit=100, max_pages=1, credential_env="TEST_NCEI_TOKEN")
    assert result["observations"] == 1
    result = svc.fetch_erddap_tabledap("ocean_temp", ["time", "latitude", "longitude", "station", "sea_surface_temperature"])
    assert result["observations"] == 1
    observations = svc.observations(limit=10)
    assert {item["provider"] for item in observations} == {"ncei", "erddap"}
    assert any(item["metric_code"] == "sea_surface_temperature" and item["latitude"] == 41.8 for item in observations)
    assert calls[0][1].get("Token") == "ncei-secret" or calls[0][1].get("token") == "ncei-secret"
    with connect(db, readonly=True) as connection:
        uris = [row[0] for row in connection.execute("SELECT source_uri FROM earth_climate_fetches ORDER BY id")]
    assert all("ncei-secret" not in uri for uri in uris)


def test_erddap_and_ioos_catalogs_and_earthquakes_are_cached(tmp_path):
    db = tmp_path / "ocean.sqlite3"
    responses = [
        {"table": {"columnNames": ["griddap", "tabledap", "Title", "Institution", "Dataset ID"], "rows": [["https://example/griddap/id", "", "OISST", "NOAA/NCEI", "oisst"]]}},
        {"success": True, "result": {"count": 1, "results": [{"id": "ioos-1", "name": "buoy-temperature", "title": "Buoy Temperature", "organization": {"title": "IOOS"}, "notes": "Ocean observations", "resources": [{"format": "ERDDAP", "url": "https://example/erddap"}]}]}},
        {"type": "FeatureCollection", "features": [{"type": "Feature", "id": "us7000test", "properties": {"time": 1786464000000, "updated": 1786464060000, "mag": 5.2, "magType": "mw", "place": "Test Region", "status": "reviewed", "tsunami": 0, "sig": 417, "alert": "green", "detail": "https://earthquake.usgs.gov/earthquakes/feed/v1.0/detail/us7000test.geojson"}, "geometry": {"type": "Point", "coordinates": [-150.1, 61.2, 18.0]}}]},
    ]

    def opener(req, timeout=0):
        return FakeResponse(responses.pop(0))

    svc = EarthClimateOceanService(CatalystRepository(db), opener=opener, sleeper=lambda _: None)
    assert svc.fetch_erddap_catalog(items_per_page=1000, max_pages=1)["rows"] == 1
    assert svc.fetch_ioos_catalog("temperature", rows=100, max_pages=1)["datasets"] == 1
    assert svc.fetch_usgs_earthquakes(starttime="2026-08-01", limit=100, max_pages=1)["events"] == 1
    assert svc.erddap_datasets(query="OISST")[0]["dataset_id"] == "oisst"
    assert svc.ioos_datasets(query="Buoy")[0]["dataset_id"] == "ioos-1"
    quake = svc.earthquakes(min_magnitude=5.0)[0]
    assert quake["event_id"] == "us7000test" and quake["longitude"] == -150.1 and quake["magnitude"] == 5.2
    status = svc.status()
    assert status["erddap_dataset_count"] == 1 and status["ioos_dataset_count"] == 1 and status["usgs_earthquake_count"] == 1


def test_migration_nineteen_rollback_and_reapply(tmp_path):
    repository = CatalystRepository(tmp_path / "migration19.sqlite3")
    repository.initialize(target=19)
    assert repository.health().migration_version == 19
    with connect(repository.path, readonly=True) as connection:
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='earth_climate_ocean_status'").fetchone()
    assert repository.rollback(1) == [19]
    with connect(repository.path, readonly=True) as connection:
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='earth_climate_ocean_status'").fetchone() is None
    assert repository.migrate(target=19) == [19]


def test_public_earth_api_reads_cache_only(tmp_path):
    db = tmp_path / "public.sqlite3"
    payload = {"type": "FeatureCollection", "features": [{"type": "Feature", "id": "event-1", "properties": {"time": 1786464000000, "mag": 6.1, "place": "Example"}, "geometry": {"type": "Point", "coordinates": [10.0, 20.0, 5.0]}}]}
    svc = EarthClimateOceanService(CatalystRepository(db), opener=lambda req, timeout=0: FakeResponse(payload), sleeper=lambda _: None)
    svc.fetch_usgs_earthquakes(limit=100, max_pages=1)
    server = CatalystApiServer(("127.0.0.1", 0), svc.repository, allow_origin="https://sustainablecatalyst.com")
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start(); base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with urlopen(base + "/v1/earth/earthquakes?min_magnitude=6", timeout=5) as response:
            body = json.loads(response.read())
        assert body["events"][0]["event_id"] == "event-1"
        with urlopen(base + "/v1/earth/status", timeout=5) as response:
            status = json.loads(response.read())
        assert status["usgs_earthquake_count"] == 1
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)
