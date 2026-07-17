# Institutional Workspaces and Access Governance

Catalyst Data v1.9.0 adds an institutional authorization layer without changing the canonical `catalyst-data-record/1.0` payload. Records remain portable and independently valid; workspace ownership, stewardship, access, retention, and transfer history are governed by the repository.

## Contract

Repository access metadata is represented by `catalyst-data-access-governance/1.0` and validated against `schemas/catalyst_data_access_governance_1_0.schema.json`.

The access record identifies:

- Institution and workspace
- Optional project
- Owner, steward, and custodian principals
- Visibility and data classification
- Retention policy and disposition date
- Legal-hold state

## Tenant model

The hierarchy is:

```text
institution
  └── workspace
        ├── project
        ├── membership
        └── governed record assignment
```

A migration-created Sustainable Catalyst institution and default workspace preserve compatibility for repositories upgraded from v1.8.0. Existing records are assigned automatically. Externally approved records are made public only when both workspace visibility and classification are `public`.

## Principals and roles

Principals may be users, services, or groups. Workspace membership grants one of seven roles:

- `viewer`
- `contributor`
- `analyst`
- `reviewer`
- `approver`
- `publisher`
- `administrator`

Permissions are stored explicitly. API scopes do not replace workspace permissions: an API request must pass both the bearer-token scope check and the bound principal's workspace authorization check.

## Visibility and classification

Visibility controls the intended audience:

- `private`
- `shared`
- `institutional`
- `public`

Classification controls handling sensitivity:

- `public`
- `internal`
- `restricted`
- `confidential`

A record is eligible for the public API only when:

1. Its review workflow is approved.
2. Its publication gate is external.
3. Its workspace visibility is public.
4. Its classification is public.

## Retention and legal holds

Retention policies belong to institutions and can specify a retention period and disposition action. A record may be checked for disposition eligibility with `catalyst-data disposition-check`.

An active legal hold always blocks disposition regardless of the retention date. Legal-hold changes are append-only audit events.

## Transfers and auditing

Moving a record between workspaces creates an immutable transfer event. Access decisions, membership changes, visibility changes, legal holds, record assignment, and workspace exports are recorded in `access_governance_events`.

Audit and transfer records cannot be updated or deleted through SQLite.

## API key binding

Every API key is bound to one principal and one workspace. A key cannot read another workspace's protected record collection even when it has the correct token scope.

## CLI examples

```bash
catalyst-data institution-create data.sqlite3 "Example Institute" \
  --institution-id institution:example

catalyst-data workspace-create data.sqlite3 institution:example "Research" \
  --workspace-id workspace:example-research

catalyst-data principal-create data.sqlite3 "Analyst One" \
  --principal-id principal:analyst-one \
  --email analyst@example.org

catalyst-data workspace-member-add data.sqlite3 \
  workspace:example-research principal:analyst-one analyst \
  --actor principal:system

catalyst-data record-access-set data.sqlite3 RECORD_ID \
  workspace:example-research \
  --owner-principal-id principal:analyst-one \
  --visibility institutional \
  --classification internal \
  --actor principal:analyst-one

catalyst-data legal-hold data.sqlite3 RECORD_ID set \
  --actor principal:analyst-one \
  --reason "Preserve for institutional review"

catalyst-data access-events data.sqlite3 --record-id RECORD_ID
```

## Boundaries

Catalyst Data provides access controls and auditable policy metadata. It does not itself establish legal compliance, records-management certification, or regulatory sufficiency. Institutions remain responsible for defining appropriate roles, retention periods, privacy classifications, and legal-hold procedures.
