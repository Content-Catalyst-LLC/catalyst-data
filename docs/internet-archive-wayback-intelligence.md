# Internet Archive & Wayback Intelligence

Catalyst Data v2.3.0 adds provider adapters and a governed archival catalog for Internet Archive and Wayback Machine resources.

## Official endpoints

- Archive.org Advanced Search (`advancedsearch.php`)
- Item Metadata API (`/metadata/{identifier}`)
- Wayback availability (`/wayback/available?url=...`)
- Wayback CDX history (`web.archive.org/cdx/search/cdx`)

Catalyst identifies automated requests with `SustainableCatalyst-CatalystData/<version>` and uses bounded retry/backoff for rate-limit and transient server responses. Catalog metadata is retained in PostgreSQL/SQLite with checksums and fetched timestamps. Files are cataloged, not mirrored, by default.

## CLI

```text
catalyst-data archive-search DATABASE QUERY [--rows 25 --page 1]
catalyst-data archive-item-fetch DATABASE IDENTIFIER
catalyst-data archive-items DATABASE [--query TEXT --mediatype TYPE]
catalyst-data archive-item DATABASE IDENTIFIER
catalyst-data wayback-available DATABASE URL
catalyst-data wayback-fetch DATABASE URL [--limit 100]
catalyst-data wayback-captures DATABASE URL [--limit 100]
catalyst-data archive-status DATABASE
```

## WordPress boundary

The WordPress plugin consumes only cached Catalyst Data archive endpoints. It never receives Archive.org credentials or causes direct Archive.org crawling.
