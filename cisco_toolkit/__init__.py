"""cisco_toolkit - incremental package extraction of COLLECT_PARSE_V3_23_0.py.

PHASE 2.7 (gated) decomposes the single-file script into a stdlib-only package,
one self-contained layer per PR, with the golden regression net verifying each
step. Step 1 (this module set) extracts the pure, leaf-level interface-name /
text normalization helpers into `textutils`; the monolith imports them back so
its references — and the `import COLLECT_PARSE_V3_23_0` entrypoint/tests — keep
working unchanged. Those extraction steps were byte-identical; the runtime-log
path and error boundaries below are later additive hardening.
"""

import os
import stat
from pathlib import Path

__version__ = "3.23.0"
# NEW-V3.23.40 (PHASE 2.7 step 30): single source of truth for the version, hoisted from the
# monolith so snapshot_state (now in cisco_toolkit.html) and the monolith entrypoint both import it.


class EngineLogOpenError(OSError):
    """The engine audit log could not be opened at its selected runtime location."""


def prepare_engine_log_file(path: str | Path) -> tuple[int, int, int] | None:
    """Create/validate an absolute log parent without following a reparse log target.

    Relative per-job logs retain the historical caller-owned working-directory behavior. The
    returned parent identity lets the opener reject a persistent probe-to-open directory swap.
    """
    target = Path(path)
    if not target.is_absolute():
        return None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        parent_metadata = target.parent.lstat()
    except OSError as exc:
        raise EngineLogOpenError("engine audit-log directory could not be created") from exc
    reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    parent_attributes = int(getattr(parent_metadata, "st_file_attributes", 0))
    if (
        target.parent.is_symlink()
        or parent_attributes & reparse_flag
        or not stat.S_ISDIR(parent_metadata.st_mode)
    ):
        raise EngineLogOpenError("engine audit-log directory is a reparse or non-directory entry")
    if os.path.lexists(target):
        try:
            target_metadata = target.lstat()
        except OSError as exc:
            raise EngineLogOpenError("engine audit-log target metadata could not be read") from exc
        target_attributes = int(getattr(target_metadata, "st_file_attributes", 0))
        if (
            target.is_symlink()
            or target_attributes & reparse_flag
            or not stat.S_ISREG(target_metadata.st_mode)
            or target_metadata.st_nlink != 1
        ):
            raise EngineLogOpenError("engine audit-log target is not one regular non-reparse file")
    return (
        int(parent_metadata.st_dev),
        int(parent_metadata.st_ino),
        int(stat.S_IFMT(parent_metadata.st_mode)),
    )


def engine_log_path(
    *,
    frozen: bool,
    executable: str | Path,
    cwd: str | Path,
    version: str = __version__,
) -> str:
    """Resolve the engine audit log without collapsing isolated jobs onto one shared file.

    Source/installed console scripts and frozen engine children running in an external per-job
    working directory keep the historical relative log. A frozen invocation launched from anywhere
    inside its installed application tree is redirected to the one writable ``Atlas/data`` subtree.
    """
    name = f"cisco_migration_autofill_v{version.replace('.', '_')}.log"
    if not frozen:
        return name
    executable_dir = Path(executable).resolve().parent
    try:
        Path(cwd).resolve().relative_to(executable_dir)
    except ValueError:
        return name
    except OSError:
        # If the working directory cannot be classified, prefer the bounded application data root
        # over an unknown relative write location.
        pass
    return str(executable_dir / "data" / name)
