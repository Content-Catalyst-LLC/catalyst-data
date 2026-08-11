from __future__ import annotations

import hashlib
import json
import re
import secrets
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Iterable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from ._version import __version__
from .adapters import AdapterManifest, AdapterValidationError, SourceAdapter
from .connectors import ConnectorFetchError
from .database import connect, transaction
from .repository import CatalystRepository, canonical_json

WORLD_BANK_BASE = "https://api.worldbank.org/v2"
UN_SDG_BASE = "https://unstats.un.org/SDGAPI/v1/sdg"
MAX_RESPONSE_BYTES = 20_000_000


class GlobalStatisticsError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha(value: bytes | Mapping[str, Any] | list[Any]) -> str:
    raw = value if isinstance(value, bytes) else canonical_json(value).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _id(prefix: str) -> str:
    return f"{prefix}:" + secrets.token_hex(12)


def _stable_id(prefix: str, *parts: Any) -> str:
    digest = hashlib.sha256("|".join("" if p is None else str(p) for p in parts).encode("utf-8")).hexdigest()[:32]
    return f"{prefix}:{digest}"


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        for key in ("value", "name", "title", "description"):
            if value.get(key) not in (None, ""):
                return str(value[key])
        return canonical_json(dict(value))
    if isinstance(value, list):
        return "; ".join(str(x) for x in value if x is not None) or None
    text = str(value).strip()
    return text or None


def _numeric(value: Any) -> float | None:
    if value in (None, "", "NA", "N/A", "null"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _list_payload(payload: Any, *keys: str) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [dict(row) for row in payload if isinstance(row, Mapping)]
    if isinstance(payload, Mapping):
        for key in keys:
            value = payload.get(key)
            if isinstance(value, list):
                return [dict(row) for row in value if isinstance(row, Mapping)]
        for value in payload.values():
            if isinstance(value, list) and all(isinstance(row, Mapping) for row in value):
                return [dict(row) for row in value]
    return []


class WorldBankCountriesAdapter(SourceAdapter):
    manifest = AdapterManifest(
        adapter_id="world-bank-countries",
        name="World Bank Countries Adapter",
        version="1.0.0",
        provider="world-bank",
        response_format="json",
        capabilities=("read", "country-catalog", "pagination", "provenance"),
        pagination=("page",),
        description="World Bank v2 country and classification catalog.",
    )

    def normalize_config(self, config: Mapping[str, Any]) -> dict[str, Any]:
        per_page = int(config.get("per_page") or 400)
        if not 1 <= per_page <= 2000:
            raise AdapterValidationError("config.per_page must be between 1 and 2000")
        page = int(config.get("page") or 1)
        if page < 1:
            raise AdapterValidationError("config.page must be positive")
        return {"per_page": per_page, "page": page, "pagination": {"type": "page", "start": page}}

    def request_uri(self, config: Mapping[str, Any], state: Mapping[str, Any]) -> str:
        page = int(state.get("cursor") or config["page"])
        return WORLD_BANK_BASE + "/country?" + urlencode({"format": "json", "per_page": config["per_page"], "page": page})

    def parse_page(self, body: bytes, headers: Mapping[str, str], config: Mapping[str, Any], state: Mapping[str, Any]):
        payload = json.loads(body.decode("utf-8-sig"))
        if not isinstance(payload, list) or len(payload) < 2:
            raise AdapterValidationError("World Bank response must contain metadata and records")
        meta = payload[0] if isinstance(payload[0], Mapping) else {}
        rows = _list_payload(payload[1])
        page = int(meta.get("page") or state.get("cursor") or config["page"])
        pages = int(meta.get("pages") or page)
        return rows, page + 1 if page < pages else None


class WorldBankIndicatorsAdapter(SourceAdapter):
    manifest = AdapterManifest(
        adapter_id="world-bank-indicators",
        name="World Bank Indicators Adapter",
        version="1.0.0",
        provider="world-bank",
        response_format="json",
        capabilities=("read", "indicator-catalog", "pagination", "provenance"),
        pagination=("page",),
        description="World Bank v2 indicator metadata catalog.",
    )

    def normalize_config(self, config: Mapping[str, Any]) -> dict[str, Any]:
        per_page = int(config.get("per_page") or 1000)
        if not 1 <= per_page <= 20000:
            raise AdapterValidationError("config.per_page must be between 1 and 20000")
        page = int(config.get("page") or 1)
        if page < 1:
            raise AdapterValidationError("config.page must be positive")
        return {"per_page": per_page, "page": page, "pagination": {"type": "page", "start": page}}

    def request_uri(self, config: Mapping[str, Any], state: Mapping[str, Any]) -> str:
        page = int(state.get("cursor") or config["page"])
        return WORLD_BANK_BASE + "/indicator?" + urlencode({"format": "json", "per_page": config["per_page"], "page": page})

    def parse_page(self, body: bytes, headers: Mapping[str, str], config: Mapping[str, Any], state: Mapping[str, Any]):
        return WorldBankCountriesAdapter().parse_page(body, headers, config, state)


class WorldBankIndicatorDataAdapter(SourceAdapter):
    manifest = AdapterManifest(
        adapter_id="world-bank-indicator-data",
        name="World Bank Indicator Data Adapter",
        version="1.0.0",
        provider="world-bank",
        response_format="json",
        capabilities=("read", "indicator-observations", "time-series", "pagination", "footnotes", "provenance"),
        pagination=("page",),
        description="World Bank v2 country/indicator observations with period and source metadata.",
    )

    def normalize_config(self, config: Mapping[str, Any]) -> dict[str, Any]:
        countries = str(config.get("countries") or config.get("country") or "all").strip()
        if not re.fullmatch(r"[A-Za-z0-9;_-]+", countries):
            raise AdapterValidationError("config.countries contains invalid characters")
        indicator = str(config.get("indicator") or "").strip()
        if not indicator or not re.fullmatch(r"[A-Za-z0-9._;-]+", indicator):
            raise AdapterValidationError("config.indicator is invalid")
        date = str(config.get("date") or "").strip() or None
        if date and not re.fullmatch(r"[0-9A-Za-z:.-]+", date):
            raise AdapterValidationError("config.date is invalid")
        per_page = int(config.get("per_page") or 1000)
        if not 1 <= per_page <= 20000:
            raise AdapterValidationError("config.per_page must be between 1 and 20000")
        page = int(config.get("page") or 1)
        return {"countries": countries, "indicator": indicator, "date": date, "per_page": per_page, "page": page, "footnote": bool(config.get("footnote", True)), "pagination": {"type": "page", "start": page}}

    def request_uri(self, config: Mapping[str, Any], state: Mapping[str, Any]) -> str:
        page = int(state.get("cursor") or config["page"])
        params: dict[str, Any] = {"format": "json", "per_page": config["per_page"], "page": page}
        if config.get("date"):
            params["date"] = config["date"]
        if config.get("footnote"):
            params["footnote"] = "y"
        return f"{WORLD_BANK_BASE}/country/{quote(str(config['countries']), safe=';')}/indicator/{quote(str(config['indicator']), safe=';.')}?" + urlencode(params)

    def parse_page(self, body: bytes, headers: Mapping[str, str], config: Mapping[str, Any], state: Mapping[str, Any]):
        return WorldBankCountriesAdapter().parse_page(body, headers, config, state)


class UNSDGGeoAreasAdapter(SourceAdapter):
    manifest = AdapterManifest(
        adapter_id="un-sdg-geoareas",
        name="UNSD SDG GeoArea Adapter",
        version="1.0.0",
        provider="un-sdg",
        response_format="json",
        capabilities=("read", "m49-geography", "catalog", "provenance"),
        pagination=("none",),
        description="UNSD SDG geography catalog preserving M49 geoAreaCode values.",
    )
    def normalize_config(self, config: Mapping[str, Any]) -> dict[str, Any]: return {"pagination": {"type": "none"}}
    def request_uri(self, config: Mapping[str, Any], state: Mapping[str, Any]) -> str: return UN_SDG_BASE + "/GeoArea/List"
    def parse_page(self, body: bytes, headers: Mapping[str, str], config: Mapping[str, Any], state: Mapping[str, Any]):
        payload=json.loads(body.decode("utf-8-sig")); return _list_payload(payload,"data","geoAreas","items"), None


class UNSDGGoalsAdapter(SourceAdapter):
    manifest = AdapterManifest(
        adapter_id="un-sdg-goals",
        name="UNSD SDG Goals Adapter",
        version="1.0.0",
        provider="un-sdg",
        response_format="json",
        capabilities=("read", "sdg-goals", "catalog", "provenance"),
        pagination=("none",),
        description="UNSD SDG goals catalog from the current published release.",
    )
    def normalize_config(self, config: Mapping[str, Any]) -> dict[str, Any]: return {"includechildren": bool(config.get("includechildren", True)), "pagination": {"type": "none"}}
    def request_uri(self, config: Mapping[str, Any], state: Mapping[str, Any]) -> str: return UN_SDG_BASE + "/Goal/List?" + urlencode({"includechildren": str(config["includechildren"]).lower()})
    def parse_page(self, body: bytes, headers: Mapping[str, str], config: Mapping[str, Any], state: Mapping[str, Any]):
        payload=json.loads(body.decode("utf-8-sig")); return _list_payload(payload,"data","goals","items"), None


class UNSDGIndicatorsAdapter(SourceAdapter):
    manifest = AdapterManifest(
        adapter_id="un-sdg-indicators",
        name="UNSD SDG Indicators Adapter",
        version="1.0.0",
        provider="un-sdg",
        response_format="json",
        capabilities=("read", "sdg-indicators", "series-metadata", "catalog", "provenance"),
        pagination=("none",),
        description="UNSD SDG indicator and published-series catalog.",
    )
    def normalize_config(self, config: Mapping[str, Any]) -> dict[str, Any]: return {"pagination": {"type": "none"}}
    def request_uri(self, config: Mapping[str, Any], state: Mapping[str, Any]) -> str: return UN_SDG_BASE + "/Indicator/List"
    def parse_page(self, body: bytes, headers: Mapping[str, str], config: Mapping[str, Any], state: Mapping[str, Any]):
        payload=json.loads(body.decode("utf-8-sig")); return _list_payload(payload,"data","indicators","items"), None


class UNSDGIndicatorDataAdapter(SourceAdapter):
    manifest = AdapterManifest(
        adapter_id="un-sdg-indicator-data",
        name="UNSD SDG Indicator Data Adapter",
        version="1.0.0",
        provider="un-sdg",
        response_format="json",
        capabilities=("read", "indicator-observations", "time-series", "m49-geography", "dimensions", "pagination", "provenance"),
        pagination=("page",),
        description="UNSD SDG paginated indicator observations with M49 geography and disaggregation dimensions.",
    )
    def normalize_config(self, config: Mapping[str, Any]) -> dict[str, Any]:
        indicators=[str(x).strip() for x in (config.get("indicators") or [config.get("indicator")]) if str(x or "").strip()]
        if not indicators or any(not re.fullmatch(r"[0-9A-Za-z._-]+", x) for x in indicators): raise AdapterValidationError("config.indicators is required and contains invalid values")
        areas=[str(x).strip() for x in (config.get("area_codes") or config.get("areaCode") or []) if str(x or "").strip()]
        if any(not re.fullmatch(r"\d{1,4}", x) for x in areas): raise AdapterValidationError("config.area_codes must contain M49 numeric codes")
        start=config.get("time_period_start"); end=config.get("time_period_end")
        if start is not None and int(start) < 1800: raise AdapterValidationError("time_period_start is invalid")
        if end is not None and int(end) < 1800: raise AdapterValidationError("time_period_end is invalid")
        page_size=int(config.get("page_size") or 100)
        if not 1 <= page_size <= 1000: raise AdapterValidationError("config.page_size must be between 1 and 1000")
        page=int(config.get("page") or 1)
        return {"indicators":indicators,"area_codes":areas,"time_period_start":int(start) if start is not None else None,"time_period_end":int(end) if end is not None else None,"page_size":page_size,"page":page,"pagination":{"type":"page","start":page}}
    def request_uri(self, config: Mapping[str, Any], state: Mapping[str, Any]) -> str:
        page=int(state.get("cursor") or config["page"]); params=[]
        params += [("indicator",x) for x in config["indicators"]]; params += [("areaCode",x) for x in config["area_codes"]]
        if config.get("time_period_start") is not None: params.append(("timePeriodStart",str(config["time_period_start"])))
        if config.get("time_period_end") is not None: params.append(("timePeriodEnd",str(config["time_period_end"])))
        params += [("page",str(page)),("pageSize",str(config["page_size"]))]
        return UN_SDG_BASE + "/Indicator/Data?" + urlencode(params)
    def parse_page(self, body: bytes, headers: Mapping[str, str], config: Mapping[str, Any], state: Mapping[str, Any]):
        payload=json.loads(body.decode("utf-8-sig")); rows=_list_payload(payload,"data","Data","observations","items")
        page=int(state.get("cursor") or config["page"]); next_page=None
        if isinstance(payload,Mapping):
            current=int(payload.get("page") or payload.get("pageNumber") or page)
            total_pages=payload.get("totalPages") or payload.get("pages")
            total_elements=payload.get("totalElements") or payload.get("total") or payload.get("totalCount")
            if total_pages is not None: next_page=current+1 if current < int(total_pages) else None
            elif total_elements is not None: next_page=current+1 if current*int(config["page_size"]) < int(total_elements) else None
            elif len(rows) >= int(config["page_size"]): next_page=current+1
        elif len(rows) >= int(config["page_size"]): next_page=page+1
        return rows,next_page


class GlobalStatisticsService:
    def __init__(self, repository: CatalystRepository | str, *, opener: Callable[..., Any] | None=None, sleeper: Callable[[float],None] | None=None):
        self.repository=repository if isinstance(repository,CatalystRepository) else CatalystRepository(repository)
        self.repository.initialize(); self.opener=opener or urlopen; self.sleeper=sleeper or time.sleep

    @staticmethod
    def user_agent() -> str:
        return f"SustainableCatalyst-CatalystData/{__version__} (+https://sustainablecatalyst.com/; GlobalStatisticsAdapter)"

    def _fetch(self, uri: str, *, provider: str, timeout: int=30, retries: int=3) -> tuple[bytes,dict[str,str]]:
        headers={"User-Agent":self.user_agent(),"Accept":"application/json,text/plain;q=0.9,*/*;q=0.5"}
        for attempt in range(1,max(1,retries)+1):
            try:
                with self.opener(Request(uri,headers=headers),timeout=timeout) as response:
                    body=response.read(MAX_RESPONSE_BYTES+1)
                    if len(body)>MAX_RESPONSE_BYTES: raise ConnectorFetchError(f"{provider} response exceeds the 20 MB safety limit",transient=False)
                    return body,{str(k):str(v) for k,v in response.headers.items()}
            except HTTPError as exc:
                transient=exc.code==429 or 500<=exc.code<600
                if not transient or attempt>=retries: raise ConnectorFetchError(f"{provider} HTTP {exc.code}: {exc.reason}",transient=transient,status=exc.code) from exc
                delay=None; raw=exc.headers.get("Retry-After") if exc.headers else None
                if raw and str(raw).isdigit(): delay=min(60,max(1,int(raw)))
                elif raw:
                    try:
                        at=parsedate_to_datetime(str(raw)); at=at if at.tzinfo else at.replace(tzinfo=timezone.utc); delay=min(60,max(1,int((at-datetime.now(timezone.utc)).total_seconds())))
                    except (TypeError,ValueError,OverflowError): delay=None
                self.sleeper(float(delay or min(2**(attempt-1),8)))
            except URLError as exc:
                if attempt>=retries: raise ConnectorFetchError(f"{provider} network error: {exc.reason}",transient=True) from exc
                self.sleeper(float(min(2**(attempt-1),8)))
        raise GlobalStatisticsError(f"{provider} request failed")

    def _record_fetch(self,c,*,provider:str,resource_type:str,request:Mapping[str,Any],body:bytes,source_uri:str,result_count:int,now:str) -> None:
        c.execute("INSERT INTO global_statistics_fetches(fetch_id,provider,resource_type,request_json,result_count,response_sha256,source_uri,fetched_at) VALUES (?,?,?,?,?,?,?,?)",(_id("stats-fetch"),provider,resource_type,canonical_json(dict(request)),int(result_count),_sha(body),source_uri,now))

    def fetch_world_bank_countries(self, *, per_page:int=400, max_pages:int=5) -> dict[str,Any]:
        adapter=WorldBankCountriesAdapter(); config=adapter.normalize_config({"per_page":per_page}); cursor=config["page"]; total=0; pages=0
        while cursor is not None and pages<max(1,max_pages):
            uri=adapter.request_uri(config,{"cursor":cursor}); body,headers=self._fetch(uri,provider="World Bank"); rows,next_cursor=adapter.parse_page(body,headers,config,{"cursor":cursor}); now=_now()
            with connect(self.repository.path) as c, transaction(c):
                self._record_fetch(c,provider="world-bank",resource_type="countries",request={"page":cursor,"per_page":per_page},body=body,source_uri=uri,result_count=len(rows),now=now)
                for row in rows:
                    code=str(row.get("id") or row.get("iso2Code") or "").strip()
                    name=str(row.get("name") or "").strip()
                    if not code or not name: continue
                    region=row.get("region") if isinstance(row.get("region"),Mapping) else {}; income=row.get("incomeLevel") if isinstance(row.get("incomeLevel"),Mapping) else {}; lending=row.get("lendingType") if isinstance(row.get("lendingType"),Mapping) else {}
                    c.execute("INSERT INTO world_bank_countries(country_code,iso2_code,name,region_code,region_name,income_level_code,income_level_name,lending_type_code,lending_type_name,capital_city,longitude,latitude,metadata_json,source_uri,fetched_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(country_code) DO UPDATE SET iso2_code=excluded.iso2_code,name=excluded.name,region_code=excluded.region_code,region_name=excluded.region_name,income_level_code=excluded.income_level_code,income_level_name=excluded.income_level_name,lending_type_code=excluded.lending_type_code,lending_type_name=excluded.lending_type_name,capital_city=excluded.capital_city,longitude=excluded.longitude,latitude=excluded.latitude,metadata_json=excluded.metadata_json,source_uri=excluded.source_uri,fetched_at=excluded.fetched_at,updated_at=excluded.updated_at",(code,_text(row.get("iso2Code")),name,_text(region.get("id")),_text(region.get("value")),_text(income.get("id")),_text(income.get("value")),_text(lending.get("id")),_text(lending.get("value")),_text(row.get("capitalCity")),_text(row.get("longitude")),_text(row.get("latitude")),canonical_json(row),uri,now,now))
            total+=len(rows); pages+=1; cursor=next_cursor
        return {"provider":"world-bank","resource":"countries","pages":pages,"records":total,"status":self.status()}

    def fetch_world_bank_indicators(self, *, per_page:int=1000, max_pages:int=50) -> dict[str,Any]:
        adapter=WorldBankIndicatorsAdapter(); config=adapter.normalize_config({"per_page":per_page}); cursor=config["page"]; total=0; pages=0
        while cursor is not None and pages<max(1,max_pages):
            uri=adapter.request_uri(config,{"cursor":cursor}); body,headers=self._fetch(uri,provider="World Bank"); rows,next_cursor=adapter.parse_page(body,headers,config,{"cursor":cursor}); now=_now()
            with connect(self.repository.path) as c, transaction(c):
                self._record_fetch(c,provider="world-bank",resource_type="indicators",request={"page":cursor,"per_page":per_page},body=body,source_uri=uri,result_count=len(rows),now=now)
                for row in rows:
                    code=str(row.get("id") or "").strip(); name=str(row.get("name") or "").strip()
                    if not code or not name: continue
                    source=row.get("source") if isinstance(row.get("source"),Mapping) else {}; topics=row.get("topics") if isinstance(row.get("topics"),list) else []
                    c.execute("INSERT INTO world_bank_indicators(indicator_code,name,unit,source_id,source_note,source_organization,topics_json,metadata_json,source_uri,fetched_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(indicator_code) DO UPDATE SET name=excluded.name,unit=excluded.unit,source_id=excluded.source_id,source_note=excluded.source_note,source_organization=excluded.source_organization,topics_json=excluded.topics_json,metadata_json=excluded.metadata_json,source_uri=excluded.source_uri,fetched_at=excluded.fetched_at,updated_at=excluded.updated_at",(code,name,_text(row.get("unit")),_text(source.get("id")),_text(row.get("sourceNote")),_text(row.get("sourceOrganization")),canonical_json(topics),canonical_json(row),uri,now,now))
            total+=len(rows); pages+=1; cursor=next_cursor
        return {"provider":"world-bank","resource":"indicators","pages":pages,"records":total,"status":self.status()}

    def fetch_world_bank_data(self, countries:str, indicator:str, *, date:str|None=None, per_page:int=1000, max_pages:int=25, footnote:bool=True) -> dict[str,Any]:
        adapter=WorldBankIndicatorDataAdapter(); config=adapter.normalize_config({"countries":countries,"indicator":indicator,"date":date,"per_page":per_page,"footnote":footnote}); cursor=config["page"]; total=0; pages=0
        while cursor is not None and pages<max(1,max_pages):
            uri=adapter.request_uri(config,{"cursor":cursor}); body,headers=self._fetch(uri,provider="World Bank"); rows,next_cursor=adapter.parse_page(body,headers,config,{"cursor":cursor}); now=_now()
            with connect(self.repository.path) as c, transaction(c):
                self._record_fetch(c,provider="world-bank",resource_type="observations",request={"countries":countries,"indicator":indicator,"date":date,"page":cursor},body=body,source_uri=uri,result_count=len(rows),now=now)
                for row in rows:
                    country=row.get("country") if isinstance(row.get("country"),Mapping) else {}; indicator_obj=row.get("indicator") if isinstance(row.get("indicator"),Mapping) else {}
                    country_code=str(row.get("countryiso3code") or row.get("country_id") or country.get("id") or "").strip(); indicator_code=str(indicator_obj.get("id") or indicator).strip(); period=str(row.get("date") or "").strip(); source_id=_text(row.get("source")) or ""
                    if not country_code or not indicator_code or not period: continue
                    dimensions={k:row.get(k) for k in ("unit","obs_status","decimal") if k in row}
                    value=row.get("value"); value_num=_numeric(value); value_text=None if value_num is not None or value is None else _text(value)
                    obs_id=_stable_id("wb-observation",country_code,indicator_code,period,source_id)
                    existing=c.execute("SELECT first_seen_at FROM world_bank_observations WHERE country_code=? AND indicator_code=? AND period=? AND source_id=?",(country_code,indicator_code,period,source_id)).fetchone(); first_seen=existing["first_seen_at"] if existing else now
                    c.execute("INSERT INTO world_bank_observations(observation_id,country_code,country_name,indicator_code,indicator_name,period,value_numeric,value_text,unit,decimal_places,obs_status,footnote,source_id,raw_json,source_uri,first_seen_at,fetched_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(country_code,indicator_code,period,source_id) DO UPDATE SET country_name=excluded.country_name,indicator_name=excluded.indicator_name,value_numeric=excluded.value_numeric,value_text=excluded.value_text,unit=excluded.unit,decimal_places=excluded.decimal_places,obs_status=excluded.obs_status,footnote=excluded.footnote,raw_json=excluded.raw_json,source_uri=excluded.source_uri,fetched_at=excluded.fetched_at,updated_at=excluded.updated_at",(obs_id,country_code,_text(country.get("value")),indicator_code,_text(indicator_obj.get("value")),period,value_num,value_text,_text(row.get("unit")),int(row.get("decimal")) if str(row.get("decimal") or "").isdigit() else None,_text(row.get("obs_status")),_text(row.get("footnote")),source_id,canonical_json(row),uri,first_seen,now,now))
            total+=len(rows); pages+=1; cursor=next_cursor
        return {"provider":"world-bank","resource":"observations","countries":countries,"indicator":indicator,"date":date,"pages":pages,"records":total}

    def fetch_un_sdg_catalog(self, *, include_children:bool=True) -> dict[str,Any]:
        specs=[("geoareas",UNSDGGeoAreasAdapter(),{}),("goals",UNSDGGoalsAdapter(),{"includechildren":include_children}),("indicators",UNSDGIndicatorsAdapter(),{})]; counts={}
        for resource,adapter,raw_config in specs:
            config=adapter.normalize_config(raw_config); uri=adapter.request_uri(config,{}); body,headers=self._fetch(uri,provider="UNSD SDG"); rows,_=adapter.parse_page(body,headers,config,{}); now=_now(); counts[resource]=len(rows)
            with connect(self.repository.path) as c, transaction(c):
                self._record_fetch(c,provider="un-sdg",resource_type=resource,request=raw_config,body=body,source_uri=uri,result_count=len(rows),now=now)
                if resource=="geoareas":
                    for row in rows:
                        code=str(row.get("geoAreaCode") or row.get("code") or row.get("id") or "").strip(); name=str(row.get("geoAreaName") or row.get("name") or row.get("title") or "").strip()
                        if not code or not name: continue
                        c.execute("INSERT INTO un_sdg_geoareas(geo_area_code,geo_area_name,type_code,parent_code,metadata_json,source_uri,fetched_at,updated_at) VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(geo_area_code) DO UPDATE SET geo_area_name=excluded.geo_area_name,type_code=excluded.type_code,parent_code=excluded.parent_code,metadata_json=excluded.metadata_json,source_uri=excluded.source_uri,fetched_at=excluded.fetched_at,updated_at=excluded.updated_at",(code,name,_text(row.get("type")),_text(row.get("parentCode") or row.get("parent")),canonical_json(row),uri,now,now))
                elif resource=="goals":
                    for row in rows:
                        code=str(row.get("code") or row.get("goalCode") or row.get("id") or "").strip(); title=str(row.get("title") or row.get("description") or row.get("name") or "").strip()
                        if not code or not title: continue
                        c.execute("INSERT INTO un_sdg_goals(goal_code,title,description,metadata_json,source_uri,fetched_at,updated_at) VALUES (?,?,?,?,?,?,?) ON CONFLICT(goal_code) DO UPDATE SET title=excluded.title,description=excluded.description,metadata_json=excluded.metadata_json,source_uri=excluded.source_uri,fetched_at=excluded.fetched_at,updated_at=excluded.updated_at",(code,title,_text(row.get("description")),canonical_json(row),uri,now,now))
                else:
                    for row in rows:
                        code=str(row.get("code") or row.get("indicatorCode") or row.get("id") or "").strip(); desc=str(row.get("description") or row.get("title") or row.get("name") or "").strip()
                        if not code or not desc: continue
                        series=row.get("series") if isinstance(row.get("series"),list) else row.get("seriesList") if isinstance(row.get("seriesList"),list) else []
                        c.execute("INSERT INTO un_sdg_indicators(indicator_code,description,goal_code,target_code,series_json,metadata_json,source_uri,fetched_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(indicator_code) DO UPDATE SET description=excluded.description,goal_code=excluded.goal_code,target_code=excluded.target_code,series_json=excluded.series_json,metadata_json=excluded.metadata_json,source_uri=excluded.source_uri,fetched_at=excluded.fetched_at,updated_at=excluded.updated_at",(code,desc,_text(row.get("goal") or row.get("goalCode")),_text(row.get("target") or row.get("targetCode")),canonical_json(series),canonical_json(row),uri,now,now))
        return {"provider":"un-sdg","resource":"catalog","counts":counts,"status":self.status()}

    def fetch_un_sdg_data(self, indicators:Sequence[str]|str, *, area_codes:Sequence[str|int]=(), time_period_start:int|None=None, time_period_end:int|None=None, page_size:int=100, max_pages:int=25) -> dict[str,Any]:
        indicator_list=[indicators] if isinstance(indicators,str) else list(indicators); adapter=UNSDGIndicatorDataAdapter(); config=adapter.normalize_config({"indicators":indicator_list,"area_codes":list(area_codes),"time_period_start":time_period_start,"time_period_end":time_period_end,"page_size":page_size}); cursor=config["page"]; total=0; pages=0
        while cursor is not None and pages<max(1,max_pages):
            uri=adapter.request_uri(config,{"cursor":cursor}); body,headers=self._fetch(uri,provider="UNSD SDG"); rows,next_cursor=adapter.parse_page(body,headers,config,{"cursor":cursor}); now=_now()
            with connect(self.repository.path) as c, transaction(c):
                self._record_fetch(c,provider="un-sdg",resource_type="observations",request={"indicators":indicator_list,"area_codes":[str(x) for x in area_codes],"time_period_start":time_period_start,"time_period_end":time_period_end,"page":cursor},body=body,source_uri=uri,result_count=len(rows),now=now)
                for row in rows:
                    indicator_code=_text(row.get("indicator") or row.get("indicatorCode")); series_code=_text(row.get("seriesCode") or row.get("series")); area_code=_text(row.get("geoAreaCode") or row.get("areaCode")); period=_text(row.get("timePeriod") or row.get("year") or row.get("period")); nature=_text(row.get("nature") or row.get("natureCode")) or ""
                    if not series_code and indicator_code: series_code=indicator_code
                    if not series_code or not area_code or not period: continue
                    dimensions=row.get("dimensions") if isinstance(row.get("dimensions"),Mapping) else {}
                    for key in ("sex","age","location","educationLevel","typeOfProduct","typeOfOccupation","reportingType"):
                        if row.get(key) not in (None,""): dimensions[key]=row.get(key)
                    dimensions_json=canonical_json(dimensions); value=row.get("value") if "value" in row else row.get("valueNumeric"); value_num=_numeric(value); value_text=None if value_num is not None or value is None else _text(value)
                    obs_id=_stable_id("un-sdg-observation",series_code,area_code,period,dimensions_json,nature)
                    existing=c.execute("SELECT first_seen_at FROM un_sdg_observations WHERE series_code=? AND geo_area_code=? AND time_period=? AND dimensions_json=? AND nature_code=?",(series_code,area_code,period,dimensions_json,nature)).fetchone(); first_seen=existing["first_seen_at"] if existing else now
                    c.execute("INSERT INTO un_sdg_observations(observation_id,indicator_code,series_code,series_description,geo_area_code,geo_area_name,time_period,value_numeric,value_text,units,nature_code,dimensions_json,raw_json,source_uri,first_seen_at,fetched_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(series_code,geo_area_code,time_period,dimensions_json,nature_code) DO UPDATE SET indicator_code=excluded.indicator_code,series_description=excluded.series_description,geo_area_name=excluded.geo_area_name,value_numeric=excluded.value_numeric,value_text=excluded.value_text,units=excluded.units,raw_json=excluded.raw_json,source_uri=excluded.source_uri,fetched_at=excluded.fetched_at,updated_at=excluded.updated_at",(obs_id,indicator_code,series_code,_text(row.get("seriesDescription") or row.get("seriesDesc")),area_code,_text(row.get("geoAreaName") or row.get("areaName")),period,value_num,value_text,_text(row.get("units") or row.get("unit")),nature,dimensions_json,canonical_json(row),uri,first_seen,now,now))
            total+=len(rows); pages+=1; cursor=next_cursor
        return {"provider":"un-sdg","resource":"observations","indicators":indicator_list,"area_codes":[str(x) for x in area_codes],"pages":pages,"records":total}

    def world_bank_observations(self, *, country:str|None=None, indicator:str|None=None, start_period:str|None=None, end_period:str|None=None, limit:int=100, offset:int=0) -> list[dict[str,Any]]:
        clauses=[]; params:list[Any]=[]
        if country: clauses.append("country_code=?"); params.append(country)
        if indicator: clauses.append("indicator_code=?"); params.append(indicator)
        if start_period: clauses.append("period>=?"); params.append(start_period)
        if end_period: clauses.append("period<=?"); params.append(end_period)
        sql="SELECT observation_id,country_code,country_name,indicator_code,indicator_name,period,value_numeric,value_text,unit,decimal_places,obs_status,footnote,source_id,source_uri,fetched_at FROM world_bank_observations" + (" WHERE "+" AND ".join(clauses) if clauses else "") + " ORDER BY period DESC,country_code,indicator_code LIMIT ? OFFSET ?"; params += [max(1,min(500,limit)),max(0,offset)]
        with connect(self.repository.path,readonly=True) as c: return [dict(row) for row in c.execute(sql,params)]

    def un_sdg_observations(self, *, indicator:str|None=None, series:str|None=None, area_code:str|None=None, start_period:str|None=None, end_period:str|None=None, limit:int=100, offset:int=0) -> list[dict[str,Any]]:
        clauses=[]; params:list[Any]=[]
        for column,value in (("indicator_code",indicator),("series_code",series),("geo_area_code",area_code)):
            if value: clauses.append(f"{column}=?"); params.append(value)
        if start_period: clauses.append("time_period>=?"); params.append(start_period)
        if end_period: clauses.append("time_period<=?"); params.append(end_period)
        sql="SELECT observation_id,indicator_code,series_code,series_description,geo_area_code,geo_area_name,time_period,value_numeric,value_text,units,nature_code,dimensions_json,source_uri,fetched_at FROM un_sdg_observations" + (" WHERE "+" AND ".join(clauses) if clauses else "") + " ORDER BY time_period DESC,geo_area_code,series_code LIMIT ? OFFSET ?"; params += [max(1,min(500,limit)),max(0,offset)]
        with connect(self.repository.path,readonly=True) as c:
            out=[]
            for row in c.execute(sql,params): d=dict(row); d["dimensions"]=json.loads(d.pop("dimensions_json")); out.append(d)
            return out

    def status(self) -> dict[str,Any]:
        with connect(self.repository.path,readonly=True) as c:
            row=c.execute("SELECT * FROM global_statistics_status").fetchone(); return dict(row) if row else {}
