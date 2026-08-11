# Sustainable Catalyst Data WordPress Integration

Version 2.3.0 extends the production integration foundation with read-only Internet Archive catalog and Wayback history surfaces.

## Configuration

Open **Settings → Catalyst Data** and configure the public HTTPS Catalyst Data API base URL, for example `https://data.sustainablecatalyst.com`.

The plugin never stores PostgreSQL credentials, Archive.org credentials, or private Catalyst Data bearer tokens. It proxies only Catalyst Data public-read API surfaces through `wp_safe_remote_get`, adds bounded caching, and exposes same-origin WordPress REST endpoints. Public WordPress requests read Catalyst Data's local archive catalog; they do not initiate Archive.org or Wayback acquisition.

## Shortcodes

- `[sustainable_catalyst_data]` — approved public record explorer.
- `[catalyst_data_embed]` — backward-compatible alias.
- `[catalyst_data_status]` — compact API health/version status.
- `[catalyst_data_archive_search query="renewable energy" limit="12"]` — cached Internet Archive catalog explorer.
- `[catalyst_data_wayback url="https://example.org" limit="20"]` — cached Wayback capture history.

## WordPress REST routes

- `/wp-json/sustainable-catalyst-data/v1/health`
- `/wp-json/sustainable-catalyst-data/v1/records`
- `/wp-json/sustainable-catalyst-data/v1/records/{record_id}`
- `/wp-json/sustainable-catalyst-data/v1/archive/items`
- `/wp-json/sustainable-catalyst-data/v1/archive/items/{identifier}`
- `/wp-json/sustainable-catalyst-data/v1/wayback/captures`

These routes proxy only configured Catalyst Data public endpoints and never accept a Catalyst Data upstream base URL or credentials from visitors.
