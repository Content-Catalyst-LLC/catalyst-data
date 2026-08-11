# Space & Scientific Data Network

Catalyst Data v2.7.0 adds governed provider integrations for NASA DONKI, the NASA/JPL Small-Body Database, NASA/JPL close-approach observations, and NASA Exoplanet Archive TAP discovery.

## Acquisition boundary

Provider calls happen only through Catalyst Data backend operations. Public API and WordPress surfaces read the local governed cache. NASA API credentials are injected from environment variables at request time and are not persisted.

## Cached data families

- Space-weather events: event type, source ID, start time, coordinates where supplied, linked instruments/activities, and raw provider payload.
- Small bodies: permanent/source designations, NEO/PHA flags, orbit class, physical/orbital fields, and raw provider payload.
- Close approaches: source designation, approach epoch/date, body, distance, relative velocity, magnitude/diameter fields where supplied, and raw provider payload.
- Exoplanets: planet/host identity, discovery metadata, selected planetary/stellar fields, sky coordinates, and raw TAP row.

## Consumer boundary

Site Intelligence, Workspace, Research Librarian, Publications, and WordPress can consume cached records through Catalyst Data contracts without acquiring from NASA/JPL directly.
