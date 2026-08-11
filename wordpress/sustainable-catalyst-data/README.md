# Sustainable Catalyst Data WordPress Integration

Version 2.6.0 adds read-only earth, climate, ocean, IOOS, and USGS earthquake surfaces to the production WordPress integration while retaining archival and statistics features.

## Configuration

Open **Settings → Catalyst Data** and configure the public HTTPS Catalyst Data API base URL, for example `https://data.sustainablecatalyst.com`.

The plugin never stores PostgreSQL credentials, provider credentials, or private Catalyst Data bearer tokens. Public WordPress requests read Catalyst Data's local caches; they do not initiate World Bank, UNSD, Internet Archive, or Wayback acquisition.

## Shortcodes

- `[sustainable_catalyst_data]` — approved public record explorer.
- `[catalyst_data_embed]` — backward-compatible alias.
- `[catalyst_data_status]` — compact API health/version status.
- `[catalyst_data_archive_search query="renewable energy" limit="12"]` — cached Internet Archive catalog explorer.
- `[catalyst_data_wayback url="https://example.org" limit="20"]` — cached Wayback capture history.
- `[catalyst_data_statistics provider="world-bank" country="KEN" indicator="SP.POP.TOTL" limit="20"]` — cached World Bank observations.
- `[catalyst_data_statistics provider="un-sdg" area_code="404" indicator="1.1.1" limit="20"]` — cached UN SDG observations.

## WordPress REST routes

- `/wp-json/sustainable-catalyst-data/v1/health`
- `/wp-json/sustainable-catalyst-data/v1/records`
- `/wp-json/sustainable-catalyst-data/v1/archive/items`
- `/wp-json/sustainable-catalyst-data/v1/wayback/captures`
- `/wp-json/sustainable-catalyst-data/v1/statistics/status`
- `/wp-json/sustainable-catalyst-data/v1/statistics/world-bank/observations`
- `/wp-json/sustainable-catalyst-data/v1/statistics/un-sdg/observations`

These routes proxy only configured Catalyst Data public endpoints and never accept upstream provider URLs or credentials from visitors.


## U.S. public data
`[catalyst_data_us_public]` renders cached Census, BLS, BEA, EIA, or USGS observations from the Catalyst Data API. Acquisition remains server-side and credential secrets are never stored in WordPress.

- `[catalyst_data_earth]` — cached NOAA/ERDDAP observations or USGS earthquake events.
- `[catalyst_data_ocean]` — cached ERDDAP or IOOS dataset discovery.
