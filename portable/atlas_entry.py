"""Frozen Atlas packaging adapter; the shared server owns parsing and application startup."""

from __future__ import annotations

import ntpath
import os
from pathlib import Path
import re
import sys

from webapp.backend import serve
from cisco_toolkit.brand_tokens import APP_TITLE


def _maintenance_path_spelling(value: str, *, absolute: bool = False) -> None:
    spelling = value.replace("/", "\\")
    drive, tail = ntpath.splitdrive(spelling)
    if (spelling.startswith("\\")
            or (drive and (not re.fullmatch(r"[A-Za-z]:", drive) or not tail.startswith("\\")))
            or (absolute and (not re.fullmatch(r"[A-Za-z]:", drive) or not tail.startswith("\\")))):
        raise ValueError("unsupported Windows path namespace")


def _maintenance_local_path(path: Path) -> Path:
    """One ordinary local namespace only; never resolve UNC/device spellings."""
    if os.name == "nt":
        _maintenance_path_spelling(str(path))
    resolved = path.resolve()
    if os.name == "nt":
        _maintenance_path_spelling(str(resolved), absolute=True)
    return resolved


def _maintenance_write_refused(*, external_db=None) -> bool:
    """Fence every writable door, including a private recovery-helper executable."""
    if not serve._frozen():
        return False
    try:
        if os.name == "nt":
            # _exe_dir also resolves, so validate its original input first.
            _maintenance_path_spelling(sys.executable)
        application = _maintenance_local_path(serve._exe_dir())
        root = application.parent
        helper = bool(re.fullmatch(r"Atlas\.maintenance-[0-9a-f]{32}", root.name, re.IGNORECASE))
        if helper:
            root = root.parent
        root = _maintenance_local_path(root)
        probes: tuple[Path, ...] = ()
        if external_db is not None:
            database = Path(external_db)
            probes = tuple(_maintenance_local_path(path)
                           for path in (database, database.parent, database.parent / "backups"))
    except (OSError, ValueError, RuntimeError):
        print(f"{APP_TITLE}: refusing to write - unsupported or unresolved maintenance path namespace.\n"
              "  Use an ordinary local drive path; UNC, extended-length and device namespaces "
              "are not supported by the selftest write fence.", file=sys.stderr)
        return True
    pending = os.path.lexists(root / "Atlas.update-state.json")
    if not pending and not helper:
        return False
    if external_db is not None:
        external = True
        # DEST may be a drive root, with the transaction's TEMP directory
        # elsewhere on that drive. Every operand now shares the validated
        # ordinary local namespace, including redirected backup targets.
        for resolved in probes:
            if resolved.is_relative_to(application):
                external = False
            if resolved.is_relative_to(root):
                relative = resolved.relative_to(root).parts
                if relative and (relative[0].casefold() == "atlas"
                                 or relative[0].casefold().startswith(("atlas.", ".atlas."))):
                    external = False
        if external:
            return False
    reason = "portable maintenance is incomplete" if pending else "private maintenance helpers are code-only"
    print(f"{APP_TITLE}: refusing to write - {reason}.\n"
          "  Preserve every Atlas* path and explicitly recover with the recorded "
          "installed-version helper (README-FIELD.txt, UPDATE).", file=sys.stderr)
    return True


def _command_handler(argv: list[str]) -> int | None:
    """Dispatch installed-code maintenance before the server or engine can write."""
    if serve._frozen() and argv and argv[0] == "--verify-release":
        from portable.verify_release import main as verify_release_main

        return verify_release_main(argv[1:])
    if serve._frozen() and argv and argv[0] != serve.ENGINE_SENTINEL:
        from portable.maintenance import COMMANDS as maintenance_commands

        if any(argument in maintenance_commands for argument in argv):
            from portable.maintenance import main as maintenance_main

            return maintenance_main(argv)
    return None


def run_selftest(dist_dir=None, db_path=None, scope_dist_dir=None) -> int:
    """Run the shared asset checks behind the frozen installation write fence."""
    return serve.run_selftest(dist_dir=dist_dir, db_path=db_path, scope_dist_dir=scope_dist_dir,
                              write_admission=_maintenance_write_refused)


def _prepare_presentation(app, url):
    """Reached only after normal server fences; no imports for headless/CLI paths."""
    from portable.native_launch import prepare_presentation

    return prepare_presentation(app, url, browser_schedule=serve._schedule_browser_open)


def main(argv=None) -> int:
    """Retain shared freeze-support, argument normalization and live-network scoping."""
    return serve.main(argv, command_handler=_command_handler, write_admission=_maintenance_write_refused,
                      presentation_prepare=_prepare_presentation)


if __name__ == "__main__":
    sys.exit(main())
