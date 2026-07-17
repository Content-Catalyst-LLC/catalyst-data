# Accessibility, Offline Use, Performance, and Release Hardening

Catalyst Data v1.12.0 adds an operational layer around the governed repository without changing `catalyst-data-record/1.0`. Migration 012 records verified backups, restores, offline operations and synchronization runs, performance benchmarks, security checks, and release attestations.

## Backup and recovery

`backup-create` uses SQLite's online backup API, runs an integrity check, writes a SHA-256 manifest sidecar, and records append-only backup history. `restore` verifies the source backup, creates a pre-restore safety copy when replacing an existing repository, applies any later supported migrations, and records an immutable restore event.

```bash
catalyst-data backup-create catalyst-data.sqlite3 backups/catalyst-data.sqlite3
catalyst-data backup-verify catalyst-data.sqlite3 backups/catalyst-data.sqlite3
catalyst-data restore catalyst-data.sqlite3 backups/catalyst-data.sqlite3 --target restored.sqlite3
```

## Offline operation queue

Field and disconnected workflows can queue canonical record writes, connector runs, saved-query runs, analysis runs, and handoff receipts. Each payload is checksum-bound. Synchronization records attempts, results, errors, and immutable run summaries. Failed operations stop after their declared maximum attempts.

```bash
catalyst-data offline-queue catalyst-data.sqlite3 record-upsert queued-record.json
catalyst-data offline-sync catalyst-data.sqlite3
catalyst-data offline-operations catalyst-data.sqlite3
```

## Performance and security

The benchmark command persists repository quick-check, statistics, and 100-record page timings with the Python, SQLite, and platform environment. The security audit checks database integrity, foreign keys, API token hashes, connector secret storage, journal mode, and database file permissions.

```bash
catalyst-data benchmark catalyst-data.sqlite3 --iterations 5
catalyst-data security-audit catalyst-data.sqlite3
catalyst-data operational-readiness catalyst-data.sqlite3
```

## Release attestations

`release-attest` writes a file-level SHA-256 manifest and lightweight software bill of materials. Attestation history is append-only inside the repository.

```bash
catalyst-data release-attest catalyst-data.sqlite3 . outputs/release-attestation.json
```

## Accessibility and public embed resilience

The WordPress embed provides visible keyboard focus, responsive layouts, reduced-motion support, live loading/error announcements, retry controls, `aria-busy`, semantic record lists, and a last-known-good browser cache. Cached records are clearly identified and are only used when the public API cannot be reached.

## Boundary

These controls improve recoverability and operational evidence. They do not replace institution-specific disaster recovery, penetration testing, legal review, or accessibility certification.
