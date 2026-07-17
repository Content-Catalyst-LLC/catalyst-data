from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from .engine import brief_markdown, build_record, convert_legacy_record
from .exporter import export_repository
from .importer import ImportPipelineError, ImportService
from .repository import CatalystRepository, RepositoryError
from .validation import RecordValidationError, validate_record


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("input JSON must contain an object")
    return value


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Validate records and operate a persistent Catalyst Data repository")
    subparsers = result.add_subparsers(dest="command")

    brief = subparsers.add_parser("brief", help="build a canonical record and Markdown brief")
    brief.add_argument("input", type=Path)
    brief.add_argument("output", type=Path)

    validate = subparsers.add_parser("validate", help="validate a canonical catalyst-data-record/1.0 file")
    validate.add_argument("input", type=Path)

    upgrade = subparsers.add_parser("upgrade", help="upgrade a v1.0.x record to catalyst-data-record/1.0")
    upgrade.add_argument("input", type=Path)
    upgrade.add_argument("output", type=Path)

    init = subparsers.add_parser("init", help="initialize a SQLite repository and apply all migrations")
    init.add_argument("database", type=Path)

    migrate = subparsers.add_parser("migrate", help="apply ordered migrations")
    migrate.add_argument("database", type=Path)
    migrate.add_argument("--target", type=int)

    rollback = subparsers.add_parser("rollback", help="reverse one or more migrations")
    rollback.add_argument("database", type=Path)
    rollback.add_argument("--steps", type=int, default=1)

    status = subparsers.add_parser("status", help="show repository health and migration status")
    status.add_argument("database", type=Path)
    status.add_argument("--json", action="store_true")

    import_command = subparsers.add_parser("import", help="import canonical or authoring records from JSON or CSV")
    import_command.add_argument("database", type=Path)
    import_command.add_argument("input", type=Path)
    import_command.add_argument("--format", choices=("auto", "json", "csv"), default="auto")
    import_command.add_argument("--dry-run", action="store_true")
    import_command.add_argument("--continue-on-error", action="store_true")
    import_command.add_argument("--non-atomic", action="store_true", help="commit valid rows while reporting invalid rows")
    import_command.add_argument("--summary", type=Path, help="write the import summary as JSON")

    export = subparsers.add_parser("export", help="export repository records to JSON or CSV")
    export.add_argument("database", type=Path)
    export.add_argument("output", type=Path)
    export.add_argument("--format", choices=("json", "csv"), default="json")

    inspect = subparsers.add_parser("inspect", help="inspect repository statistics or one record")
    inspect.add_argument("database", type=Path)
    inspect.add_argument("--record-id")

    review = subparsers.add_parser("review", help="show the measurement review queue")
    review.add_argument("database", type=Path)
    review.add_argument("--status", choices=("missing source", "needs evidence", "reviewable with caution", "reviewable"))
    review.add_argument("--limit", type=int, default=100)

    sources = subparsers.add_parser("sources", help="show immutable source version history")
    sources.add_argument("database", type=Path)
    sources.add_argument("--source-id")
    sources.add_argument("--limit", type=int, default=100)

    provenance = subparsers.add_parser("provenance", help="show append-only provenance events for a record")
    provenance.add_argument("database", type=Path)
    provenance.add_argument("record_id")
    provenance.add_argument("--limit", type=int, default=200)

    evidence = subparsers.add_parser("evidence", help="show a record evidence chain, revisions, gaps, and provenance")
    evidence.add_argument("database", type=Path)
    evidence.add_argument("record_id")

    return result


def _print_status(repository: CatalystRepository, *, as_json: bool) -> None:
    health = repository.health()
    payload = {
        "healthy": health.healthy,
        "path": health.path,
        "exists": health.exists,
        "integrity": health.integrity,
        "foreign_keys": health.foreign_keys,
        "migration_version": health.migration_version,
        "latest_migration": health.latest_migration,
        "repository_id": health.repository_id,
        "record_count": health.record_count,
        "import_run_count": health.import_run_count,
        "migrations": repository.migration_status() if health.exists else [],
    }
    if as_json:
        print(json.dumps(payload, indent=2))
        return
    print(f"repository: {payload['path']}")
    print(f"health: {'healthy' if payload['healthy'] else 'attention required'}")
    print(f"integrity: {payload['integrity']}")
    print(f"migrations: {payload['migration_version']}/{payload['latest_migration']}")
    print(f"records: {payload['record_count']}")
    print(f"import runs: {payload['import_run_count']}")


def main(argv: Sequence[str] | None = None) -> int:
    args_list = list(argv) if argv is not None else sys.argv[1:]
    commands = {"brief", "validate", "upgrade", "init", "migrate", "rollback", "status", "import", "export", "inspect", "review", "sources", "provenance", "evidence", "-h", "--help"}
    if len(args_list) == 2 and args_list[0] not in commands:
        args_list = ["brief", *args_list]
    args = parser().parse_args(args_list)
    if not args.command:
        parser().print_help()
        return 2
    try:
        if args.command == "validate":
            validate_record(_read(args.input))
            print(f"valid {args.input}")
            return 0
        if args.command == "upgrade":
            record = convert_legacy_record(_read(args.input))
            _write_json(args.output, record)
            print(f"wrote {args.output}")
            return 0
        if args.command == "brief":
            record = build_record(_read(args.input))
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(brief_markdown(record), encoding="utf-8")
            json_output = args.output.with_suffix(".json")
            _write_json(json_output, record)
            print(f"wrote {args.output}")
            print(f"wrote {json_output}")
            return 0

        repository = CatalystRepository(args.database)
        if args.command == "init":
            applied = repository.initialize()
            print(f"initialized {args.database}")
            print("applied migrations: " + (", ".join(map(str, applied)) if applied else "none"))
            return 0
        if args.command == "migrate":
            applied = repository.migrate(target=args.target)
            print("applied migrations: " + (", ".join(map(str, applied)) if applied else "none"))
            return 0
        if args.command == "rollback":
            rolled_back = repository.rollback(args.steps)
            print("rolled back migrations: " + ", ".join(map(str, rolled_back)))
            return 0
        if args.command == "status":
            _print_status(repository, as_json=args.json)
            return 0 if repository.health().healthy else 1
        if args.command == "import":
            service = ImportService(repository)
            atomic = not args.non_atomic
            summary = service.run(
                args.input,
                format_name=args.format,
                dry_run=args.dry_run,
                atomic=atomic,
                continue_on_error=args.continue_on_error or args.non_atomic,
            )
            payload = summary.to_dict()
            if args.summary:
                _write_json(args.summary, payload)
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return 1 if summary.failed else 0
        if args.command == "export":
            count = export_repository(repository, args.output, format_name=args.format)
            print(f"exported {count} record(s) to {args.output}")
            return 0
        if args.command == "inspect":
            repository.initialize()
            if args.record_id:
                record = repository.get_record(args.record_id)
                if record is None:
                    print(f"ERROR: record not found: {args.record_id}")
                    return 1
                print(json.dumps(record, indent=2, ensure_ascii=False))
            else:
                print(json.dumps(repository.stats(), indent=2))
            return 0
        if args.command == "review":
            repository.initialize()
            print(json.dumps(repository.review_queue(status=args.status, limit=args.limit), indent=2, ensure_ascii=False))
            return 0
        if args.command == "sources":
            repository.initialize()
            print(json.dumps(repository.source_history(args.source_id, limit=args.limit), indent=2, ensure_ascii=False))
            return 0
        if args.command == "provenance":
            repository.initialize()
            print(json.dumps(repository.provenance(args.record_id, limit=args.limit), indent=2, ensure_ascii=False))
            return 0
        if args.command == "evidence":
            repository.initialize()
            payload = repository.evidence(args.record_id)
            if payload is None:
                print(f"ERROR: record not found: {args.record_id}")
                return 1
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return 0
        return 2
    except ImportPipelineError as exc:
        payload = exc.summary.to_dict()
        if getattr(args, "summary", None):
            _write_json(args.summary, payload)
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 1
    except (OSError, json.JSONDecodeError, ValueError, RecordValidationError, RepositoryError) as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
