"""Sealed, navigable run-manifest chain-of-custody (roadmap D2 + J4) — offline, deterministic.

The offline answer to NetClaw's GAIT immutable transcript: an append-only, hash-chained ledger of the
assessment pipeline's steps. Each row carries `prev_sha256` and a `sha256` over `(prev_sha256 + canonical
step payload)`, so editing any earlier row breaks every hash after it — without a Git (or any) dependency.
Pure stdlib `hashlib`; no LLM, no network; determinism is the whole point (same inputs -> same chain),
which is why it is the engine's seal and not NetClaw's non-deterministic agent transcript.

SCOPE OF "append-only" — the property holds WITHIN one sealed manifest: rows are only ever appended to a
chain, and any edit to an earlier row invalidates every hash after it. It is NOT a claim that manifests
accumulate across runs. `COLLECT_PARSE_V3_23_0.build_run_manifest` seals one run's artifact set, and a
re-run to the same `--output` replaces that file along with the artifacts it hashes (a manifest outliving
its artifacts would seal files that no longer exist). Read a manifest as "this artifact set, sealed", not
as an engagement history; the append-across-runs ledger is `cisco_toolkit.gate_state`'s audit array.

**Scope the seal honestly.** The chain is UNKEYED and :func:`build_manifest` is public, so anyone holding
the file can re-seal an edited ledger into a clean ``chain_root``. What this detects is a CARELESS edit,
a deletion or a truncation — not a determined forger. ``verify --expect-root`` raises that bar: a
``chain_root`` carried OUT OF BAND (the report, the engagement email) pins the delivered file to the run
that produced it, and a re-seal cannot match it. Say "detects careless edits" wherever this is described;
"tamper-proof" would be a false claim, and an auditor acting on it is the harm.

That bar is only as wide as what the chain actually covers. It originally covered the pipeline steps
and the artifact NAMES but not the artifact DIGESTS, which sat outside ``chain_root`` entirely — so
swapping a delivered workbook and rewriting its ``sha256`` in the top-level list passed ``--artifacts``
AND ``--expect-root``, the two checks that exist to answer "is this the workbook that was sealed?".
:func:`build_manifest` now seals the digests as a final :data:`SEAL_ARTIFACTS` chain row and
:func:`verify_file` reconciles the two copies. A manifest produced before that change has no such row;
verification says so explicitly rather than implying coverage it cannot check.

Auditor surface: ``python -m cisco_toolkit.manifest verify <run_manifest.json>`` (exit 0 clean / 4
broken). It verifies the listed artifact bytes beside the manifest by default; ``--metadata-only`` is
the explicit opt-out for a deliberately separated manifest. Provenance, input/evidence records,
abstentions and redaction metadata are committed through :data:`SEAL_METADATA`, not loose claims
outside the root. On a Python-less stick the same check is ``Atlas.exe --verify-manifest <path>``.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

GENESIS = "0" * 64
_RESERVED = ("seq", "prev_sha256", "sha256")

#: Stage name of the synthesized final chain row that seals the per-artifact digests
#: (see :func:`build_manifest`). Manifests produced before this existed have no such row —
#: :func:`verify_file` says so rather than implying coverage it cannot check.
SEAL_ARTIFACTS = "seal_artifacts"

#: Stage name of the synthesized row that seals every provenance/coverage metadata field. Metadata
#: used to be copied into loose top-level keys where it could be edited without changing chain_root.
SEAL_METADATA = "seal_metadata"

#: Version of the manifest envelope (independent of the assessment snapshot schema version).
MANIFEST_FORMAT = 2

#: Windows reserved device names. ``open("NUL")`` succeeds on Windows and reads as an empty file,
#: so an artifact named NUL whose sealed digest is the (publicly known) sha256 of b"" verified
#: "ok" from an EMPTY folder. Names are matched on the stem, case-insensitively.
_WIN_DEVICES = frozenset(
    ["CON", "PRN", "AUX", "NUL"]
    + [f"COM{i}" for i in range(1, 10)] + [f"LPT{i}" for i in range(1, 10)])
_MAX_MANIFEST_BYTES = 16 * 1024 * 1024
_MAX_CHAIN_ROWS = 10_000
_MAX_ARTIFACTS = 4_096
_MAX_ARTIFACT_BYTES = 4 * 1024 * 1024 * 1024
_HASH_CHUNK_BYTES = 1024 * 1024


def _canon(obj: Any) -> str:
    # A deterministic, process-independent default for non-JSON values (NO repr/memory address), so the
    # seal can never silently become process-nondeterministic.
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=lambda o: "<%s>" % type(o).__name__)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _payload(seq: Any, step: Dict[str, Any]) -> str:
    """The canonical sealed payload for one row: the engine-owned ``seq`` PLUS the caller's non-reserved
    step fields. Sealing seq makes the ordering tamper-evident; stripping reserved keys makes a caller
    field that happens to be named ``sha256``/``seq`` collision-safe (seal and verify strip identically)."""
    data = {k: v for k, v in (step or {}).items() if k not in _RESERVED}
    return _canon({"seq": seq, "step": data})


def hash_chain(steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Seal an ordered list of step dicts into a hash chain. Each output row = the step's non-reserved
    fields plus ``seq`` / ``prev_sha256`` / ``sha256``; row N's hash commits to row N-1's hash AND to N's
    own ``seq``. (``seq``/``sha256``/``prev_sha256`` are engine-owned; a caller key of those names is dropped.)"""
    out: List[Dict[str, Any]] = []
    prev = GENESIS
    for i, step in enumerate(steps or []):
        sha = _sha(prev + _payload(i, step))
        data = {k: v for k, v in (step or {}).items() if k not in _RESERVED}
        row = dict(data)
        row.update(seq=i, prev_sha256=prev, sha256=sha)
        out.append(row)
        prev = sha
    return out


def verify_chain(chain: List[Dict[str, Any]], expected_root: Optional[str] = None) -> Tuple[bool, List[int]]:
    """Recompute the chain and report (ok, [indices of broken rows]). A row is broken if its stored
    ``sha256`` doesn't match its recomputed value (covering the step fields AND ``seq``), or its
    ``prev_sha256`` doesn't link to the prior row. Pass ``expected_root`` (the sealed ``chain_root``) to
    also catch TAIL-TRUNCATION: a dropped tail leaves a self-consistent prefix that otherwise verifies clean."""
    broken: List[int] = []
    expect_prev = GENESIS
    for i, row in enumerate(chain or []):
        step = {k: v for k, v in row.items() if k not in _RESERVED}
        recomputed = _sha(str(row.get("prev_sha256", "")) + _payload(row.get("seq"), step))
        if row.get("prev_sha256") != expect_prev or row.get("sha256") != recomputed:
            broken.append(i)
        expect_prev = row.get("sha256")
    ok = len(broken) == 0
    if expected_root is not None and (not chain or chain[-1].get("sha256") != expected_root):
        ok = False
        last = (len(chain) - 1) if chain else 0
        if last not in broken:
            broken.append(last)
    return (ok, broken)


def verify_manifest(man: Dict[str, Any]) -> Tuple[bool, List[int]]:
    """Verify a whole manifest: the chain reconciles AND its sealed ``chain_root`` still matches the chain's
    last hash (so a truncated/edited chain is caught even though the prefix is internally consistent)."""
    man = man or {}
    return verify_chain(man.get("chain") or [], expected_root=man.get("chain_root"))


def artifact_sha256(data: bytes) -> str:
    return hashlib.sha256(data or b"").hexdigest()


def _is_sha256_digest(value: Any) -> bool:
    """Canonical lowercase SHA-256 without accepting lookalike/partial digests."""
    return (
        isinstance(value, str)
        and len(value) == 64
        and value == value.lower()
        and all(ch in "0123456789abcdef" for ch in value)
    )


def _is_reparse(st: os.stat_result) -> bool:
    marker = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(marker and getattr(st, "st_file_attributes", 0) & marker)


def _open_regular_no_follow(path: str):
    """Open a regular file while refusing final-component links/reparse points.

    ``O_NOFOLLOW`` closes the final-component race on platforms that expose it.  Windows does not
    expose that flag through :mod:`os`, so the reparse attribute and file identity are checked both
    before and after opening; the verifier never follows a link that was already present.
    """
    before = os.lstat(path)
    if stat.S_ISLNK(before.st_mode) or _is_reparse(before) or not stat.S_ISREG(before.st_mode):
        raise ValueError("path is not a regular non-link file")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        opened = os.fstat(fd)
        after = os.lstat(path)
        if (
            not stat.S_ISREG(opened.st_mode)
            or _is_reparse(opened)
            or stat.S_ISLNK(after.st_mode)
            or _is_reparse(after)
            or (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino)
            or (after.st_dev, after.st_ino) != (opened.st_dev, opened.st_ino)
        ):
            raise ValueError("file identity changed or resolves through a link/reparse point")
        return os.fdopen(fd, "rb")
    except Exception:
        os.close(fd)
        raise


def _stream_file_sha256(path: str, *, max_bytes: int) -> Tuple[str, int]:
    st = os.lstat(path)
    if st.st_size > max_bytes:
        raise OverflowError(f"file is {st.st_size} bytes; limit is {max_bytes}")
    digest = hashlib.sha256()
    total = 0
    with _open_regular_no_follow(path) as handle:
        while True:
            chunk = handle.read(_HASH_CHUNK_BYTES)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise OverflowError(f"file exceeds the {max_bytes}-byte verification limit")
            digest.update(chunk)
    return digest.hexdigest(), total


def _strict_manifest_json(raw: bytes) -> Any:
    def object_pairs(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise ValueError(f"duplicate JSON key {key!r}")
            out[key] = value
        return out

    def reject_constant(value):
        raise ValueError(f"non-standard JSON constant {value}")

    return json.loads(
        raw.decode("utf-8-sig"),
        object_pairs_hook=object_pairs,
        parse_constant=reject_constant,
    )


def _json_value(value: Any) -> Any:
    """Return the deterministic JSON value actually committed to the chain."""
    return json.loads(_canon(value))


def _artifact_rows(artifacts: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Normalize legacy and rich artifact mappings into sealed rows."""
    rows: List[Dict[str, Any]] = []
    for name, value in sorted((artifacts or {}).items()):
        if isinstance(value, dict):
            row = {str(k): _json_value(v) for k, v in value.items() if k != "name"}
            row = {"name": str(name), **row}
        else:
            row = {"name": str(name), "sha256": str(value)}
        rows.append(row)
    return rows


def build_manifest(meta: Dict[str, Any], artifacts: Dict[str, Any],
                   steps: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Assemble a manifest whose root commits to every custody claim.

    ``meta`` is open-ended: input hashes, raw-evidence records, abstentions, redaction provenance
    and future fields are preserved rather than silently dropped. ``artifacts`` accepts the legacy
    ``{name: sha256}`` shape or rich per-file records containing size/kind/source.
    """
    metadata = _json_value(meta or {})
    if not isinstance(metadata, dict):
        raise TypeError("manifest metadata must be an object")
    metadata.setdefault("tool", "cisco-assess")
    metadata["manifest_format"] = MANIFEST_FORMAT
    rows = _artifact_rows(artifacts)
    chain = hash_chain(list(steps or []) + [
        {"stage": SEAL_METADATA, "metadata": metadata},
        {"stage": SEAL_ARTIFACTS, "artifacts": rows},
    ])
    # Historic headline keys remain compatibility caches. ``metadata`` is the complete authoritative
    # copy and verify_file rejects any cache which disagrees with it.
    return {
        "manifest_format": MANIFEST_FORMAT,
        "tool": metadata.get("tool"),
        "schema_version": metadata.get("schema_version"),
        "generated_at": metadata.get("generated_at"),
        "collected_at": metadata.get("collected_at"),
        "devices_file_sha256": metadata.get("devices_file_sha256"),
        "abstention_ledger": metadata.get("abstention_ledger") or {},
        "metadata": metadata,
        "artifacts": rows,
        "chain": chain,
        "chain_root": chain[-1]["sha256"] if chain else GENESIS,
    }


# --- auditor surface ------------------------------------------------------------------------------

def _is_confined(name: str) -> bool:
    """Is ``name`` a plain file name that stays inside the folder it is joined to?

    Deliberately a WHITELIST, not a blacklist of bad patterns: the only names the producer ever
    emits are basenames, so anything with a directory separator, a drive letter, a UNC prefix or a
    ``..`` component is rejected without being opened. Checked on both separators regardless of
    host OS — a manifest sealed on Windows gets verified on the auditor's Linux box and vice versa,
    and ``ntpath``/``posixpath`` disagree about which slash escapes."""
    if not name or name in (".", ".."):
        return False
    if ":" in name or name.startswith(("/", "\\", "~")):        # drive-qualified, absolute or UNC
        return False
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in name):
        # Embedded NUL raises ValueError (not OSError); other controls make file/audit names
        # ambiguous, so all are refused before a filesystem call.
        return False
    if name.rstrip(". ") != name:
        # Windows silently strips these suffixes while opening, creating an alias.
        return False
    if name.split(".")[0].strip().upper() in _WIN_DEVICES:
        # Not a path escape, but not a file either: on Windows these open successfully and read
        # as empty, so a fabricated artifact named NUL carrying sha256(b"") verified "ok" out of
        # an empty folder. Refused on every OS so a manifest verifies identically everywhere.
        return False
    parts = name.replace("\\", "/").split("/")
    return len(parts) == 1 and parts[0] not in ("", ".", "..")


def _portable_artifact_name_key(name: str) -> str:
    """The most collision-prone portable spelling of an artifact basename."""
    return unicodedata.normalize("NFKC", str(name)).rstrip(". ").casefold()


def _sealed_artifacts(chain: List[Dict[str, Any]]) -> Optional[List[Dict[str, Any]]]:
    """The artifact digests sealed INSIDE the chain, or ``None`` for a manifest sealed before
    :data:`SEAL_ARTIFACTS` existed (absence is reported, never treated as agreement)."""
    for row in reversed(chain):
        if isinstance(row, dict) and row.get("stage") == SEAL_ARTIFACTS:
            got = row.get("artifacts")
            return got if isinstance(got, list) else []
    return None


def _sealed_metadata(chain: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The complete metadata object sealed inside the chain, or ``None`` for a legacy manifest."""
    for row in reversed(chain):
        if isinstance(row, dict) and row.get("stage") == SEAL_METADATA:
            got = row.get("metadata")
            return got if isinstance(got, dict) else {}
    return None


def _structural_problem(man: Dict[str, Any]) -> Optional[str]:
    """Why this object cannot be verified at all, or ``None`` if it is shaped like a manifest.

    The manifest is UNTRUSTED input — it arrives from a share, a client, a partial write. A
    wrong-typed ``chain`` (dict/str/int) or a non-dict row used to raise AttributeError/TypeError
    straight out of the CLI: a traceback and exit 1, where the contract is a sentence and exit 4.
    Same wrong-typed-value class the stored-DoS wave (#462-#475) fixed across the deliverables."""
    chain = man.get("chain")
    if chain is None:
        return "carries no chain — there is nothing sealed here to verify"
    if not isinstance(chain, list):
        return f"'chain' is {type(chain).__name__}, not a list of steps — this is not a manifest"
    if not chain:
        return "carries no chain — there is nothing sealed here to verify"
    if len(chain) > _MAX_CHAIN_ROWS:
        return f"carries {len(chain)} chain rows; limit is {_MAX_CHAIN_ROWS}"
    bad = [i for i, row in enumerate(chain) if not isinstance(row, dict)]
    if bad:
        return (f"{len(bad)} chain row(s) are not objects (first at index {bad[0]}, "
                f"{type(chain[bad[0]]).__name__}) — the ledger is malformed, not merely edited")
    root = man.get("chain_root")
    if not isinstance(root, str) or not root.strip():
        # verify_chain skips its tail check when expected_root is None, so a manifest whose root
        # was deleted or nulled had its truncation check silently switched OFF: drop rows, null
        # the root, and a gutted ledger verified as clean as an intact one.
        return ("has no sealed chain_root, so a dropped tail cannot be detected — an unsealed "
                "ledger is not a weaker seal, it is no seal")
    arts = man.get("artifacts")
    if arts is not None and not isinstance(arts, list):
        return f"'artifacts' is {type(arts).__name__}, not a list"
    if isinstance(arts, list):
        if len(arts) > _MAX_ARTIFACTS:
            return f"carries {len(arts)} artifacts; limit is {_MAX_ARTIFACTS}"
        bad_a = [i for i, a in enumerate(arts) if not isinstance(a, dict)]
        if bad_a:
            return (f"{len(bad_a)} artifact entr(ies) are not objects (first at index {bad_a[0]}) "
                    f"— the artifact list is malformed")
        names = [
            str(row.get("name") or "")
            for row in arts
            if _is_confined(str(row.get("name") or ""))
        ]
        portable = [_portable_artifact_name_key(name) for name in names]
        if len(set(portable)) != len(portable):
            return (
                "carries artifact names that collide under portable Unicode/Windows "
                "normalization; one delivered file could satisfy multiple manifest rows"
            )
    metadata = man.get("metadata")
    if metadata is not None and not isinstance(metadata, dict):
        return f"'metadata' is {type(metadata).__name__}, not an object"
    return None


def verify_file(path: str, expect_root: Optional[str] = None,
                artifacts_dir: Optional[str] = None, *,
                metadata_only: bool = False) -> Dict[str, Any]:
    """Verify a delivered ``*.run_manifest.json`` on disk. Returns
    ``{ok, reason, broken, chain_root, artifacts}`` — never raises for a bad file, because the caller
    is a CLI whose whole job is to report the bad file.

    Three independent checks, each of which can only FAIL the result:

    * the hash chain reconciles to its own sealed ``chain_root`` (:func:`verify_manifest`);
    * ``expect_root``, when given, matches — the only check a re-sealing forger cannot pass, since it
      pins the file to a root carried out of band (see the module docstring);
    * every listed deliverable is re-hashed beside the manifest by default. ``artifacts_dir`` may
      select another folder. A MISSING artifact fails as loudly as a MISMATCHed one: a manifest naming
      a file you were not given is incomplete custody. ``metadata_only=True`` is the explicit opt-out
      for an intentionally separated manifest.
    """
    try:
        manifest_stat = os.lstat(path)
        if manifest_stat.st_size > _MAX_MANIFEST_BYTES:
            raise OverflowError(
                f"manifest is {manifest_stat.st_size} bytes; limit is {_MAX_MANIFEST_BYTES}"
            )
        # utf-8-SIG strips a BOM if present and is identical to utf-8 when absent. The producer
        # never writes one, but a manifest that merely passed through a Windows tool acquires one.
        with _open_regular_no_follow(path) as f:
            raw_manifest = f.read(_MAX_MANIFEST_BYTES + 1)
        if len(raw_manifest) > _MAX_MANIFEST_BYTES:
            raise OverflowError(
                f"manifest exceeds the {_MAX_MANIFEST_BYTES}-byte verification limit"
            )
        man = _strict_manifest_json(raw_manifest)
    except (OSError, UnicodeError, ValueError, OverflowError, RecursionError) as e:
        # RecursionError is NOT a ValueError, so deeply nested JSON escaped this handler and broke
        # this function's documented contract ("never raises for a bad file, because the caller is a
        # CLI whose whole job is to report the bad file"). Reachable from `Atlas.exe
        # --verify-manifest` — the field auditor's surface for CLIENT-SUPPLIED manifests, i.e. exactly
        # the untrusted input this guard exists for. `_MAX_CHAIN_ROWS`/`_MAX_ARTIFACTS` cannot help:
        # they are enforced after the parse.
        return {"ok": False, "reason": f"cannot read manifest {path}: {e}",
                "broken": [], "chain_root": None, "artifacts": []}
    if not isinstance(man, dict):
        return {"ok": False, "reason": f"{path} is not a manifest object (got {type(man).__name__})",
                "broken": [], "chain_root": None, "artifacts": []}

    root = man.get("chain_root")
    # Absence is absence, never health: verify_manifest({}) is (True, []) because there is nothing
    # to contradict, so the emptiest possible file would otherwise be the easiest to "verify".
    problem = _structural_problem(man)
    if problem:
        return {"ok": False, "chain_root": root, "broken": [], "artifacts": [],
                "reason": f"{path} {problem}"}
    chain = man["chain"]
    n = len(chain)

    ok, broken = verify_manifest(man)
    if ok:
        reason = f"chain of {n} step(s) reconciles to chain_root {str(root)[:16]}…"
    elif verify_chain(chain)[0]:
        # Every row self-reconciles but the sealed root does not match the tail: rows were REMOVED
        # from the end. Saying "broken at row N" there points the auditor at an intact row.
        reason = (f"chain TRUNCATED — its {n} step(s) are internally consistent but do not reach the "
                  f"sealed chain_root {str(root)[:16]}…, so step(s) were dropped from the end")
    else:
        reason = f"chain BROKEN at row(s) {broken} of {n} — the sealed ledger was edited"

    if expect_root is not None:          # not `if expect_root:` — an empty --expect-root must FAIL
        want = str(expect_root).strip().lower()   # loudly, never quietly skip the check it asked for
        if len(want) != 64 or any(c not in "0123456789abcdef" for c in want):
            # The engine's own console line prints chain_root truncated to 12 chars, so a partial
            # root is the likeliest thing an engineer copies. Reporting that as "not the manifest
            # that run produced" would have them reject a GENUINE deliverable set at a client site.
            ok = False
            reason = (f"--expect-root is not a full chain_root ({len(want)} chars, need 64 hex). "
                      f"The end-of-run console line shortens it — copy the whole value out of the "
                      f"manifest's \"chain_root\" field. Not checked against the file.")
        elif str(root).strip().lower() != want:
            ok = False
            reason = (f"chain_root MISMATCH: file has {str(root)[:16]}…, expected {want[:16]}… "
                      f"— this is not the manifest that run produced")

    # Does the delivered artifact list still match the copy sealed INSIDE the chain? Without this,
    # editing a top-level artifact digest was invisible to BOTH the chain and --expect-root, so a
    # swapped deliverable passed every check the tool offered.
    sealed = _sealed_artifacts(chain)
    listed = _json_value(man.get("artifacts") or [])
    if sealed is None:
        reason += ("; NOTE this manifest predates artifact sealing, so its artifact digests are "
                    "NOT covered by chain_root — re-hash the files and compare out of band")
    elif sealed != listed:
        ok = False
        reason += ("; ARTIFACT LIST ALTERED — the delivered list no longer matches the copy sealed "
                   "in the chain, so a deliverable was swapped or its digest rewritten")

    sealed_meta = _sealed_metadata(chain)
    if sealed_meta is None:
        reason += ("; NOTE this manifest predates metadata sealing, so its provenance/abstention "
                   "fields are NOT covered by chain_root")
    else:
        listed_meta = man.get("metadata")
        if listed_meta != sealed_meta:
            ok = False
            reason += ("; METADATA ALTERED — the top-level metadata no longer matches the complete "
                       "copy sealed in the chain")
        # The old headline fields are caches for existing consumers. They must not be an alternate,
        # editable truth surface beside the sealed metadata.
        for key in ("manifest_format", "tool", "schema_version", "generated_at", "collected_at",
                    "devices_file_sha256", "abstention_ledger"):
            expected = (sealed_meta.get("abstention_ledger") or {}) if key == "abstention_ledger" \
                else sealed_meta.get(key)
            if man.get(key) != expected:
                ok = False
                reason += f"; METADATA CACHE ALTERED ({key})"

    checked: List[Dict[str, str]] = []
    if metadata_only:
        reason += "; artifact bytes NOT checked (--metadata-only was explicitly requested)"
    else:
        if artifacts_dir is None:
            artifacts_dir = os.path.dirname(os.path.abspath(path)) or "."
        artifacts_dir = os.path.abspath(artifacts_dir)
        bad = 0
        for a in man.get("artifacts") or []:
            name, want_sha = str(a.get("name") or ""), str(a.get("sha256") or "")
            if (
                not _is_confined(name)
                or not _is_sha256_digest(want_sha)
            ):
                # The manifest is UNTRUSTED input — it arrives from wherever the deliverable set has
                # been. os.path.join DISCARDS artifacts_dir for an absolute/UNC name, and "../" walks
                # out of it, so a crafted manifest turns `verify --artifacts` into a read-and-hash
                # oracle over the auditor's disk. The real producer only ever writes basenames
                # (COLLECT_PARSE build_run_manifest -> os.path.basename), so anything else is refused
                # unopened rather than normalised into something plausible.
                state = "INVALID"
            else:
                candidate = os.path.join(artifacts_dir, name)
                try:
                    got, _size = _stream_file_sha256(
                        candidate,
                        max_bytes=_MAX_ARTIFACT_BYTES,
                    )
                    state = "ok" if got == want_sha else "MISMATCH"
                except FileNotFoundError:
                    state = "MISSING"
                except OverflowError:
                    state = "OVERSIZE"
                except ValueError:
                    state = "INVALID"
                except OSError:
                    state = "UNREADABLE"
            if state != "ok":
                bad += 1
            checked.append({"name": name, "state": state})
        if bad:
            ok = False
            reason += (
                f"; {bad} of {len(checked)} artifact(s) do not match the seal "
                "(MISMATCH=altered, MISSING=absent, UNREADABLE=I/O refused, "
                "OVERSIZE=verification bound exceeded, INVALID=unsafe path/hash/link/non-file)"
            )
        elif checked:
            reason += f"; all {len(checked)} artifact(s) hash to the seal"
    return {"ok": ok, "reason": reason, "broken": broken, "chain_root": root, "artifacts": checked}


def main(argv: Optional[List[str]] = None) -> int:
    """``verify <path>`` — the shipped command an auditor runs against a delivered run manifest.
    Exit 0 clean / 4 broken-or-unreadable, the same OK/INTEGRITY language as
    ``python -m cisco_toolkit.holdout verify`` (which seals with this same chain)."""
    import argparse
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    parser = argparse.ArgumentParser(
        prog="python -m cisco_toolkit.manifest",
        description="Verify a sealed run manifest (<out>.run_manifest.json) emitted by cisco-assess.")
    sub = parser.add_subparsers(dest="cmd")
    p = sub.add_parser("verify", help="check that a delivered manifest's hash chain still reconciles")
    p.add_argument("path", help="path to a *.run_manifest.json")
    p.add_argument("--expect-root", default=None, metavar="SHA256",
                   help="the chain_root recorded OUT OF BAND for this run. The chain is unkeyed, so "
                        "this is the only check a re-sealing forger cannot pass")
    p.add_argument("--artifacts", nargs="?", const="", default=None, metavar="DIR",
                   help="re-hash listed deliverables in DIR instead of beside the manifest. Artifact "
                        "verification is already the default; a missing file fails like a mismatch")
    p.add_argument("--metadata-only", action="store_true",
                   help="explicitly verify only the sealed chain/metadata, without opening artifact "
                        "files. Use only when the manifest was intentionally separated from its files")
    args = parser.parse_args(argv)
    if args.cmd != "verify":
        parser.print_help()
        return 0

    if args.metadata_only and args.artifacts is not None:
        p.error("--metadata-only and --artifacts are mutually exclusive")
    art = args.artifacts
    if art in (None, ""):                            # default/bare --artifacts -> beside manifest
        art = os.path.dirname(os.path.abspath(args.path)) or "."
    res = verify_file(args.path, expect_root=args.expect_root, artifacts_dir=art,
                      metadata_only=args.metadata_only)
    print(("OK: " if res["ok"] else "INTEGRITY: ") + res["reason"])
    for a in res["artifacts"]:
        if a["state"] != "ok":
            print(f"  [{a['state']}] {a['name']}")
    if res["ok"] and not args.expect_root:
        # Never let a bare pass be read as "provably untampered" — the seal is unkeyed.
        print("  NOTE: an unkeyed chain detects careless edits, not a forger who re-seals. "
              "Re-run with --expect-root <chain_root from the report> to pin this file to its run.")
    return 0 if res["ok"] else 4


if __name__ == "__main__":
    raise SystemExit(main())
