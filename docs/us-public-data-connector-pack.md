# U.S. Public Data Connector Pack

Catalyst Data v2.5.0 adds governed acquisition for U.S. Census, BLS, BEA, EIA, EPA Envirofacts, and USGS Water Data.

## Credential environment variables

- Census: `CATALYST_CENSUS_API_KEY` (optional)
- BLS: `CATALYST_BLS_API_KEY` (optional for the supported single-series read surface)
- BEA: `CATALYST_BEA_API_KEY` (required)
- EIA: `CATALYST_EIA_API_KEY` (required)
- USGS: `CATALYST_USGS_API_KEY` (optional)
- EPA Envirofacts: no credential is stored by this connector

Secrets are injected at request time and redacted from stored request URIs and provenance records.

## Cached public surfaces

`GET /v1/us-public/status`

`GET /v1/us-public/observations`

`GET /v1/us-public/epa-records`

These endpoints never contact federal providers. Acquisition is a backend CLI/service operation.

## WordPress

`[catalyst_data_us_public provider="census" metric="B01003_001E" geography="state:17" limit="20"]`

WordPress receives only cached public data through the configured Catalyst Data API base URL.
