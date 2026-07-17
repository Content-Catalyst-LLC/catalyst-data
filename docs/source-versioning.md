# Source Versioning and Snapshots

Source identity is stable across metadata updates. The `sources` table stores the current normalized source, while `source_versions` stores each unique historical payload.

A source version is deduplicated by the SHA-256 digest of canonical source JSON. `source_snapshots` records retrieved content or capture metadata associated with a specific source version.

Source versions and snapshots are immutable. Corrections create a new source version or snapshot rather than editing history.
