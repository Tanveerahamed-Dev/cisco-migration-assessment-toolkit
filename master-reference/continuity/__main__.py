"""Command line interface for the local read-only continuity validator."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from release.compiler_bundle import load_compiler_bundle

from .corpus import load_enhancement_corpus
from .enhance import (
    DEFAULT_MAX_DEPTH,
    DEFAULT_MAX_EDGES,
    DEFAULT_MAX_RECORDS,
    build_enhancement_package,
)
from .model import ContinuityInputError, canonical_json, read_json_object
from .query import query_by_id, query_by_path, query_impact
from .validation import validate_completion_receipt, validate_task_envelope


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m continuity",
        description="Read-only exact-source Atlas queries, enhancement scaffolds, and continuity validation",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    query = subcommands.add_parser("query", help="query one exact compiler bundle")
    query.add_argument("--compiler-output", required=True)
    selection = query.add_mutually_exclusive_group(required=True)
    selection.add_argument("--id")
    selection.add_argument("--path")
    selection.add_argument("--impact")
    query.add_argument("--line", type=int)

    enhance = subcommands.add_parser(
        "enhance",
        help="compile one bounded evidence-cited enhancement scaffold",
    )
    enhance.add_argument("--repo-root", required=True)
    enhance.add_argument("--compiler-output", required=True)
    seed = enhance.add_mutually_exclusive_group(required=True)
    seed.add_argument("--id")
    seed.add_argument("--file")
    seed.add_argument("--gap")
    enhance.add_argument("--max-depth", type=int, default=DEFAULT_MAX_DEPTH)
    enhance.add_argument("--max-records", type=int, default=DEFAULT_MAX_RECORDS)
    enhance.add_argument("--max-edges", type=int, default=DEFAULT_MAX_EDGES)

    envelope = subcommands.add_parser("validate-envelope", help="validate a TaskEnvelope")
    envelope.add_argument("--repo-root", required=True)
    envelope.add_argument("--compiler-output", required=True)
    envelope.add_argument("--envelope", required=True)

    completion = subcommands.add_parser("validate-completion", help="validate a CompletionReceipt")
    completion.add_argument("--repo-root", required=True)
    completion.add_argument("--compiler-output", required=True)
    completion.add_argument("--envelope", required=True)
    completion.add_argument("--receipt", required=True)
    return parser


def _run(arguments: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    if arguments.command == "enhance":
        bundle = load_enhancement_corpus(Path(arguments.compiler_output))
        seed_kind, seed_value = next(
            (kind, value)
            for kind, value in (("id", arguments.id), ("file", arguments.file), ("gap", arguments.gap))
            if value is not None
        )
        return build_enhancement_package(
            bundle,
            Path(arguments.repo_root),
            seed_kind=seed_kind,
            seed_value=seed_value,
            max_depth=arguments.max_depth,
            max_records=arguments.max_records,
            max_edges=arguments.max_edges,
        )

    bundle = load_compiler_bundle(Path(arguments.compiler_output))
    if arguments.command == "query":
        if arguments.line is not None and arguments.path is None:
            raise ContinuityInputError("--line is valid only with --path")
        if arguments.id is not None:
            return query_by_id(bundle, arguments.id)
        if arguments.path is not None:
            return query_by_path(bundle, arguments.path, arguments.line)
        return query_impact(bundle, arguments.impact)
    envelope = read_json_object(Path(arguments.envelope))
    if arguments.command == "validate-envelope":
        result = validate_task_envelope(envelope, Path(arguments.repo_root), bundle)
        return (0 if result["status"] == "valid" else 2), result
    receipt = read_json_object(Path(arguments.receipt))
    result = validate_completion_receipt(receipt, envelope, Path(arguments.repo_root), bundle)
    return (0 if result["status"] == "valid" else 2), result


def main() -> int:
    try:
        code, result = _run(_parser().parse_args())
    except (ContinuityInputError, OSError, RuntimeError, ValueError, KeyError, TypeError) as exc:
        code, result = 4, {
            "schema_version": "1.0.0",
            "status": "failed",
            "reason": "invalid_or_unverifiable_input",
            "detail": " ".join(str(exc).replace("\r", " ").replace("\n", " ").split())[:1000],
            "side_effects": "none",
        }
    sys.stdout.buffer.write(canonical_json(result))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
