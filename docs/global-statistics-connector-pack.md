# Global Statistics Connector Pack — v2.4.0

Catalyst Data v2.4.0 adds governed provider adapters for the World Bank Indicators API v2 and the United Nations Statistics Division SDG API.

## World Bank

The connector preserves source-native country and indicator codes and supports the API's JSON response format, page/per-page pagination, date/date-range queries, multi-country requests, and footnote retrieval. Catalog and observation responses are cached in Catalyst Data with raw payloads, request URIs, retrieval timestamps, and immutable fetch history.

## United Nations SDG

The connector preserves UNSD goal and indicator codes and M49 geography codes. It caches current Goal/List, GeoArea/List, Indicator/List metadata and paginated Indicator/Data observations, including series identity, period, units, nature-of-data codes, and disaggregation dimensions when returned.

## Trust boundary

Acquisition is a backend/CLI operation. The public API and WordPress plugin read only the Catalyst Data cache. Public page views cannot trigger upstream World Bank or UNSD requests.

## Storage

Migration 017 adds provider catalogs, observation tables, immutable fetch history, and a combined status/freshness view. SQLite remains supported for local/offline use and the generated PostgreSQL schema remains the production path.
