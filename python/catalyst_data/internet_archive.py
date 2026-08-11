from __future__ import annotations

import hashlib
import json
import re
import secrets
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Iterable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen

from ._version import __version__
from .adapters import AdapterManifest, AdapterValidationError, SourceAdapter
from .connectors import ConnectorFetchError
from .database import connect, transaction
from .repository import CatalystRepository, canonical_json

IA_SEARCH_URL = "https://archive.org/advancedsearch.php"
IA_METADATA_URL = "https://archive.org/metadata/{identifier}"
WAYBACK_AVAILABLE_URL = "https://archive.org/wayback/available"
WAYBACK_CDX_URL = "https://web.archive.org/cdx/search/cdx"
DEFAULT_FIELDS = ("identifier", "title", "creator", "date", "mediatype", "collection", "subject", "description", "publicdate")

class InternetArchiveError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _id(prefix: str) -> str:
    return f"{prefix}:" + secrets.token_hex(12)


def _sha(value: bytes | Mapping[str, Any] | list[Any]) -> str:
    raw = value if isinstance(value, bytes) else canonical_json(value).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _list(value: Any) -> list[Any]:
    if value is None:
        return []
    return list(value) if isinstance(value, list) else [value]


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        return "; ".join(str(item) for item in value if item is not None) or None
    return str(value)


def _valid_public_url(value: str) -> str:
    raw = str(value or "").strip()
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise InternetArchiveError("target URL must be an absolute HTTP(S) URL")
    return raw


class InternetArchiveSearchAdapter(SourceAdapter):
    manifest = AdapterManifest(
        adapter_id="internet-archive-search",
        name="Internet Archive Advanced Search Adapter",
        version="1.0.0",
        provider="internet-archive",
        response_format="json",
        capabilities=("read", "catalog-search", "pagination", "cache-friendly", "provenance"),
        pagination=("page",),
        description="Provider-specific adapter for Archive.org Advanced Search catalog discovery.",
    )

    def normalize_config(self, config: Mapping[str, Any]) -> dict[str, Any]:
        query = str(config.get("query") or "").strip()
        if not query:
            raise AdapterValidationError("config.query is required")
        rows = int(config.get("rows") or 50)
        if not 1 <= rows <= 1000:
            raise AdapterValidationError("config.rows must be between 1 and 1000")
        fields = tuple(dict.fromkeys(str(x).strip() for x in config.get("fields", DEFAULT_FIELDS) if str(x).strip()))
        if "identifier" not in fields:
            fields = ("identifier",) + fields
        sorts = tuple(str(x).strip() for x in config.get("sorts", ()) if str(x).strip())
        return {
            "base_url": IA_SEARCH_URL,
            "query": query,
            "rows": rows,
            "fields": list(fields),
            "sorts": list(sorts),
            "user_agent": str(config.get("user_agent") or InternetArchiveService.user_agent()),
            "pagination": {"type": "page", "start": int(config.get("page") or 1), "max_pages": int(config.get("max_pages") or 25)},
        }

    def request_uri(self, config: Mapping[str, Any], state: Mapping[str, Any]) -> str:
        page = int(state.get("cursor") or config["pagination"]["start"])
        params: list[tuple[str, str]] = [("q", str(config["query"])), ("output", "json"), ("rows", str(config["rows"])), ("page", str(page))]
        params.extend(("fl[]", field) for field in config["fields"])
        params.extend(("sort[]", sort) for sort in config.get("sorts", []))
        return IA_SEARCH_URL + "?" + urlencode(params)

    def parse_page(self, body: bytes, headers: Mapping[str, str], config: Mapping[str, Any], state: Mapping[str, Any]):
        payload = json.loads(body.decode("utf-8-sig"))
        response = payload.get("response") or {}
        docs = response.get("docs") or []
        if not isinstance(docs, list):
            raise AdapterValidationError("Internet Archive response.docs must be an array")
        rows = [dict(row) for row in docs if isinstance(row, Mapping)]
        page = int(state.get("cursor") or config["pagination"]["start"])
        num_found = int(response.get("numFound") or len(rows))
        next_page = page + 1 if rows and page * int(config["rows"]) < num_found else None
        return rows, next_page


class InternetArchiveMetadataAdapter(SourceAdapter):
    manifest = AdapterManifest(
        adapter_id="internet-archive-metadata",
        name="Internet Archive Item Metadata Adapter",
        version="1.0.0",
        provider="internet-archive",
        response_format="json",
        capabilities=("read", "item-metadata", "file-inventory", "provenance"),
        pagination=("none",),
        description="Fetches a complete Archive.org item metadata transaction and file inventory.",
    )

    def normalize_config(self, config: Mapping[str, Any]) -> dict[str, Any]:
        identifier = str(config.get("identifier") or "").strip()
        if not identifier or len(identifier) > 255 or not re.fullmatch(r"[^/\\?#\s]+", identifier):
            raise AdapterValidationError("config.identifier is invalid")
        return {"identifier": identifier, "base_url": IA_METADATA_URL.format(identifier=quote(identifier, safe="")), "user_agent": str(config.get("user_agent") or InternetArchiveService.user_agent()), "pagination": {"type":"none","max_pages":1}}

    def request_uri(self, config: Mapping[str, Any], state: Mapping[str, Any]) -> str:
        return str(config["base_url"])

    def parse_page(self, body: bytes, headers: Mapping[str, str], config: Mapping[str, Any], state: Mapping[str, Any]):
        payload = json.loads(body.decode("utf-8-sig"))
        if not isinstance(payload, Mapping):
            raise AdapterValidationError("Internet Archive metadata response must be an object")
        return [dict(payload)], None


class WaybackAvailabilityAdapter(SourceAdapter):
    manifest = AdapterManifest(
        adapter_id="wayback-availability",
        name="Wayback Snapshot Availability Adapter",
        version="1.0.0",
        provider="internet-archive-wayback",
        response_format="json",
        capabilities=("read", "snapshot-availability", "provenance"),
        pagination=("none",),
        description="Checks the Wayback Machine for the closest available archived snapshot.",
    )

    def normalize_config(self, config: Mapping[str, Any]) -> dict[str, Any]:
        target = _valid_public_url(str(config.get("url") or ""))
        timestamp = str(config.get("timestamp") or "").strip() or None
        if timestamp and not re.fullmatch(r"\d{4,14}", timestamp):
            raise AdapterValidationError("config.timestamp must contain 4 to 14 digits")
        return {"url": target, "timestamp": timestamp, "base_url": WAYBACK_AVAILABLE_URL, "user_agent": str(config.get("user_agent") or InternetArchiveService.user_agent()), "pagination": {"type":"none","max_pages":1}}

    def request_uri(self, config: Mapping[str, Any], state: Mapping[str, Any]) -> str:
        params = {"url": config["url"]}
        if config.get("timestamp"):
            params["timestamp"] = config["timestamp"]
        return WAYBACK_AVAILABLE_URL + "?" + urlencode(params)

    def parse_page(self, body: bytes, headers: Mapping[str, str], config: Mapping[str, Any], state: Mapping[str, Any]):
        payload = json.loads(body.decode("utf-8-sig"))
        return [dict(payload)], None


class WaybackCDXAdapter(SourceAdapter):
    manifest = AdapterManifest(
        adapter_id="wayback-cdx",
        name="Wayback CDX History Adapter",
        version="1.0.0",
        provider="internet-archive-wayback",
        response_format="json",
        capabilities=("read", "snapshot-history", "temporal-evidence", "content-digest", "provenance"),
        pagination=("none",),
        description="Retrieves Wayback CDX capture history for longitudinal archival evidence.",
    )

    def normalize_config(self, config: Mapping[str, Any]) -> dict[str, Any]:
        target = _valid_public_url(str(config.get("url") or ""))
        limit = int(config.get("limit") or 100)
        if not 1 <= limit <= 1000:
            raise AdapterValidationError("config.limit must be between 1 and 1000")
        return {"url": target, "limit": limit, "base_url": WAYBACK_CDX_URL, "user_agent": str(config.get("user_agent") or InternetArchiveService.user_agent()), "pagination": {"type":"none","max_pages":1}}

    def request_uri(self, config: Mapping[str, Any], state: Mapping[str, Any]) -> str:
        return WAYBACK_CDX_URL + "?" + urlencode({"url": config["url"], "output": "json", "limit": config["limit"]})

    def parse_page(self, body: bytes, headers: Mapping[str, str], config: Mapping[str, Any], state: Mapping[str, Any]):
        payload = json.loads(body.decode("utf-8-sig"))
        if not isinstance(payload, list) or not payload:
            return [], None
        if not isinstance(payload[0], list):
            raise AdapterValidationError("Wayback CDX JSON response must begin with a field-name row")
        fields = [str(x) for x in payload[0]]
        rows = []
        for values in payload[1:]:
            if isinstance(values, list):
                rows.append(dict(zip(fields, values)))
        return rows[: int(config["limit"])], None


class InternetArchiveService:
    def __init__(self, repository: CatalystRepository | str, *, opener: Callable[..., Any] | None = None, sleeper: Callable[[float], None] | None = None):
        self.repository = repository if isinstance(repository, CatalystRepository) else CatalystRepository(repository)
        self.repository.initialize()
        self.opener = opener or urlopen
        self.sleeper = sleeper or time.sleep

    @staticmethod
    def user_agent() -> str:
        return f"SustainableCatalyst-CatalystData/{__version__} (+https://sustainablecatalyst.com/; InternetArchiveAdapter)"

    def _fetch(self, uri: str, *, timeout: int = 30, retries: int = 3) -> tuple[bytes, dict[str,str]]:
        headers = {"User-Agent": self.user_agent(), "Accept": "application/json,text/plain;q=0.9,*/*;q=0.5"}
        for attempt in range(1, max(1,retries)+1):
            try:
                with self.opener(Request(uri, headers=headers), timeout=timeout) as response:
                    body = response.read(20_000_001)
                    if len(body) > 20_000_000:
                        raise ConnectorFetchError("Internet Archive response exceeds the 20 MB safety limit", transient=False)
                    return body, {str(k):str(v) for k,v in response.headers.items()}
            except HTTPError as exc:
                transient = exc.code == 429 or 500 <= exc.code < 600
                if not transient or attempt >= retries:
                    raise ConnectorFetchError(f"Internet Archive HTTP {exc.code}: {exc.reason}", transient=transient, status=exc.code) from exc
                retry_after = None
                if exc.headers:
                    raw = exc.headers.get("Retry-After")
                    if raw and str(raw).isdigit():
                        retry_after = min(60, max(1, int(raw)))
                    elif raw:
                        try:
                            retry_at = parsedate_to_datetime(str(raw))
                            now = datetime.now(timezone.utc)
                            if retry_at.tzinfo is None:
                                retry_at = retry_at.replace(tzinfo=timezone.utc)
                            retry_after = min(60, max(1, int((retry_at - now).total_seconds())))
                        except (TypeError, ValueError, OverflowError):
                            retry_after = None
                self.sleeper(float(retry_after or min(2 ** (attempt-1), 8)))
            except URLError as exc:
                if attempt >= retries:
                    raise ConnectorFetchError(f"Internet Archive network error: {exc.reason}", transient=True) from exc
                self.sleeper(float(min(2 ** (attempt-1), 8)))
        raise InternetArchiveError("Internet Archive request failed")

    def search(self, query: str, *, rows: int = 25, page: int = 1, fields: Iterable[str] = DEFAULT_FIELDS, sorts: Iterable[str] = ()) -> dict[str, Any]:
        adapter = InternetArchiveSearchAdapter(); config=adapter.normalize_config({"query":query,"rows":rows,"page":page,"fields":list(fields),"sorts":list(sorts),"max_pages":1})
        uri=adapter.request_uri(config,{"cursor":page}); body, headers=self._fetch(uri); docs,_=adapter.parse_page(body,headers,config,{"cursor":page})
        payload=json.loads(body.decode("utf-8-sig")); num_found=int((payload.get("response") or {}).get("numFound") or len(docs)); now=_now(); search_id=_id("ia-search")
        with connect(self.repository.path) as c, transaction(c):
            cur=c.execute("INSERT INTO internet_archive_searches(search_id,query_text,fields_json,sorts_json,page_number,row_limit,num_found,response_sha256,source_uri,fetched_at) VALUES (?,?,?,?,?,?,?,?,?,?)",(search_id,query,canonical_json(list(config['fields'])),canonical_json(list(config['sorts'])),page,rows,num_found,_sha(body),uri,now)); sid=int(cur.lastrowid)
            for pos,doc in enumerate(docs,1):
                identifier=str(doc.get('identifier') or '').strip()
                if not identifier: continue
                c.execute("INSERT INTO internet_archive_search_results(search_id,position,item_identifier,document_json) VALUES (?,?,?,?)",(sid,pos,identifier,canonical_json(doc)))
                self._upsert_item_from_doc(c,doc,now)
        return {"search_id":search_id,"query":query,"page":page,"rows":rows,"num_found":num_found,"results":docs,"source_uri":uri,"fetched_at":now}

    def _upsert_item_from_doc(self,c,doc: Mapping[str,Any],now:str):
        identifier=str(doc.get('identifier') or '').strip()
        if not identifier: return
        metadata=dict(doc); digest=_sha(metadata); source=f"https://archive.org/details/{quote(identifier,safe='')}"
        row=c.execute("SELECT id,first_seen_at,metadata_sha256 FROM internet_archive_items WHERE item_identifier=?",(identifier,)).fetchone()
        values=( _text(doc.get('title')), _text(doc.get('mediatype')), canonical_json(_list(doc.get('creator'))), _text(doc.get('date')), _text(doc.get('description')), canonical_json(_list(doc.get('collection'))), canonical_json(_list(doc.get('subject'))), canonical_json(metadata), digest, source, now )
        if row:
            c.execute("UPDATE internet_archive_items SET title=?,mediatype=?,creator_json=?,item_date=?,description=?,collection_json=?,subject_json=?,metadata_json=?,metadata_sha256=?,source_uri=?,fetched_at=?,updated_at=? WHERE id=?", values[:-1]+(now,now,int(row['id'])))
        else:
            c.execute("INSERT INTO internet_archive_items(item_identifier,title,mediatype,creator_json,item_date,description,collection_json,subject_json,metadata_json,metadata_sha256,source_uri,first_seen_at,fetched_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(identifier,)+values[:-1]+(now,now,now))

    def fetch_item(self, identifier: str) -> dict[str,Any]:
        adapter=InternetArchiveMetadataAdapter(); config=adapter.normalize_config({"identifier":identifier}); uri=adapter.request_uri(config,{}); body,headers=self._fetch(uri); rows,_=adapter.parse_page(body,headers,config,{}); payload=rows[0]; metadata=dict(payload.get('metadata') or {}); files=[dict(x) for x in payload.get('files',[]) if isinstance(x,Mapping)]; now=_now(); digest=_sha(metadata); files_digest=_sha(files)
        with connect(self.repository.path) as c, transaction(c):
            self._upsert_item_from_doc(c,{**metadata,'identifier':identifier},now)
            row=c.execute("SELECT id FROM internet_archive_items WHERE item_identifier=?",(identifier,)).fetchone(); item_id=int(row['id'])
            c.execute("UPDATE internet_archive_items SET metadata_json=?,metadata_sha256=?,source_uri=?,fetched_at=?,updated_at=? WHERE id=?",(canonical_json(metadata),digest,uri,now,now,item_id))
            existing=c.execute("SELECT id FROM internet_archive_item_versions WHERE item_id=? AND metadata_sha256=? AND files_sha256=?",(item_id,digest,files_digest)).fetchone()
            if not existing:
                c.execute("INSERT INTO internet_archive_item_versions(version_id,item_id,metadata_sha256,files_sha256,metadata_json,files_json,fetched_at) VALUES (?,?,?,?,?,?,?)",(_id('ia-item-version'),item_id,digest,files_digest,canonical_json(metadata),canonical_json(files),now))
            current_file_names = [str(f.get('name') or '').strip() for f in files if str(f.get('name') or '').strip()]
            if current_file_names:
                placeholders = ",".join("?" for _ in current_file_names)
                c.execute(f"DELETE FROM internet_archive_files WHERE item_id=? AND file_name NOT IN ({placeholders})", [item_id, *current_file_names])
            else:
                c.execute("DELETE FROM internet_archive_files WHERE item_id=?", (item_id,))
            for f in files:
                name=str(f.get('name') or '').strip()
                if not name: continue
                size=f.get('size'); size_int=int(size) if str(size or '').isdigit() else None
                private=str(f.get('private') or 'false').lower() in ('1','true','yes')
                furi=f"https://archive.org/download/{quote(identifier,safe='')}/{quote(name,safe='/')}"
                c.execute("INSERT INTO internet_archive_files(item_id,file_name,format,source_kind,size_bytes,md5,sha1,crc32,mtime,private_flag,metadata_json,source_uri,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(item_id,file_name) DO UPDATE SET format=excluded.format,source_kind=excluded.source_kind,size_bytes=excluded.size_bytes,md5=excluded.md5,sha1=excluded.sha1,crc32=excluded.crc32,mtime=excluded.mtime,private_flag=excluded.private_flag,metadata_json=excluded.metadata_json,source_uri=excluded.source_uri,updated_at=excluded.updated_at",(item_id,name,_text(f.get('format')),_text(f.get('source')),size_int,_text(f.get('md5')),_text(f.get('sha1')),_text(f.get('crc32')),_text(f.get('mtime')),1 if private else 0,canonical_json(f),furi,now))
        return self.item(identifier, include_files=True)

    def item(self, identifier: str, *, include_files: bool=True) -> dict[str,Any]:
        with connect(self.repository.path, readonly=True) as c:
            row=c.execute("SELECT * FROM internet_archive_items WHERE item_identifier=?",(identifier,)).fetchone()
            if not row: raise InternetArchiveError(f"Internet Archive item is not cached: {identifier}")
            item=dict(row); item['creator']=json.loads(item.pop('creator_json')); item['collections']=json.loads(item.pop('collection_json')); item['subjects']=json.loads(item.pop('subject_json')); item['metadata']=json.loads(item.pop('metadata_json'))
            if include_files:
                files=[]
                for r in c.execute("SELECT * FROM internet_archive_files WHERE item_id=? ORDER BY file_name",(item['id'],)):
                    f=dict(r); f['metadata']=json.loads(f.pop('metadata_json')); files.append(f)
                item['files']=files
            return item

    def items(self, *, query: str|None=None, mediatype: str|None=None, limit:int=25, offset:int=0) -> list[dict[str,Any]]:
        limit=max(1,min(100,limit)); offset=max(0,offset); clauses=[]; params=[]
        if query:
            clauses.append("(item_identifier LIKE ? OR title LIKE ? OR description LIKE ?)"); pattern=f"%{query}%"; params += [pattern,pattern,pattern]
        if mediatype: clauses.append("mediatype=?"); params.append(mediatype)
        sql="SELECT item_identifier,title,mediatype,creator_json,item_date,description,collection_json,subject_json,source_uri,fetched_at,updated_at FROM internet_archive_items"
        if clauses: sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY updated_at DESC,item_identifier LIMIT ? OFFSET ?"; params += [limit,offset]
        with connect(self.repository.path,readonly=True) as c:
            out=[]
            for row in c.execute(sql,params):
                d=dict(row); d['creator']=json.loads(d.pop('creator_json')); d['collections']=json.loads(d.pop('collection_json')); d['subjects']=json.loads(d.pop('subject_json')); out.append(d)
            return out

    def wayback_available(self, url: str, *, timestamp: str|None=None) -> dict[str,Any]:
        adapter=WaybackAvailabilityAdapter(); config=adapter.normalize_config({'url':url,'timestamp':timestamp}); uri=adapter.request_uri(config,{}); body,headers=self._fetch(uri); rows,_=adapter.parse_page(body,headers,config,{}); payload=rows[0]; closest=((payload.get('archived_snapshots') or {}).get('closest') or {}); now=_now(); count=1 if closest.get('available') else 0
        with connect(self.repository.path) as c, transaction(c):
            c.execute("INSERT INTO wayback_queries(query_id,target_url,query_type,params_json,response_sha256,result_count,source_uri,fetched_at) VALUES (?,?,?,?,?,?,?,?)",(_id('wayback-query'),url,'availability',canonical_json({'timestamp':timestamp}),_sha(body),count,uri,now))
            if count:
                self._upsert_capture(c,url,{"timestamp":closest.get('timestamp'),"original":url,"statuscode":closest.get('status'),"mimetype":None,"digest":None,"length":None,"url":closest.get('url')},now)
        return {"url":url,"closest":closest,"source_uri":uri,"fetched_at":now}

    def fetch_wayback_captures(self, url: str, *, limit:int=100) -> dict[str,Any]:
        adapter=WaybackCDXAdapter(); config=adapter.normalize_config({'url':url,'limit':limit}); uri=adapter.request_uri(config,{}); body,headers=self._fetch(uri); rows,_=adapter.parse_page(body,headers,config,{}); now=_now()
        with connect(self.repository.path) as c, transaction(c):
            c.execute("INSERT INTO wayback_queries(query_id,target_url,query_type,params_json,response_sha256,result_count,source_uri,fetched_at) VALUES (?,?,?,?,?,?,?,?)",(_id('wayback-query'),url,'cdx',canonical_json({'limit':limit}),_sha(body),len(rows),uri,now))
            for row in rows: self._upsert_capture(c,url,row,now)
        return {"url":url,"captures":self.wayback_captures(url,limit=limit),"source_uri":uri,"fetched_at":now}

    def _upsert_capture(self,c,target_url:str,row:Mapping[str,Any],now:str):
        ts=str(row.get('timestamp') or '').strip(); original=str(row.get('original') or target_url); digest=_text(row.get('digest')); replay=_text(row.get('url')) or (f"https://web.archive.org/web/{ts}/{original}" if ts else "")
        if not ts or not replay: return
        identity=_sha({"target":target_url,"timestamp":ts,"original":original,"digest":digest})[:24]; length=row.get('length'); length_int=int(length) if str(length or '').isdigit() else None
        existing=c.execute("SELECT id FROM wayback_captures WHERE target_url=? AND timestamp=? AND original_url=?",(target_url,ts,original)).fetchone()
        if existing:
            c.execute("UPDATE wayback_captures SET mimetype=COALESCE(?,mimetype),status_code=COALESCE(?,status_code),digest=COALESCE(?,digest),length_bytes=COALESCE(?,length_bytes),replay_url=?,last_seen_at=? WHERE id=?",(_text(row.get('mimetype')),_text(row.get('statuscode')),digest,length_int,replay,now,int(existing['id'])))
        else:
            c.execute("INSERT INTO wayback_captures(capture_id,target_url,timestamp,original_url,mimetype,status_code,digest,length_bytes,replay_url,first_seen_at,last_seen_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",(f'wayback-capture:{identity}',target_url,ts,original,_text(row.get('mimetype')),_text(row.get('statuscode')),digest,length_int,replay,now,now))

    def wayback_captures(self, url:str, *, limit:int=100) -> list[dict[str,Any]]:
        with connect(self.repository.path,readonly=True) as c:
            return [dict(r) for r in c.execute("SELECT capture_id,target_url,timestamp,original_url,mimetype,status_code,digest,length_bytes,replay_url,first_seen_at,last_seen_at FROM wayback_captures WHERE target_url=? ORDER BY timestamp DESC LIMIT ?",(url,max(1,min(1000,limit))))]

    def status(self) -> dict[str,Any]:
        with connect(self.repository.path,readonly=True) as c:
            row=c.execute("SELECT * FROM internet_archive_catalog_status").fetchone()
            return dict(row) if row else {"item_count":0,"file_count":0,"search_count":0,"wayback_capture_count":0}
