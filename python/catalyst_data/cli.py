from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .engine import brief_markdown, build_record


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Generate a Catalyst Data evidence brief")
    result.add_argument("input", type=Path, help="input JSON record")
    result.add_argument("output", type=Path, help="output Markdown brief")
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        payload = json.loads(args.input.read_text(encoding="utf-8"))
        record = build_record(payload)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(brief_markdown(record), encoding="utf-8")
    json_output = args.output.with_suffix(".json")
    json_output.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.output}")
    print(f"wrote {json_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
