# WordPress Plugin

The WordPress demo plugin provides `[catalyst_data_demo]`. It is browser-based and creates canonical JSON without sending user inputs to a server.

## Distribution

Committed source is stored in `wordpress/catalyst-data-demo/`. The installable ZIP is generated deterministically at `dist/catalyst-data-demo.zip` by:

```bash
python3 scripts/build_release.py
```

Do not edit files inside the ZIP directly.

## v1.8.0 behavior

- Loads generated review and record contracts before the demo engine.
- Emits `catalyst-data-record/1.0` with stable semantic IDs.
- Adds producer metadata and creation/update timestamps.
- Includes source URL, publisher, license, retrieval time, citation, checksum, and access notes.
- Includes confidence basis, reviewer notes, assumptions, limitations, uncertainty, and quality flags.
- Keeps review readiness separate from measurement direction.
- Treats a missing or zero baseline as an indeterminate percentage change.
- Rejects malformed URLs, checksums, unsupported quality flags, and invalid numeric values in the browser output.
- Generates unique field IDs when the shortcode appears more than once on a page.

The WordPress component remains a browser-only demonstration. Persistent repository operations are provided by the Python CLI and service layer, not by the shortcode.

## Persistent public records

Use `[catalyst_data_embed api_url="https://data.example.org" limit="12"]` to render externally approved records. The embed is read-only and never receives API write credentials.
