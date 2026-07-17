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


    indicators = subparsers.add_parser("indicators", help="show the governed indicator registry")
    indicators.add_argument("database", type=Path)
    indicators.add_argument("--indicator-id")
    indicators.add_argument("--limit", type=int, default=100)

    methods = subparsers.add_parser("methods", help="show immutable methodology version history")
    methods.add_argument("database", type=Path)
    methods.add_argument("--methodology-id")
    methods.add_argument("--limit", type=int, default=100)

    units = subparsers.add_parser("units", help="show governed unit definitions")
    units.add_argument("database", type=Path)
    units.add_argument("--unit-id")
    units.add_argument("--limit", type=int, default=100)

    convert = subparsers.add_parser("convert", help="convert a value between compatible governed units")
    convert.add_argument("database", type=Path)
    convert.add_argument("value", type=float)
    convert.add_argument("from_unit")
    convert.add_argument("to_unit")

    compare = subparsers.add_parser("compare", help="compare two records using indicator governance rules")
    compare.add_argument("database", type=Path)
    compare.add_argument("left_record_id")
    compare.add_argument("right_record_id")

    governance_events = subparsers.add_parser("governance-events", help="show indicator governance history")
    governance_events.add_argument("database", type=Path)
    governance_events.add_argument("indicator_id")
    governance_events.add_argument("--limit", type=int, default=200)


    questions = subparsers.add_parser("questions", help="show research and decision questions")
    questions.add_argument("database", type=Path)
    questions.add_argument("--question-id")
    questions.add_argument("--limit", type=int, default=100)

    instruments = subparsers.add_parser("instruments", help="show collection instruments and current versions")
    instruments.add_argument("database", type=Path)
    instruments.add_argument("--instrument-id")
    instruments.add_argument("--limit", type=int, default=100)

    datasets = subparsers.add_parser("datasets", help="show datasets and current versions")
    datasets.add_argument("database", type=Path)
    datasets.add_argument("--dataset-id")
    datasets.add_argument("--limit", type=int, default=100)

    observations = subparsers.add_parser("observations", help="show governed observations")
    observations.add_argument("database", type=Path)
    observations.add_argument("--record-id")
    observations.add_argument("--quality-status", choices=("valid","missing","censored","outlier","imputed","rejected"))
    observations.add_argument("--limit", type=int, default=200)

    lineage = subparsers.add_parser("lineage", help="show question-to-observation lineage for a record")
    lineage.add_argument("database", type=Path)
    lineage.add_argument("record_id")

    reviews = subparsers.add_parser("reviews", help="show the governed review workflow queue")
    reviews.add_argument("database", type=Path)
    reviews.add_argument("--state", choices=("draft","submitted","in-review","changes-requested","approved","rejected","superseded","archived"))
    reviews.add_argument("--reviewer")
    reviews.add_argument("--limit", type=int, default=100)

    review_history = subparsers.add_parser("review-history", help="show decisions, comments, quality, and approval snapshots")
    review_history.add_argument("database", type=Path)
    review_history.add_argument("record_id")

    review_assign = subparsers.add_parser("review-assign", help="assign a reviewer")
    review_assign.add_argument("database", type=Path); review_assign.add_argument("record_id"); review_assign.add_argument("reviewer"); review_assign.add_argument("--actor", required=True)

    review_submit = subparsers.add_parser("review-submit", help="submit a record for review")
    review_submit.add_argument("database", type=Path); review_submit.add_argument("record_id"); review_submit.add_argument("--actor", required=True); review_submit.add_argument("--notes")

    review_start = subparsers.add_parser("review-start", help="start an assigned review")
    review_start.add_argument("database", type=Path); review_start.add_argument("record_id"); review_start.add_argument("--actor", required=True); review_start.add_argument("--notes")

    review_decide = subparsers.add_parser("review-decide", help="record a review decision")
    review_decide.add_argument("database", type=Path); review_decide.add_argument("record_id")
    review_decide.add_argument("decision", choices=("changes_requested","approved","rejected","superseded","archived","reopened"))
    review_decide.add_argument("--actor", required=True); review_decide.add_argument("--reason"); review_decide.add_argument("--notes")

    review_comment = subparsers.add_parser("review-comment", help="append an immutable review comment")
    review_comment.add_argument("database", type=Path); review_comment.add_argument("record_id"); review_comment.add_argument("body")
    review_comment.add_argument("--actor", required=True); review_comment.add_argument("--visibility", choices=("internal","public"), default="internal")

    quality_assess = subparsers.add_parser("quality-assess", help="append a six-dimension quality assessment from JSON")
    quality_assess.add_argument("database", type=Path); quality_assess.add_argument("record_id"); quality_assess.add_argument("input", type=Path); quality_assess.add_argument("--actor", required=True)

    revisions = subparsers.add_parser("revisions", help="show immutable record revisions and semantic diffs")
    revisions.add_argument("database", type=Path); revisions.add_argument("record_id"); revisions.add_argument("--limit", type=int, default=100)

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
    commands = {"brief", "validate", "upgrade", "init", "migrate", "rollback", "status", "import", "export", "inspect", "review", "sources", "provenance", "evidence", "indicators", "methods", "units", "convert", "compare", "governance-events", "questions", "instruments", "datasets", "observations", "lineage", "reviews", "review-history", "review-assign", "review-submit", "review-start", "review-decide", "review-comment", "quality-assess", "revisions", "-h", "--help"}
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
        if args.command == "indicators":
            repository.initialize()
            print(json.dumps(repository.indicator_registry(args.indicator_id, limit=args.limit), indent=2, ensure_ascii=False))
            return 0
        if args.command == "methods":
            repository.initialize()
            print(json.dumps(repository.methodology_history(args.methodology_id, limit=args.limit), indent=2, ensure_ascii=False))
            return 0
        if args.command == "units":
            repository.initialize()
            print(json.dumps(repository.unit_registry(args.unit_id, limit=args.limit), indent=2, ensure_ascii=False))
            return 0
        if args.command == "convert":
            repository.initialize()
            print(json.dumps({"value": args.value, "from_unit": args.from_unit, "to_unit": args.to_unit, "converted_value": repository.convert(args.value, args.from_unit, args.to_unit)}, indent=2))
            return 0
        if args.command == "compare":
            repository.initialize()
            print(json.dumps(repository.compare(args.left_record_id, args.right_record_id), indent=2, ensure_ascii=False))
            return 0
        if args.command == "governance-events":
            repository.initialize()
            print(json.dumps(repository.governance_events(args.indicator_id, limit=args.limit), indent=2, ensure_ascii=False))
            return 0
        if args.command == "questions":
            repository.initialize()
            print(json.dumps(repository.questions(args.question_id, limit=args.limit), indent=2, ensure_ascii=False))
            return 0
        if args.command == "instruments":
            repository.initialize()
            print(json.dumps(repository.instruments(args.instrument_id, limit=args.limit), indent=2, ensure_ascii=False))
            return 0
        if args.command == "datasets":
            repository.initialize()
            print(json.dumps(repository.datasets(args.dataset_id, limit=args.limit), indent=2, ensure_ascii=False))
            return 0
        if args.command == "observations":
            repository.initialize()
            print(json.dumps(repository.observations(args.record_id, quality_status=args.quality_status, limit=args.limit), indent=2, ensure_ascii=False))
            return 0
        if args.command == "lineage":
            repository.initialize()
            payload = repository.lineage(args.record_id)
            if payload is None:
                print(f"ERROR: record not found: {args.record_id}")
                return 1
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return 0

        if args.command == "reviews":
            repository.initialize(); print(json.dumps(repository.review_cases(state=args.state, reviewer=args.reviewer, limit=args.limit), indent=2, ensure_ascii=False)); return 0
        if args.command == "review-history":
            repository.initialize(); payload=repository.review_history(args.record_id)
            if payload is None: print(f"ERROR: record not found: {args.record_id}"); return 1
            print(json.dumps(payload, indent=2, ensure_ascii=False)); return 0
        if args.command == "review-assign":
            repository.initialize(); action=repository.assign_review(args.record_id,args.reviewer,args.actor); print(action); return 0
        if args.command == "review-submit":
            repository.initialize(); action=repository.submit_review(args.record_id,args.actor,args.notes); print(action); return 0
        if args.command == "review-start":
            repository.initialize(); action=repository.start_review(args.record_id,args.actor,args.notes); print(action); return 0
        if args.command == "review-decide":
            repository.initialize(); action=repository.decide_review(args.record_id,args.decision,args.actor,reason=args.reason,notes=args.notes); print(action); return 0
        if args.command == "review-comment":
            repository.initialize(); action=repository.add_review_comment(args.record_id,args.actor,args.body,visibility=args.visibility); print(action); return 0
        if args.command == "quality-assess":
            repository.initialize(); payload=_read(args.input); scores=payload.get("scores",payload); basis=payload.get("basis",{}) if isinstance(payload,dict) else {}
            action=repository.assess_quality(args.record_id,args.actor,scores,basis=basis); print(action); return 0
        if args.command == "revisions":
            repository.initialize(); print(json.dumps(repository.revision_history(args.record_id,limit=args.limit),indent=2,ensure_ascii=False)); return 0
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
