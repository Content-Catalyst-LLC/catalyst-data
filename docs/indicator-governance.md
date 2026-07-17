# Indicator Governance

Catalyst Data v1.4.0 introduces `catalyst-data-indicator-governance/1.0` as an optional, backward-compatible property of `catalyst-data-record/1.0`.

Each governed indicator includes:

- Namespace and code
- Domain and custodian
- Draft, active, deprecated, replaced, or archived status
- Aliases and definition
- Frequency and aggregation method
- Disaggregation dimensions
- Optional numerator and denominator definitions
- Governed reporting unit
- Versioned methodology
- Framework mappings
- Compatibility rules

The repository stores each distinct governance payload as an immutable indicator version. A changed payload creates a new revision without overwriting earlier definitions.

## Comparability

The comparison engine evaluates indicator identity, direction, unit dimension and conversion basis, frequency, aggregation, methodology equivalence, declared comparable versions, and required dimensions.

Results are:

- `equivalent`
- `convertible`
- `limited`
- `incompatible`

A convertible result means numeric unit conversion is possible. It does not imply that the records are analytically interchangeable when period, population, geography, or methodology context differs.
