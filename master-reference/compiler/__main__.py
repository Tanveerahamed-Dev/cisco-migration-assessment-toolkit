"""Command-line entry point: ``python -m compiler`` from master-reference."""

from __future__ import annotations

import argparse
import json

from .compiler import CompilationError, compile_repository


def main() -> int:
    parser = argparse.ArgumentParser(description="Compile the tracked repository intelligence corpus")
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--chunk-size", type=int, default=2_000)
    parser.add_argument(
        "--allow-dirty-preview",
        action="store_true",
        help="emit an explicitly non-releaseable dirty-worktree preview",
    )
    arguments = parser.parse_args()
    try:
        manifest = compile_repository(
            arguments.repo_root,
            arguments.output,
            chunk_size=arguments.chunk_size,
            allow_dirty_preview=arguments.allow_dirty_preview,
        )
    except CompilationError as exc:
        print(json.dumps({"status": "failed", "errors": list(exc.errors)}, sort_keys=True))
        return 2
    print(
        json.dumps(
            {
                "status": "complete",
                "source_commit": manifest["source_commit"],
                "source_tree_digest": manifest["source_tree_digest"],
                "groups": {name: value["record_count"] for name, value in manifest["groups"].items()},
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
