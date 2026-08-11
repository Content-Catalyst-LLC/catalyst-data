# Earth, Climate & Ocean Data Network

Catalyst Data v2.6.0 adds governed environmental source adapters for NOAA NCEI CDO v2, ERDDAP, the U.S. IOOS Data Catalog, and USGS earthquake events.

## Ownership boundary

Catalyst Data owns acquisition, cache persistence, source-native identifiers, timestamps, spatial coordinates, provenance, and provider request history. Site Intelligence and WordPress are consumers.

## Public reads

- `/v1/earth/status`
- `/v1/earth/observations`
- `/v1/earth/earthquakes`
- `/v1/ocean/erddap-datasets`
- `/v1/ocean/ioos-datasets`

These endpoints do not fetch upstream data.

## Secrets

NCEI access tokens are supplied through `CATALYST_NCEI_TOKEN` (or another explicitly selected environment variable) and are sent as request headers. Credentials are not written to adapter configuration, fetch provenance, WordPress, or source URIs.
