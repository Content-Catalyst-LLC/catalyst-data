from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from .engine import brief_markdown, build_record, convert_legacy_record
from .validation import RecordValidationError, validate_record


def _read(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("input JSON must contain an object")
    return value


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Build, upgrade, and validate Catalyst Data records")
    subparsers = result.add_subparsers(dest="command")

    brief = subparsers.add_parser("brief", help="build a canonical record and Markdown brief")
    brief.add_argument("input", type=Path)
    brief.add_argument("output", type=Path)

    validate = subparsers.add_parser("validate", help="validate a canonical catalyst-data-record/1.0 file")
    validate.add_argument("input", type=Path)

    upgrade = subparsers.add_parser("upgrade", help="upgrade a v1.0.x record to catalyst-data-record/1.0")
    upgrade.add_argument("input", type=Path)
    upgrade.add_argument("output", type=Path)

    return result


def main(argv: Sequence[str] | None = None) -> int:
    args_list = list(argv) if argv is not None else sys.argv[1:]
    # Preserve the v1.0.x two-positional-argument CLI.
    if args_list is not None and len(args_list) == 2 and args_list[0] not in {"brief", "validate", "upgrade", "-h", "--help"}:
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
        record = build_record(_read(args.input))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(brief_markdown(record), encoding="utf-8")
        json_output = args.output.with_suffix(".json")
        _write_json(json_output, record)
        print(f"wrote {args.output}")
        print(f"wrote {json_output}")
        return 0
    except (OSError, json.JSONDecodeError, ValueError, RecordValidationError) as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
