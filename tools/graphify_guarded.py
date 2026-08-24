"""Run Graphify 0.9.47 with the reviewed JSON ``extends`` correction in memory.

Graphifyy 0.9.47's JSON extractor emits ``extends`` edges for every array-valued
property.  This launcher accepts only the reviewed upstream extractor bytes,
changes the one faulty predicate in memory, verifies the result, and rebinds the
aliases used by the 0.9.47 dispatcher before Graphify's CLI is entered.
Because parallel AST workers reload the on-disk module, the launcher also owns
``GRAPHIFY_MAX_WORKERS=1`` and rejects command-line worker overrides.

This is deliberately a narrow compatibility guard, not verification of the full
Graphify wheel or its transitive dependencies.  The installed package is never
modified.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import importlib.util
import json
import os
import stat
import sys
import types
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

GUARD_CONTRACT = "graphify-json-extends-overlay/1"
DIST_NAME = "graphifyy"
EXPECTED_VERSION = "0.9.47"
EXTRACTOR_MODULE = "graphify.extractors.json_config"
EXTRACTOR_RELATIVE_PATH = "graphify/extractors/json_config.py"
EXPECTED_SOURCE_BYTES = 9_723
EXPECTED_SOURCE_SHA256 = "d15ea6d9b48cc71e73615c44c72808562ad4a1dbc82d5a340e3ad0c2fb4fc945"
EXPECTED_PATCHED_BYTES = 9_744
EXPECTED_PATCHED_SHA256 = "cb6b660bd2dee3f58e9007d0eac27883cd3bb3fe5d8136c13e8d83b92b90e011"
WORKER_ENV = "GRAPHIFY_MAX_WORKERS"
GUARDED_MAX_WORKERS = "1"
REFRESH_RECEIPT_CONTRACT = "atlas-graphify-refresh/1"
REFRESH_RECEIPT_PATH = Path("graphify-out/.guarded_refresh.json")

_SOURCE_SENTINEL = b'            elif val.type == "array":'
_PATCHED_SENTINEL = b'            elif val.type == "array" and key == "extends":'
_MAX_EXTRACTOR_BYTES = 32_768

_ERROR_MESSAGES = {
    "G001": "graphifyy distribution metadata is unavailable",
    "G002": "graphifyy version is not the reviewed 0.9.47 release",
    "G003": "the reviewed extractor path is unavailable or ambiguous",
    "G004": "the extractor bytes do not match the reviewed 0.9.47 source",
    "G005": "the in-memory correction does not match the reviewed result",
    "G006": "the imported extractor path or alias topology is unexpected",
    "G007": "the in-memory extractor overlay could not be installed",
    "G008": "the guard failed unexpectedly",
    "G009": "--probe does not accept additional arguments",
    "G010": "the guard owns single-process AST extraction; --max-workers is not accepted",
    "G011": "only update, watch, and code-only extract are guarded producer commands",
    "G012": "extract requires an explicit local path and --code-only",
    "G013": "the guarded producer command contains an unsupported option or argument",
    "G014": "the guard requires Python 3.12+, isolated mode, and bytecode writes disabled (-I -B)",
    "G015": "the effective producer root must be local, whole-repository, and not a linked worktree",
    "G016": "update and watch require an established graph.json in the canonical checkout",
    "G017": "the guarded refresh receipt request is invalid or unavailable",
    "G018": "another guarded Graphify producer already owns this output root",
}

_JSON_SUFFIX_VARIANTS = frozenset(
    "." + "".join(char.upper() if mask & (1 << index) else char for index, char in enumerate("json"))
    for mask in range(1 << len("json"))
)


class GuardFailure(RuntimeError):
    """A bounded, user-safe guard failure."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _stat_identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _native_long_path(path: Path) -> str:
    """Use extended-length spelling for deep generated output on Windows."""

    value = str(path)
    if os.name != "nt" or value.startswith("\\\\?\\"):
        return value
    if value.startswith("\\\\"):
        return "\\\\?\\UNC\\" + value[2:]
    return "\\\\?\\" + value


def _read_stable_source(path: Path) -> bytes:
    """Read one small regular file without a stat/read race."""

    try:
        with path.open("rb") as handle:
            before = os.fstat(handle.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise GuardFailure("G003")
            payload = handle.read(_MAX_EXTRACTOR_BYTES + 1)
            after = os.fstat(handle.fileno())
    except GuardFailure:
        raise
    except (OSError, ValueError) as exc:
        raise GuardFailure("G003") from exc

    if (
        len(payload) > _MAX_EXTRACTOR_BYTES
        or len(payload) != after.st_size
        or _stat_identity(before) != _stat_identity(after)
    ):
        raise GuardFailure("G004")
    return payload


def _locate_extractor(distribution: Any) -> Path:
    try:
        version = distribution.version
    except Exception as exc:  # metadata providers are external to this repository
        raise GuardFailure("G001") from exc
    if version != EXPECTED_VERSION:
        raise GuardFailure("G002")

    try:
        files = distribution.files
        matches = [
            item
            for item in (files or ())
            if str(item).replace("\\", "/") == EXTRACTOR_RELATIVE_PATH
        ]
        if len(matches) != 1:
            raise GuardFailure("G003")
        path = Path(distribution.locate_file(matches[0])).resolve(strict=True)
    except GuardFailure:
        raise
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise GuardFailure("G003") from exc
    return path


def _verified_patch(source: bytes) -> bytes:
    if (
        len(source) != EXPECTED_SOURCE_BYTES
        or _sha256(source) != EXPECTED_SOURCE_SHA256
        or source.count(_SOURCE_SENTINEL) != 1
        or source.count(_PATCHED_SENTINEL) != 0
    ):
        raise GuardFailure("G004")

    patched = source.replace(_SOURCE_SENTINEL, _PATCHED_SENTINEL, 1)
    if (
        len(patched) != EXPECTED_PATCHED_BYTES
        or _sha256(patched) != EXPECTED_PATCHED_SHA256
        or patched.count(_SOURCE_SENTINEL) != 0
        or patched.count(_PATCHED_SENTINEL) != 1
    ):
        raise GuardFailure("G005")
    return patched


def _module_file(module: types.ModuleType) -> Path:
    try:
        return Path(module.__file__).resolve(strict=True)  # type: ignore[arg-type]
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as exc:
        raise GuardFailure("G006") from exc


def _prepare_overlay(
    *,
    distribution_getter: Callable[[str], Any] | None = None,
    module_importer: Callable[[str], types.ModuleType] | None = None,
) -> dict[str, Any]:
    """Verify the installed source and install the corrected module in this process."""

    get_distribution = distribution_getter or importlib.metadata.distribution
    import_module = module_importer or importlib.import_module
    try:
        distribution = get_distribution(DIST_NAME)
    except importlib.metadata.PackageNotFoundError as exc:
        raise GuardFailure("G001") from exc
    except Exception as exc:  # keep probe output fixed and bounded
        raise GuardFailure("G001") from exc

    source_path = _locate_extractor(distribution)
    source = _read_stable_source(source_path)
    patched = _verified_patch(source)

    try:
        original_module = import_module(EXTRACTOR_MODULE)
        extractors_package = import_module("graphify.extractors")
        models_module = import_module("graphify.extractors.models")
        extract_facade = import_module("graphify.extract")
    except Exception as exc:
        raise GuardFailure("G006") from exc

    # Imports may have read the installed module. Recheck the same file before
    # any alias is changed or the Graphify CLI is allowed to run.
    if _module_file(original_module) != source_path or _read_stable_source(source_path) != source:
        raise GuardFailure("G006")

    original_extract_json = getattr(original_module, "extract_json", None)
    dispatch = getattr(extract_facade, "_DISPATCH", None)
    language_extractors = getattr(extractors_package, "LANGUAGE_EXTRACTORS", None)
    cache_bypass_suffixes = getattr(extract_facade, "_JS_CACHE_BYPASS_SUFFIXES", None)
    if (
        not callable(original_extract_json)
        or getattr(extractors_package, "json_config", None) is not original_module
        or getattr(extractors_package, "extract_json", None) is not original_extract_json
        or not isinstance(language_extractors, dict)
        or language_extractors.get("json") is not original_extract_json
        or getattr(extract_facade, "extract_json", None) is not original_extract_json
        or not isinstance(dispatch, dict)
        or dispatch.get(".json") is not original_extract_json
        or not isinstance(cache_bypass_suffixes, set)
        or getattr(models_module, "_JS_CACHE_BYPASS_SUFFIXES", None) is not cache_bypass_suffixes
    ):
        raise GuardFailure("G006")

    overlay = types.ModuleType(EXTRACTOR_MODULE)
    overlay.__file__ = str(source_path)
    overlay.__package__ = "graphify.extractors"
    overlay.__loader__ = None
    overlay.__spec__ = importlib.util.spec_from_loader(
        EXTRACTOR_MODULE, loader=None, origin=str(source_path)
    )
    try:
        code = compile(patched.decode("utf-8", errors="strict"), str(source_path), "exec")
        exec(code, overlay.__dict__)
        corrected_extract_json = overlay.extract_json
    except Exception as exc:
        raise GuardFailure("G007") from exc
    if not callable(corrected_extract_json):
        raise GuardFailure("G007")

    # Rebind every public/live 0.9.47 function alias. The dispatcher mapping is
    # the extraction owner; the others keep direct imports coherent.
    sys.modules[EXTRACTOR_MODULE] = overlay
    extractors_package.json_config = overlay
    extractors_package.extract_json = corrected_extract_json
    language_extractors["json"] = corrected_extract_json
    extract_facade.extract_json = corrected_extract_json
    dispatch[".json"] = corrected_extract_json

    # 0.9.47's AST cache namespace identifies only the package version/schema,
    # not these corrected extractor bytes. Never read or write ambiguous JSON
    # entries; preserve them on disk for reversibility and re-extract JSON here.
    # Dispatch case-folds suffixes, while the cache bypass in 0.9.47 compares
    # the raw suffix. Cover all ASCII case variants so FOO.JSON cannot replay
    # an ambiguous entry that foo.json would bypass.
    cache_bypass_suffixes.update(_JSON_SUFFIX_VARIANTS)

    if not (
        sys.modules.get(EXTRACTOR_MODULE) is overlay
        and extractors_package.json_config is overlay
        and extractors_package.extract_json is corrected_extract_json
        and language_extractors.get("json") is corrected_extract_json
        and extract_facade.extract_json is corrected_extract_json
        and dispatch.get(".json") is corrected_extract_json
        and _JSON_SUFFIX_VARIANTS.issubset(cache_bypass_suffixes)
        and getattr(models_module, "_JS_CACHE_BYPASS_SUFFIXES", None) is cache_bypass_suffixes
    ):
        raise GuardFailure("G007")

    return {
        "aliases": 5,
        "ast_cache": "bypass-json-casefold",
        "contract": GUARD_CONTRACT,
        "extractor": EXTRACTOR_RELATIVE_PATH,
        "max_workers": int(GUARDED_MAX_WORKERS),
        "patched_sha256": EXPECTED_PATCHED_SHA256,
        "source_sha256": EXPECTED_SOURCE_SHA256,
        "status": "pass",
        "version": EXPECTED_VERSION,
    }


def _run_graphify(arguments: Sequence[str]) -> int:
    try:
        graphify_main = importlib.import_module("graphify.__main__").main
    except Exception as exc:
        raise GuardFailure("G006") from exc

    previous_argv = sys.argv
    sys.argv = ["graphify", *arguments]
    try:
        result = graphify_main()
    finally:
        sys.argv = previous_argv
    return result if isinstance(result, int) else 0


def _print_failure(failure: GuardFailure) -> None:
    message = _ERROR_MESSAGES.get(failure.code, _ERROR_MESSAGES["G008"])
    print(
        f"graphify-guard: {failure.code}: {message}; no Graphify command was run.",
        file=sys.stderr,
    )


def _invocation_isolated() -> bool:
    """Attest the process boundary used to exclude repo/user-site shadowing."""

    return bool(
        sys.version_info >= (3, 12)
        and hasattr(Path, "is_junction")
        and sys.flags.isolated
        and sys.dont_write_bytecode
    )


@contextmanager
def _controlled_environment(root: Path | None = None):
    """Neutralize ambient controls and repo-local executable lookup."""

    prefixes = ("GRAPHIFY_", "GIT_")
    inherited = {
        key: value for key, value in os.environ.items() if key.startswith(prefixes)
    }
    inherited_path = os.environ.get("PATH")
    inherited_no_current = os.environ.get("NoDefaultCurrentDirectoryInExePath")
    excluded_roots = {Path.cwd().resolve(strict=True)}
    if root is not None:
        excluded_roots.add(root)
    for key in inherited:
        os.environ.pop(key, None)
    os.environ[WORKER_ENV] = GUARDED_MAX_WORKERS
    sanitized_path = []
    for entry in (inherited_path or "").split(os.pathsep):
        if not entry:
            continue
        candidate = Path(entry)
        if not candidate.is_absolute():
            continue
        try:
            resolved = candidate.resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        if any(resolved == excluded or excluded in resolved.parents for excluded in excluded_roots):
            continue
        sanitized_path.append(str(resolved))
    os.environ["PATH"] = os.pathsep.join(sanitized_path)
    if os.name == "nt":
        os.environ["NoDefaultCurrentDirectoryInExePath"] = "1"
    try:
        yield
    finally:
        # Also remove controls the upstream CLI may have added during this run.
        for key in tuple(os.environ):
            if key.startswith(prefixes):
                os.environ.pop(key, None)
        os.environ.update(inherited)
        if inherited_path is None:
            os.environ.pop("PATH", None)
        else:
            os.environ["PATH"] = inherited_path
        if inherited_no_current is None:
            os.environ.pop("NoDefaultCurrentDirectoryInExePath", None)
        else:
            os.environ["NoDefaultCurrentDirectoryInExePath"] = inherited_no_current


def _is_local_path(argument: str) -> bool:
    """Reject URL/UNC-shaped producer roots; drive and relative paths stay valid."""

    return bool(argument) and "://" not in argument and not argument.startswith(("//", "\\\\"))


def _producer_root(arguments: Sequence[str]) -> Path:
    if arguments[0] == "update":
        value = next(argument for argument in arguments[1:] if not argument.startswith("-"))
    else:
        value = arguments[1]
    try:
        root = Path(value).resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise GuardFailure("G015") from exc
    if not root.is_dir() or str(root).replace("\\", "/").startswith("//"):
        raise GuardFailure("G015")
    # Default output must remain under the same effective local root. Resolve
    # existing symlinks/junctions; reject even a broken symlink explicitly.
    output = root / "graphify-out"
    if output.is_symlink() or output.is_junction():
        raise GuardFailure("G015")
    if output.exists():
        try:
            resolved_output = output.resolve(strict=True)
            resolved_output.relative_to(root)
        except (OSError, RuntimeError, ValueError) as exc:
            raise GuardFailure("G015") from exc
        if str(resolved_output).replace("\\", "/").startswith("//"):
            raise GuardFailure("G015")
        stack = [output]
        while stack:
            directory = stack.pop()
            try:
                entries = tuple(os.scandir(_native_long_path(directory)))
            except OSError as exc:
                raise GuardFailure("G015") from exc
            for entry in entries:
                child = Path(entry.path)
                if child.is_symlink() or child.is_junction():
                    raise GuardFailure("G015")
                try:
                    # DirEntry's cached Windows stat can report st_nlink=0 for
                    # ordinary files; a fresh path stat reports the real count.
                    info = os.stat(_native_long_path(child), follow_symlinks=False)
                    if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
                        raise GuardFailure("G015")
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(child)
                except OSError as exc:
                    raise GuardFailure("G015") from exc
    if arguments[0] in {"update", "watch"} and not (
        output / "graph.json"
    ).is_file():
        raise GuardFailure("G016")

    # Standard Git main checkouts own a .git directory at the exact producer
    # root. A linked worktree owns a .git file; a nested root finds an ancestor
    # marker. Avoid launching Git here: on Windows, CreateProcess can resolve a
    # repo-local git.exe ahead of the trusted installation.
    marker = root / ".git"
    if marker.is_symlink() or marker.is_junction() or marker.is_file():
        raise GuardFailure("G015")
    if marker.is_dir() and (marker / "commondir").exists():
        raise GuardFailure("G015")
    if not marker.is_dir() and any((parent / ".git").exists() for parent in root.parents):
        raise GuardFailure("G015")
    return root


@contextmanager
def _producer_lock(root: Path):
    """Hold one OS-backed nonblocking lock for every producer touching this root."""

    output = root / "graphify-out"
    lock_path = output / ".guarded_producer.lock"
    try:
        output.mkdir(exist_ok=True)
        if output.is_symlink() or output.is_junction() or output.resolve(strict=True) != output:
            raise GuardFailure("G015")
        flags = os.O_RDWR | os.O_CREAT
        flags |= getattr(os, "O_BINARY", 0) | getattr(os, "O_NOINHERIT", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(lock_path, flags, 0o600)
    except GuardFailure:
        raise
    except OSError as exc:
        raise GuardFailure("G018") from exc

    locked = False
    try:
        opened = os.fstat(descriptor)
        named = os.stat(lock_path, follow_symlinks=False)
        if (
            lock_path.is_symlink()
            or lock_path.is_junction()
            or not stat.S_ISREG(opened.st_mode)
            or not stat.S_ISREG(named.st_mode)
            or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)
            or opened.st_nlink != 1
        ):
            raise GuardFailure("G015")
        if opened.st_size < 1:
            os.write(descriptor, b"\0")
            os.fsync(descriptor)
        os.lseek(descriptor, 0, os.SEEK_SET)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        locked = True
    except GuardFailure:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise
    except OSError as exc:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise GuardFailure("G018") from exc

    try:
        yield
    finally:
        if locked:
            try:
                os.lseek(descriptor, 0, os.SEEK_SET)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(descriptor, fcntl.LOCK_UN)
            except OSError:
                pass
        try:
            os.close(descriptor)
        except OSError:
            pass


def _canonical_arguments(arguments: Sequence[str], root: Path) -> list[str]:
    """Pass Graphify the same canonical root that the guard actually checked."""

    canonical = list(arguments)
    if canonical[0] == "update":
        index = next(
            index for index, argument in enumerate(canonical[1:], start=1)
            if not argument.startswith("-")
        )
    else:
        index = 1
    canonical[index] = str(root)
    return canonical


def _attested_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    attested = dict(receipt)
    attested["bytecode_writes"] = "disabled"
    attested["environment"] = "graphify-git-path-sanitized"
    attested["isolated"] = True
    attested["python"] = ".".join(str(part) for part in sys.version_info[:3])
    return attested


def _refresh_receipt_path(argument: str) -> Path:
    try:
        root = Path.cwd().resolve(strict=True)
        expected = root / REFRESH_RECEIPT_PATH
        candidate = Path(os.path.abspath(argument))
        if os.path.normcase(str(candidate)) != os.path.normcase(str(expected)):
            raise GuardFailure("G017")
        parent = candidate.parent
        if (
            not parent.is_dir()
            or parent.is_symlink()
            or parent.is_junction()
            or parent.resolve(strict=True) != expected.parent
            or candidate.is_symlink()
        ):
            raise GuardFailure("G017")
    except GuardFailure:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise GuardFailure("G017") from exc
    return candidate


def _valid_head(head: str) -> bool:
    return len(head) in {40, 64} and head == head.lower() and all(
        character in "0123456789abcdef" for character in head
    )


def _refresh_receipt_payload(
    *, phase: str, head: str, state: str, guard_receipt: dict[str, Any], receipt_path: Path
) -> dict[str, Any]:
    if phase not in {"pending", "complete"} or state not in {"clean", "dirty"}:
        raise GuardFailure("G017")
    if not _valid_head(head):
        raise GuardFailure("G017")
    payload: dict[str, Any] = {
        "contract": REFRESH_RECEIPT_CONTRACT,
        "guard": guard_receipt,
        "head": head,
        "phase": phase,
        "root": str(Path.cwd().resolve(strict=True)),
        "state": state,
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if phase == "complete":
        payload["graph"] = _graph_identity(receipt_path.parent / "graph.json")
    return payload


def _graph_identity(path: Path) -> dict[str, Any]:
    try:
        if path.is_symlink():
            raise GuardFailure("G017")
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            before = os.fstat(handle.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise GuardFailure("G017")
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
            after = os.fstat(handle.fileno())
    except GuardFailure:
        raise
    except OSError as exc:
        raise GuardFailure("G017") from exc
    if _stat_identity(before) != _stat_identity(after):
        raise GuardFailure("G017")
    return {"sha256": digest.hexdigest(), "size": after.st_size}


def _write_refresh_receipt(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except (OSError, TypeError, ValueError) as exc:
        raise GuardFailure("G017") from exc
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _read_refresh_receipt(path: Path) -> dict[str, Any] | None:
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 16_384:
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _same_receipt_identity(left: dict[str, Any], right: dict[str, Any]) -> bool:
    """Compare JSON identities without Python's ``True == 1`` coercion."""

    try:
        return json.dumps(
            {key: value for key, value in left.items() if key != "updated_at"},
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ) == json.dumps(
            {key: value for key, value in right.items() if key != "updated_at"},
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError):
        return False


def _handle_refresh_receipt(
    arguments: Sequence[str], guard_receipt: dict[str, Any]
) -> int:
    mode, path_arg, head, state = arguments
    path = _refresh_receipt_path(path_arg)
    if mode == "--receipt-status":
        if state != "clean":
            return 1
        expected = _refresh_receipt_payload(
            phase="complete",
            head=head,
            state=state,
            guard_receipt=guard_receipt,
            receipt_path=path,
        )
        actual = _read_refresh_receipt(path)
        if actual is None:
            return 1
        try:
            updated_at = datetime.fromisoformat(actual["updated_at"])
        except (KeyError, TypeError, ValueError):
            return 1
        if updated_at.tzinfo is None:
            return 1
        # Timestamp is evidentiary but not part of the freshness identity.
        return 0 if _same_receipt_identity(actual, expected) else 1
    if mode == "--receipt-complete":
        # Completion is a transition, not an independently mintable assertion.
        # The Stop hook must first have recorded the exact pending snapshot before
        # it entered Graphify.  This is local hook bookkeeping (not a signature),
        # but it prevents an accidental/partial finalizer from blessing arbitrary
        # graph bytes without the transaction's pre-mutation marker.
        pending = _read_refresh_receipt(path)
        expected_pending = _refresh_receipt_payload(
            phase="pending",
            head=head,
            state=state,
            guard_receipt=guard_receipt,
            receipt_path=path,
        )
        if pending is None:
            raise GuardFailure("G017")
        try:
            pending_updated_at = datetime.fromisoformat(pending["updated_at"])
        except (KeyError, TypeError, ValueError) as exc:
            raise GuardFailure("G017") from exc
        if pending_updated_at.tzinfo is None or not _same_receipt_identity(
            pending, expected_pending
        ):
            raise GuardFailure("G017")

    phase = "pending" if mode == "--receipt-pending" else "complete"
    payload = _refresh_receipt_payload(
        phase=phase,
        head=head,
        state=state,
        guard_receipt=guard_receipt,
        receipt_path=path,
    )
    _write_refresh_receipt(path, payload)
    return 0


def _validate_arguments(arguments: Sequence[str]) -> None:
    """Keep the guarded surface offline, local, and exact for Graphifyy 0.9.47."""

    if not arguments or arguments[0] not in {"update", "watch", "extract"}:
        raise GuardFailure("G011")

    command = arguments[0]
    if command == "update":
        roots = []
        positional = 0
        for argument in arguments[1:]:
            if argument in {"--force", "--no-cluster"}:
                continue
            if argument.startswith("-"):
                raise GuardFailure("G013")
            positional += 1
            roots.append(argument)
        if positional != 1:
            raise GuardFailure("G013")
        if not _is_local_path(roots[0]):
            raise GuardFailure("G013")
        return

    if command == "watch":
        if len(arguments) != 2 or arguments[1].startswith("-"):
            raise GuardFailure("G013")
        if not _is_local_path(arguments[1]):
            raise GuardFailure("G013")
        return

    # ``extract`` auto-selects an LLM backend when API keys exist. Keep only a
    # closed local AST surface and require the explicit no-semantic flag. In
    # particular, do not expose --allow-partial, --force, --no-gitignore, live
    # database/global destinations, or output indirection through this guard.
    if (
        len(arguments) < 2
        or arguments[1].startswith("-")
        or not _is_local_path(arguments[1])
    ):
        raise GuardFailure("G012")
    code_only = False
    no_value_options = {"--code-only", "--no-cluster"}
    index = 2
    while index < len(arguments):
        argument = arguments[index]
        if argument in no_value_options:
            code_only = code_only or argument == "--code-only"
            index += 1
            continue
        raise GuardFailure("G013")
    if not code_only:
        raise GuardFailure("G012")


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    producer_root: Path | None = None
    receipt_modes = {"--receipt-status", "--receipt-pending", "--receipt-complete"}
    receipt_mode = bool(arguments and arguments[0] in receipt_modes)
    if not _invocation_isolated():
        failure = GuardFailure("G014")
        _print_failure(failure)
        return 2
    if arguments and arguments[0] == "--probe" and len(arguments) != 1:
        failure = GuardFailure("G009")
        _print_failure(failure)
        return 2
    if receipt_mode and len(arguments) != 4:
        failure = GuardFailure("G017")
        _print_failure(failure)
        return 2
    if any(arg == "--max-workers" or arg.startswith("--max-workers=") for arg in arguments):
        failure = GuardFailure("G010")
        _print_failure(failure)
        return 2
    if arguments != ["--probe"] and not receipt_mode:
        try:
            _validate_arguments(arguments)
            producer_root = _producer_root(arguments)
            arguments = _canonical_arguments(arguments, producer_root)
        except GuardFailure as failure:
            _print_failure(failure)
            return 2

    with _controlled_environment(producer_root):
        try:
            receipt = _prepare_overlay()
        except GuardFailure as failure:
            _print_failure(failure)
            return 2
        except Exception:
            _print_failure(GuardFailure("G008"))
            return 2

        attested = _attested_receipt(receipt)
        if arguments == ["--probe"]:
            print(json.dumps(attested, sort_keys=True, separators=(",", ":")))
            return 0
        if receipt_mode:
            try:
                return _handle_refresh_receipt(arguments, attested)
            except GuardFailure as failure:
                _print_failure(failure)
                return 2
        try:
            if producer_root is None:
                raise GuardFailure("G015")
            with _producer_lock(producer_root):
                return _run_graphify(arguments)
        except GuardFailure as failure:
            _print_failure(failure)
            return 2


if __name__ == "__main__":
    raise SystemExit(main())
