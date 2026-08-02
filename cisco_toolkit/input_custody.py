"""Process-local byte custody for raw evidence consumed through path-based parsers.

The assessment engine binds every capture digest before analysis.  Readers then re-read through
this module and receive bytes only when that stable read matches the binding.  A mismatch is
remembered for the whole run, so restoring the original file later cannot erase evidence that a
parser encountered a changed input.
"""
from __future__ import annotations

import hashlib
import os
import threading
from typing import Dict, Iterable, List, Tuple


class BoundInputMutationError(RuntimeError):
    """A bound path was unavailable, unstable, or no longer matched its analysis digest."""


_LOCK = threading.RLock()
_BINDINGS: Dict[str, dict] = {}
_FAILURES: Dict[str, dict] = {}


def _key(path: str) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


def _fingerprint(st) -> Tuple[int, int, int, int]:
    return (int(st.st_dev), int(st.st_ino), int(st.st_size), int(st.st_mtime_ns))


def reset() -> None:
    """Clear bindings/failures at the start of each in-process engine run."""
    with _LOCK:
        _BINDINGS.clear()
        _FAILURES.clear()


def bind_files(bindings: Iterable[dict]) -> None:
    """Install ``{path,name,size,sha256}`` records captured before the first parser runs."""
    prepared = {}
    for row in bindings or []:
        path = os.path.abspath(str(row["path"]))
        prepared[_key(path)] = {
            "path": path,
            "name": str(row.get("name") or os.path.basename(path)),
            "size": int(row["size"]),
            "sha256": str(row["sha256"]),
        }
    with _LOCK:
        _BINDINGS.clear()
        _BINDINGS.update(prepared)
        # `_FAILURES` is deliberately NOT cleared here. This module's contract is that a mismatch is
        # "remembered for the whole run, so restoring the original file later cannot erase evidence"
        # — and clearing on re-bind made that false: a tamper detected, then a second `bind_files`
        # call, and `failures()` was empty again. Re-binding installs a new expectation; it does not
        # un-observe a mutation that already happened. `reset()` remains the ONE way to clear, which
        # is what a genuinely new run calls.


def _remember(binding: dict, reason: str) -> None:
    with _LOCK:
        _FAILURES.setdefault(_key(binding["path"]), {
            "name": binding["name"],
            "reason": str(reason)[:300],
        })


def failures() -> List[dict]:
    """Content-free, bounded mutation ledger for mandatory finalization."""
    with _LOCK:
        return [dict(row) for _path, row in sorted(_FAILURES.items())]


def read_bytes(path: str) -> bytes:
    """Return one stable read, enforcing the pre-analysis digest when the path is bound."""
    p = os.path.abspath(str(path))
    with _LOCK:
        binding = _BINDINGS.get(_key(p))
    try:
        path_before = os.stat(p)
        with open(p, "rb") as fh:
            handle_before = os.fstat(fh.fileno())
            if _fingerprint(path_before) != _fingerprint(handle_before):
                raise BoundInputMutationError("path changed before the read handle opened")
            data = fh.read()
            handle_after = os.fstat(fh.fileno())
        path_after = os.stat(p)
        expected = _fingerprint(handle_before)
        if _fingerprint(handle_after) != expected or \
                _fingerprint(path_after) != expected or len(data) != handle_before.st_size:
            raise BoundInputMutationError("path changed while bytes were being read")
        if binding:
            digest = hashlib.sha256(data).hexdigest()
            if len(data) != binding["size"] or digest != binding["sha256"]:
                raise BoundInputMutationError(
                    "bytes differ from the pre-analysis custody binding")
        return data
    except (OSError, BoundInputMutationError) as exc:
        if binding:
            _remember(binding, f"{type(exc).__name__}: {exc}")
            raise BoundInputMutationError(
                f"{binding['name']} failed its raw-evidence byte binding") from exc
        raise


def read_text(path: str, *, encoding: str = "utf-8",
              errors: str = "strict") -> str:
    return read_bytes(path).decode(encoding, errors=errors)
