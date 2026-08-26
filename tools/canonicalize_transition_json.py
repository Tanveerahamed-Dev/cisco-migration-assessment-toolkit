"""Rewrite a transition JSON asset to the frozen exact canonical encoding."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    from cisco_toolkit.transition_contract import canonical_json_bytes

    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    value = json.loads(args.path.read_text(encoding="utf-8"))
    args.path.write_bytes(canonical_json_bytes(value))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
