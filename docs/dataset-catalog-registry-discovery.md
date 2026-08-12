# Dataset Catalog, Registry & Discovery — v2.8.0

Catalyst Data v2.8.0 adds a derived cross-provider catalog over the governed caches introduced in v2.3–v2.7.

## Boundary

The catalog is an index, not a new acquisition path. Provider-native tables remain authoritative for cached source data. `catalog-sync` reads those local tables and rebuilds searchable registry entries without calling Archive.org, World Bank, UN, Census, NOAA, NASA, or any other upstream provider.

## Indexed source families

- Internet Archive item catalog and Wayback history
- World Bank indicators
- UN SDG indicators
- Census variable/dataset series
- BLS series
- BEA and EIA metrics
- EPA Envirofacts tables
- USGS water collections
- NOAA NCEI climate series
- ERDDAP datasets
- IOOS datasets
- USGS earthquake feed
- NASA DONKI event families
- NASA/JPL small-body and close-approach catalogs
- NASA Exoplanet Archive tables

## Registry metadata

Every catalog entry carries a stable Catalyst catalog ID, provider-native dataset key, title, resource kind, publisher, source URI, record count, geographic and temporal coverage where available, source-defined license/update-frequency placeholders, freshness state, tags, provider metadata, and last source fetch time.

Freshness is derived from locally recorded provider fetch timestamps: `fresh` <=30 days, `aging` <=90 days, `stale` >90 days, otherwise `unknown`.

## Rebuildability and history

`dataset_catalog_entries` is a rebuildable projection. `dataset_catalog_sync_runs` is append-only evidence recording each sync digest and entry count. Entries no longer present in provider caches are retained but marked inactive rather than deleted.

## Public boundary

The public API and WordPress plugin read only the local registry. Public discovery cannot trigger provider acquisition or reveal provider credentials.
