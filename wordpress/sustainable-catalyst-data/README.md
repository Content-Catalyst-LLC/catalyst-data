# Sustainable Catalyst Data WordPress Integration

Version 2.2.0 replaces the demo-oriented WordPress packaging with a production integration foundation.

## Configuration

Open **Settings → Catalyst Data** and configure the public HTTPS Catalyst Data API base URL, for example `https://data.sustainablecatalyst.com`.

The plugin never stores PostgreSQL credentials or private Catalyst Data bearer tokens. It proxies only public-read API surfaces through `wp_safe_remote_get`, adds bounded caching, and exposes same-origin WordPress REST endpoints for the front end.

## Shortcodes

- `[sustainable_catalyst_data]` — approved public record explorer.
- `[catalyst_data_embed]` — backward-compatible alias.
- `[catalyst_data_status]` — compact API health/version status.

## WordPress REST routes

- `/wp-json/sustainable-catalyst-data/v1/health`
- `/wp-json/sustainable-catalyst-data/v1/records`
- `/wp-json/sustainable-catalyst-data/v1/records/{record_id}`

These routes proxy only the Catalyst Data public endpoints and do not accept remote API URLs or credentials from visitors.
