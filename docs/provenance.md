# Provenance Guide

Provenance is the chain connecting a measurement to its source, method, assumptions, limitations, and review judgment.

A canonical source record carries:

- a stable source ID;
- source name and type;
- URL and publisher;
- license or reuse terms;
- retrieval timestamp;
- formatted citation;
- optional SHA-256 checksum;
- access or confidentiality notes.

Unavailable provenance fields remain explicitly `null`; they are not replaced with invented information. Missing or weak provenance must remain visible in review status, confidence basis, method limitations, and quality flags.

v1.1.0 validates that provenance fields are structurally well formed. It does not verify that a source is truthful or authoritative. Immutable source versions and multi-source evidence relationships are scheduled for later releases.
