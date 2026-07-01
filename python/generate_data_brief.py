#!/usr/bin/env python3
from __future__ import annotations
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
from catalyst_data.engine import build_record, brief_markdown

def main() -> int:
    if len(sys.argv) != 3:
        print("Usage: python python/generate_data_brief.py examples/sample_project.json outputs/generated_brief.md")
        return 2
    input_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    record = build_record(payload)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(brief_markdown(record), encoding="utf-8")
    output_path.with_suffix(".json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    print(f"wrote {output_path}")
    print(f"wrote {output_path.with_suffix('.json')}")
    return 0
if __name__ == "__main__":
    raise SystemExit(main())
