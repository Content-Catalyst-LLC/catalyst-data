# Catalyst Data WordPress Plugin

Version 1.10.0 provides two independent shortcodes:

- `[catalyst_data_demo]` runs the no-server canonical record demonstration.
- `[catalyst_data_embed api_url="https://data.example.org" limit="12"]` reads externally approved records from the Catalyst Data Public API.

The persistent embed never accepts or exposes write tokens. Configure CORS on the API with `catalyst-data serve --allow-origin=https://example.org`.
