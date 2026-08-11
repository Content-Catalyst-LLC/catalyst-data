# Sustainable Catalyst Data WordPress Integration

Catalyst Data v2.2.0 ships the primary WordPress package at `dist/sustainable-catalyst-data.zip` from source in `wordpress/sustainable-catalyst-data/`.

## Configuration

After activation, open **Settings → Catalyst Data** and provide the public HTTPS base URL of the Catalyst Data API. Localhost HTTP is accepted only for development. The plugin exposes connection health and version information in the settings screen.

## Security boundary

The plugin never needs a PostgreSQL connection string and does not store private Catalyst Data bearer tokens. Public reads use `wp_safe_remote_get` with response-size, redirect, timeout, and cache bounds. Browser requests go through same-origin WordPress REST routes instead of calling the Catalyst Data origin directly.

## Shortcodes

- `[sustainable_catalyst_data]` — approved public record grid.
- `[catalyst_data_embed]` — backward-compatible alias for the public record grid.
- `[catalyst_data_status]` — compact connectivity/version status.

The old `wordpress/catalyst-data-demo/` source remains for legacy browser-contract compatibility testing; it is not the primary v2.2.0 installable plugin.
