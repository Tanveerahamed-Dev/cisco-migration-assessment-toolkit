"""Sealed, navigable run-manifest chain-of-custody (roadmap D2 + J4) — offline, deterministic.

The offline answer to NetClaw's GAIT immutable transcript: an append-only, hash-chained ledger of the
assessment pipeline's steps. Each row carries `prev_sha256` and a `sha256` over `(prev_sha256 + canonical
step payload)`, so editing any earlier row breaks every hash after it — without a Git (or any) dependency.
Pure stdlib `hashlib`; no LLM, no network; determinism is the whole point (same inputs -> same chain),
which is why it is the engine's seal and not NetClaw's non-deterministic agent transcript.

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
broken), and on a Python-less stick the same check is ``Atlas.exe --verify-manifest <path>``.
"""
from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Dict, List, Optional, Tuple

GENESIS = "0" * 64
_RESERVED = ("seq", "prev_sha256", "sha256")

#: Stage name of the synthesized final chain row that seals the per-artifact digests
#: (see :func:`build_manifest`). Manifests produced before this existed have no such row —
#: :func:`verify_file` says so rather than implying coverage it cannot check.
SEAL_ARTIFACTS = "seal_artifacts"

#: Windows reserved device names. ``open("NUL")`` succeeds on Windows and reads as an empty file,
#: so an artifact named NUL whose sealed digest is the (publicly known) sha256 of b"" verified
#: "ok" from an EMPTY folder. Names are matched on the stem, case-insensitively.
_WIN_DEVICES = frozenset(
    ["CON", "PRN", "AUX", "NUL"]
    + [f"COM{i}" for i in range(1, 10)] + [f"LPT{i}" for i in range(1, 10)])


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


def build_manifest(meta: Dict[str, Any], artifacts: Dict[str, str], steps: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Assemble the run manifest: provenance metadata + per-artifact sha256 + the sealed step chain.

    `meta` carries schema_version / generated_at / collected_at / devices_file_sha256 / abstention_ledger;
    `artifacts` is {name: sha256}; `steps` is the ordered pipeline ledger. `chain_root` is the final hash,
    a single value that seals the entire run."""
    meta = meta or {}
    rows = [{"name": n, "sha256": s} for n, s in sorted((artifacts or {}).items())]
    # Seal the per-artifact DIGESTS into the chain, not just alongside it. Before this, `artifacts`
    # sat entirely outside `chain`/`chain_root` (the pipeline's own steps carry artifact NAMES only),
    # so swapping a delivered workbook and updating its sha256 in this list left chain_root
    # untouched — and BOTH `verify --artifacts` and `--expect-root` reported clean. A
    # chain-of-custody seal whose whole purpose is "is this the workbook that was sealed?" cannot
    # leave the answer unsealed. `verify_file` cross-checks the two copies (:func:`_sealed_artifacts`).
    chain = hash_chain(list(steps or []) + [{"stage": SEAL_ARTIFACTS, "artifacts": rows}])
    return {
        "tool": meta.get("tool", "cisco-assess"),
        "schema_version": meta.get("schema_version"),
        "generated_at": meta.get("generated_at"),
        "collected_at": meta.get("collected_at"),
        "devices_file_sha256": meta.get("devices_file_sha256"),
        "artifacts": rows,
        "abstention_ledger": meta.get("abstention_ledger") or {},
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
    if "\x00" in name:
        # open() raises ValueError (NOT OSError) on an embedded NUL, which the caller's
        # `except OSError` would not catch — a corrupted JSON string crashed the auditor's CLI.
        return False
    if name.split(".")[0].strip().upper() in _WIN_DEVICES:
        # Not a path escape, but not a file either: on Windows these open successfully and read
        # as empty, so a fabricated artifact named NUL carrying sha256(b"") verified "ok" out of
        # an empty folder. Refused on every OS so a manifest verifies identically everywhere.
        return False
    parts = name.replace("\\", "/").split("/")
    return len(parts) == 1 and parts[0] not in ("", ".", "..")


def _sealed_artifacts(chain: List[Dict[str, Any]]) -> Optional[List[Dict[str, Any]]]:
    """The artifact digests sealed INSIDE the chain, or ``None`` for a manifest sealed before
    :data:`SEAL_ARTIFACTS` existed (absence is reported, never treated as agreement)."""
    for row in reversed(chain):
        if isinstance(row, dict) and row.get("stage") == SEAL_ARTIFACTS:
            got = row.get("artifacts")
            return got if isinstance(got, list) else []
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
        bad_a = [i for i, a in enumerate(arts) if not isinstance(a, dict)]
        if bad_a:
            return (f"{len(bad_a)} artifact entr(ies) are not objects (first at index {bad_a[0]}) "
                    f"— the artifact list is malformed")
    return None


def verify_file(path: str, expect_root: Optional[str] = None,
                artifacts_dir: Optional[str] = None) -> Dict[str, Any]:
    """Verify a delivered ``*.run_manifest.json`` on disk. Returns
    ``{ok, reason, broken, chain_root, artifacts}`` — never raises for a bad file, because the caller
    is a CLI whose whole job is to report the bad file.

    Three independent checks, each of which can only FAIL the result:

    * the hash chain reconciles to its own sealed ``chain_root`` (:func:`verify_manifest`);
    * ``expect_root``, when given, matches — the only check a re-sealing forger cannot pass, since it
      pins the file to a root carried out of band (see the module docstring);
    * ``artifacts_dir``, when given, re-hashes every listed deliverable there. A MISSING artifact fails
      as loudly as a MISMATCHed one: a manifest naming a file you were not given is incomplete custody,
      and "not present" must never quietly read as "verified" (coverage honesty).
    """
    try:
        # utf-8-SIG: strips a BOM if present and is identical to utf-8 when absent. The producer
        # never writes one, but a manifest that merely passed through a Windows tool acquires one,
        # and rejecting an untampered file as unreadable is a false alarm at a client site.
        with open(path, encoding="utf-8-sig") as f:
            man = json.load(f)
    except (OSError, ValueError) as e:
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
    listed = [{"name": str(a.get("name") or ""), "sha256": str(a.get("sha256") or "")}
              for a in (man.get("artifacts") or [])]
    if sealed is None:
        reason += ("; NOTE this manifest predates artifact sealing, so its artifact digests are "
                   "NOT covered by chain_root — re-hash the files and compare out of band")
    elif sealed != listed:
        ok = False
        reason += ("; ARTIFACT LIST ALTERED — the delivered list no longer matches the copy sealed "
                   "in the chain, so a deliverable was swapped or its digest rewritten")

    checked: List[Dict[str, str]] = []
    if artifacts_dir is not None:
        bad = 0
        for a in man.get("artifacts") or []:
            name, want_sha = str(a.get("name") or ""), str(a.get("sha256") or "")
            if not _is_confined(name):
                # The manifest is UNTRUSTED input — it arrives from wherever the deliverable set has
                # been. os.path.join DISCARDS artifacts_dir for an absolute/UNC name, and "../" walks
                # out of it, so a crafted manifest turns `verify --artifacts` into a read-and-hash
                # oracle over the auditor's disk. The real producer only ever writes basenames
                # (COLLECT_PARSE build_run_manifest -> os.path.basename), so anything else is refused
                # unopened rather than normalised into something plausible.
                state = "INVALID"
            else:
                try:
                    with open(os.path.join(artifacts_dir, name), "rb") as fh:
                        got = artifact_sha256(fh.read())
                    state = "ok" if got == want_sha else "MISMATCH"
                except (OSError, ValueError):   # ValueError: embedded NUL is not an OSError
                    state = "MISSING"
            if state != "ok":
                bad += 1
            checked.append({"name": name, "state": state})
        if bad:
            ok = False
            reason += (f"; {bad} of {len(checked)} artifact(s) do not match the seal (MISMATCH = "
                       f"altered after sealing, MISSING = not in {artifacts_dir}, INVALID = the "
                       f"manifest named a path outside that folder and was not opened)")
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
                   help="also re-hash every listed deliverable (default: the manifest's own folder). "
                        "A missing artifact fails, like a mismatched one")
    args = parser.parse_args(argv)
    if args.cmd != "verify":
        parser.print_help()
        return 0

    art = args.artifacts
    if art == "":                                    # bare --artifacts -> beside the manifest
        art = os.path.dirname(os.path.abspath(args.path)) or "."
    res = verify_file(args.path, expect_root=args.expect_root, artifacts_dir=art)
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
