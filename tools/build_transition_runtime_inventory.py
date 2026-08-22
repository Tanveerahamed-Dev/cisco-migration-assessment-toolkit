#!/usr/bin/env python3
"""Measure the Atlas R2 declarative reference runtime without claiming closure.

By default the canonical inventory is written to stdout. ``--check`` compares it with exact bytes
at a caller-selected path, and ``--output`` is the explicit write mode. ``--require-complete`` is a
promotion guard and deliberately fails for this partial, nonportable v1 producer.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cisco_toolkit import transition_dsl as dsl  # noqa: E402
from cisco_toolkit.transition_runtime_inventory import (  # noqa: E402
    RuntimeInventoryError,
    build_reference_runtime_inventory,
    require_complete_runtime_closure,
    runtime_inventory_bytes,
)


def _resolved_output(path: Path) -> Path:
    candidate = path if path.is_absolute() else Path.cwd() / path
    try:
        parent = candidate.parent.resolve(strict=True)
    except OSError:
        raise RuntimeInventoryError("OUTPUT_PARENT_INVALID") from None
    if not parent.is_dir():
        raise RuntimeInventoryError("OUTPUT_PARENT_INVALID")
    return parent / candidate.name


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    destination = parser.add_mutually_exclusive_group()
    destination.add_argument(
        "--check",
        type=Path,
        help="fail when the named canonical inventory bytes differ from a fresh measurement",
    )
    destination.add_argument(
        "--output",
        type=Path,
        help="write canonical inventory bytes to this explicit path",
    )
    parser.add_argument(
        "--require-complete",
        action="store_true",
        help="fail unless complete exact runtime closure was established (v1 always refuses)",
    )
    args = parser.parse_args(argv)
    inventory = build_reference_runtime_inventory(
        ROOT,
        dsl.DSL_PROTOTYPE_PROGRAM_PATH,
        dsl.DSL_PROTOTYPE_INPUT_PATH,
    )
    raw = runtime_inventory_bytes(inventory)
    if args.require_complete:
        require_complete_runtime_closure(inventory)
    if args.check is not None:
        path = _resolved_output(args.check)
        try:
            existing = path.read_bytes()
        except OSError:
            raise RuntimeInventoryError("RUNTIME_INVENTORY_CHECK_FILE_UNREADABLE") from None
        if existing != raw:
            raise RuntimeInventoryError("RUNTIME_INVENTORY_DRIFT")
    elif args.output is not None:
        path = _resolved_output(args.output)
        path.write_bytes(raw)
    else:
        sys.stdout.buffer.write(raw)
        sys.stdout.buffer.write(b"\n")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeInventoryError as exc:
        print(exc.code, file=sys.stderr)
        raise SystemExit(2) from None
