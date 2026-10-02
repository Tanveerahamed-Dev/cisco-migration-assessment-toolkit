"""Export the real AssessHub OpenAPI offline using a temporary, empty snapshot store."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tempfile

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from webapp.backend.app import create_app  # noqa: E402


def export_schema() -> dict:
    """No server and no persistent user store; endpoint schemas come from the actual app."""
    with tempfile.TemporaryDirectory(prefix="atlas-openapi-") as directory:
        root = Path(directory)
        app = create_app(db_path=str(root / "empty.db"), dist_dir=root / "no-frontend", scope_dist_dir=None)
        try:
            return app.openapi()
        finally:
            app.state.store.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--check", action="store_true", help="Compare without changing the output file")
    args = parser.parse_args(argv)
    payload = (json.dumps(export_schema(), indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    if args.check:
        if not args.output.is_file() or args.output.read_bytes() != payload:
            print("OpenAPI output differs from the live application schema", file=sys.stderr)
            return 1
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
