"""Sealed 70/30 holdout over the REAL PIR-outcome rows — the DEC-007 activation tooling (P1-2).

Policy owner: ``docs/quality/holdout-contract.md`` (registered in docs/ssot.md); this module owns
the MECHANICS and the activation figure (:data:`ACTIVATION_FLOOR`). The contract exists BEFORE the
data: today the store holds zero REAL rows and the repo's existing gates stay in force unchanged
(:data:`cisco_toolkit.calibration.DEFAULT_N_FLOOR` REAL for any tuning proposal; N >= 20 as the
descriptive target — DEC-007's hybrid). When the REAL labelled rows reach N >= ACTIVATION_FLOOR,
:func:`seal` splits them 70/30 optimisation/holdout and freezes the holdout membership in a
committed, hash-chained manifest (the :mod:`cisco_toolkit.manifest` chain — the same mechanism as
the run ledger, but a STRONGER claim here: that chain is unkeyed, so on its own it only catches a
careless edit, and what closes the re-seal hole is COMMITTING the manifest — a forged re-seal has
to arrive as a visible change to a tracked file in a reviewed diff). Below the floor — and for surrogate rows in ANY quantity — sealing
REFUSES (:class:`HoldoutActivationError`): only ``source_class == REAL`` counts, decided by the
same discriminator the D11 gate uses (:func:`cisco_toolkit.calibration.normalize_outcome`), so a
surrogate flood can no more activate the holdout than it can unlock a tuning proposal.

**Audit trail, not proof (coverage honesty).** The holdout rows live in plaintext in the
append-only store; nothing on this machine can make them unreadable. What the seal + accessor
provide is (a) *tamper-evidence* — membership and content are frozen under a hash chain, so a
quiet swap or deletion breaks verification; (b) *attributable access* — the one sanctioned read
path (:func:`read_holdout` / ``python -m cisco_toolkit.holdout read --who <name>``) appends
who/when to the access log before it returns (and before it raises); and (c) *pre-registration* —
the split rule is fixed and committed before the data exists. **Mathematical proof of non-use does
not exist and is not claimed** — the access log is reviewed, never trusted as a guarantee.

Determinism: the split is content-addressed. Each REAL row is digested over its
calibration-normalized payload and assigned by ascending digest order, so the same rows seal to
the same ``chain_root`` whatever the store order or label spelling. The seal covers exactly the
semantic payload calibration reads (predicted/actual/source_class/date/engagement/unit/commit/
notes); an edit to any field outside that payload is outside the seal — said plainly, not implied
away. The manifest stores digests, never a second copy of the rows (the store stays the one owner
of the data — Law 1). Pure stdlib + this package; no LLM, no network.

CLI exit codes: 0 = ok · 2 = refusal (activation floor / unattributed or duplicate seal) ·
4 = integrity failure (mirrors ``selfcheck``'s RED).
"""
from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from cisco_toolkit import calibration
from cisco_toolkit.manifest import hash_chain, verify_chain

# The activation figure DEC-007 ratified: the sealed split activates at N >= 50 REAL labelled rows.
# This constant is the owner of the "50"; the contract and registry cite it, never restate it bare.
ACTIVATION_FLOOR = 50

# Holdout share of the REAL rows, in integer percent (70/30 optimisation/holdout). The holdout gets
# floor(real_n * 30 / 100) rows — integer arithmetic, no float rounding ambiguity (50 -> 15/35).
HOLDOUT_PCT = 30

CONTRACT_PATH = "docs/quality/holdout-contract.md"
MANIFEST_PATH = os.path.join("docs", "quality", "holdout_manifest.json")
ACCESS_LOG_PATH = os.path.join("docs", "quality", "holdout_access.jsonl")

_RESERVED = ("seq", "prev_sha256", "sha256")   # manifest.py's engine-owned chain keys


class HoldoutActivationError(ValueError):
    """Sealing refused: the DEC-007 activation criteria are not met (or a seal already exists)."""


class HoldoutIntegrityError(RuntimeError):
    """The sealed manifest does not verify against itself or against the store."""


def _canon(obj: Any) -> str:
    # Mirrors manifest._canon: deterministic and process-independent (no repr/memory address), so a
    # row digest can never silently vary between processes.
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      default=lambda o: "<%s>" % type(o).__name__)


def row_sha256(row: Any) -> Optional[str]:
    """Content digest of ONE outcome row, taken over its calibration-normalized payload — the exact
    fields the calibration nerve reads. Alias respellings (``pir`` -> ``REAL``, ``no-go`` ->
    ``NOT_READY``) digest identically (not tampering); flipping ``actual`` does not. ``None`` for a
    row calibration itself cannot use (malformed rows are never sealed — absence is absence)."""
    norm = calibration.normalize_outcome(row)
    if norm is None:
        return None
    return hashlib.sha256(_canon(norm).encode("utf-8")).hexdigest()


def activation_status(rows: List[Any], *, floor: int = ACTIVATION_FLOOR) -> Dict[str, Any]:
    """Is the DEC-007 seal allowed yet? Counts via :func:`calibration.calibration_gap` — the ONE
    source_class-aware counter (no second computation of real_n) — and says exactly why not."""
    gap = calibration.calibration_gap(rows)
    real_n, total = gap["real_n"], gap["n"]
    eligible = real_n >= floor
    if eligible:
        reason = (f"activation eligible: {real_n} REAL labelled rows >= floor {floor} (DEC-007) — "
                  f"seal() may create the one-time 70/30 optimisation/holdout manifest.")
    else:
        reason = (f"holdout activation refused: {real_n} REAL labelled rows < floor {floor} "
                  f"(store total {total}; surrogate rows NEVER count — DEC-007, same REAL-only rule "
                  f"as the D11 gate). The sealed split stays dormant; the existing gates "
                  f"(calibration.DEFAULT_N_FLOOR={calibration.DEFAULT_N_FLOOR} REAL to propose, "
                  f"N>=20 descriptive target) remain the only ones in force.")
    return {"eligible": eligible, "real_n": real_n, "n": total, "floor": floor,
            "by_source": gap["by_source"], "reason": reason}


def split_real_rows(rows: List[Any], *, holdout_pct: int = HOLDOUT_PCT) -> Dict[str, Any]:
    """Deterministic, content-addressed split of the REAL rows (normalized payloads). Rows are
    ordered by content digest ascending; the lowest ``floor(pct%)`` become the holdout. Nothing
    random, nothing order-dependent — anyone can recompute the membership, which is the point
    (the seal is tamper-evidence, not secrecy). Surrogate rows are not split: they are permanently
    descriptive-only (D11), so optimisation-set membership is meaningless for them."""
    valid_real = [o for o in (calibration.normalize_outcome(r) for r in (rows or []))
                  if o and o.get("source_class") == "REAL"]
    pairs = sorted(((hashlib.sha256(_canon(o).encode("utf-8")).hexdigest(), o) for o in valid_real),
                   key=lambda p: p[0])
    h_n = len(pairs) * holdout_pct // 100
    return {"real_n": len(pairs),
            "holdout": [o for _, o in pairs[:h_n]],
            "holdout_digests": [d for d, _ in pairs[:h_n]],
            "optimisation": [o for _, o in pairs[h_n:]]}


def seal(rows: List[Any], *, floor: int = ACTIVATION_FLOOR, store: Optional[str] = None) -> Dict[str, Any]:
    """The one-time DEC-007 activation event: refuse below the floor, else seal the 70/30 split.

    The returned manifest chains a POLICY step (floor, split percentages, counts — so the terms of
    the seal are themselves tamper-evident) followed by one step per holdout row carrying its
    content digest. ``sealed_at`` is informational provenance OUTSIDE the chain (not hash-covered;
    the chain is the seal — same stance as the run manifest's meta). Committing the returned
    manifest is the human's git action; this function writes nothing."""
    status = activation_status(rows, floor=floor)
    if not status["eligible"]:
        raise HoldoutActivationError(status["reason"])
    parts = split_real_rows(rows)
    if parts["real_n"] != status["real_n"]:   # one discriminator, two call sites — they must agree
        raise HoldoutIntegrityError(
            f"REAL-row count drifted between counter ({status['real_n']}) and splitter "
            f"({parts['real_n']}) — calibration.normalize_outcome changed under one of them")
    policy = {"kind": "policy", "policy": "DEC-007", "contract": CONTRACT_PATH,
              "activation_floor": floor, "holdout_pct": HOLDOUT_PCT,
              "real_n": parts["real_n"], "optimisation_n": len(parts["optimisation"]),
              "holdout_n": len(parts["holdout"])}
    steps = [policy] + [{"kind": "holdout_row", "row_sha256": d} for d in parts["holdout_digests"]]
    chain = hash_chain(steps)
    return {"tool": "cisco-holdout", "schema": "holdout_manifest/1", "contract": CONTRACT_PATH,
            "store": str(store or calibration.PIR_OUTCOMES_PATH).replace("\\", "/"),
            "sealed_at": _now_iso(),
            "chain": chain, "chain_root": chain[-1]["sha256"]}


def verify(man: Dict[str, Any], store_rows: Optional[List[Any]] = None) -> Dict[str, Any]:
    """Verify a holdout manifest: the chain reconciles to its sealed ``chain_root`` (edits,
    reorders and tail-truncation all break it — :func:`manifest.verify_chain` semantics), the
    sealed policy step is present and consistent with the row count, and — when the store's rows
    are supplied — every sealed digest still resolves to a present store row (with multiplicity, so
    deleting one of two identical holdout rows is still caught). An edit to an OPTIMISATION row is
    deliberately outside this seal: the manifest freezes the holdout, the append-only store +
    git history cover the rest."""
    man = man or {}
    chain = man.get("chain") or []
    ok, broken = verify_chain(chain, expected_root=man.get("chain_root"))
    problems: List[str] = []
    if not ok:
        problems.append(f"hash chain broken at rows {broken}")
    policy = None
    if chain and chain[0].get("kind") == "policy":
        policy = {k: v for k, v in chain[0].items() if k not in _RESERVED}
    if policy is None:
        ok = False
        problems.append("manifest carries no sealed policy step (step 0)")
    sealed = [r.get("row_sha256") for r in chain[1:] if r.get("kind") == "holdout_row"]
    if policy is not None and policy.get("holdout_n") != len(sealed):
        ok = False
        problems.append(f"sealed policy says holdout_n={policy.get('holdout_n')} but the chain "
                        f"carries {len(sealed)} holdout rows")
    missing: List[str] = []
    if store_rows is not None:
        have = Counter(d for d in (row_sha256(r) for r in store_rows) if d)
        want = Counter(sealed)
        missing = sorted(d for d, k in want.items() if have.get(d, 0) < k)
        if missing:
            ok = False
            problems.append(f"{len(missing)} sealed holdout row(s) missing from the store "
                            f"(deleted or content-edited)")
    reason = ("; ".join(problems) if problems else
              "holdout manifest verifies: chain intact"
              + (", every sealed row present in the store" if store_rows is not None
                 else " (store not checked)"))
    return {"ok": ok, "broken": broken, "missing": missing, "policy": policy,
            "sealed_rows": len(sealed), "reason": reason}


def read_holdout(who: str, purpose: Optional[str] = None, *,
                 manifest_path: str = MANIFEST_PATH, store_path: Optional[str] = None,
                 log_path: str = ACCESS_LOG_PATH) -> List[Dict[str, Any]]:
    """THE sanctioned holdout read path — the contract forbids every other one. Verifies the seal
    against the store, then returns the normalized holdout rows; **every access attempt against the
    data — success or integrity failure — appends who/when to the access log first** (an
    unattributed call is refused before anything is read, so there is nothing to log). The log line
    also records the OS user best-effort: like the scorecard's provenance pair, ``who`` is a
    declared identity, not proof — the residual is declared, not hidden."""
    who = str(who or "").strip()
    if not who:
        raise ValueError("holdout access requires an attributable identity (--who); "
                         "refusing an unattributed read")
    try:
        with open(manifest_path, encoding="utf-8") as f:
            man = json.load(f)
    except (OSError, ValueError) as e:
        raise HoldoutIntegrityError(
            f"no readable holdout manifest at {manifest_path} — either the DEC-007 split has not "
            f"activated yet (no seal exists) or the manifest is damaged: {e}") from e
    store = store_path or man.get("store") or calibration.PIR_OUTCOMES_PATH
    rows = calibration.read_outcomes(store)
    res = verify(man, store_rows=rows)
    selected: List[Dict[str, Any]] = []
    if res["ok"]:
        want = Counter(r.get("row_sha256") for r in (man.get("chain") or [])[1:]
                       if r.get("kind") == "holdout_row")
        for r in rows:
            d = row_sha256(r)
            if d and want.get(d, 0) > 0:
                want[d] -= 1
                selected.append(calibration.normalize_outcome(r))
    _append_access(log_path, who=who, purpose=purpose, ok=res["ok"], n_rows=len(selected),
                   manifest=str(manifest_path).replace("\\", "/"),
                   chain_root=man.get("chain_root"))
    if not res["ok"]:
        raise HoldoutIntegrityError(f"holdout integrity failure — {res['reason']} "
                                    f"(the access attempt was logged)")
    return selected


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _append_access(log_path: str, **fields: Any) -> Dict[str, Any]:
    """One append-only JSONL access-log line: ts + declared who + best-effort OS user + outcome."""
    entry: Dict[str, Any] = {"ts": _now_iso()}
    try:
        import getpass
        entry["os_user"] = getpass.getuser()
    except Exception:
        entry["os_user"] = None
    entry.update(fields)
    d = os.path.dirname(str(log_path))
    if d:
        os.makedirs(d, exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=True, sort_keys=True) + "\n")
    return entry


def read_access_log(path: str = ACCESS_LOG_PATH) -> List[Dict[str, Any]]:
    """Every well-formed access-log line, file order. Missing/empty -> [] (absence is absence);
    malformed lines skipped, not fatal (mirrors :func:`calibration.read_outcomes`)."""
    try:
        with open(path, encoding="utf-8") as f:
            out: List[Dict[str, Any]] = []
            for line in f:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except Exception:
                        pass
            return out
    except OSError:
        return []


# --- CLI -----------------------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    """``status`` (default) reports activation state; ``seal`` refuses below the floor and never
    overwrites an existing manifest (re-sealing is a human-gated event — move the old seal
    deliberately); ``verify`` checks chain + store; ``read`` is the logging accessor. Reads the
    store honoring ``PIR_OUTCOMES_FILE`` like the calibration CLI."""
    import argparse
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    parser = argparse.ArgumentParser(
        prog="python -m cisco_toolkit.holdout",
        description="DEC-007 sealed-holdout tooling (contract: %s)" % CONTRACT_PATH)
    sub = parser.add_subparsers(dest="cmd")
    for name in ("status", "seal", "verify", "read"):
        p = sub.add_parser(name)
        p.add_argument("--store", default=None, help="outcome store (default: manifest's / %s)"
                       % calibration.PIR_OUTCOMES_PATH)
        p.add_argument("--manifest", default=MANIFEST_PATH)
        if name == "seal":
            p.add_argument("--out", default=MANIFEST_PATH)
        if name == "read":
            p.add_argument("--who", required=True, help="attributable identity for the access log")
            p.add_argument("--purpose", default=None)
            p.add_argument("--log", default=ACCESS_LOG_PATH)
    args = parser.parse_args(argv)
    cmd = args.cmd or "status"
    store = getattr(args, "store", None) or os.environ.get("PIR_OUTCOMES_FILE")

    if cmd == "status":
        st = activation_status(calibration.read_outcomes(store or calibration.PIR_OUTCOMES_PATH))
        print(f"holdout (DEC-007) — {st['reason']}")
        print(f"  by_source: {st['by_source'] or '(store empty)'}")
        return 0

    if cmd == "seal":
        if os.path.exists(args.out):
            print(f"REFUSED: {args.out} already exists — re-sealing is a human-gated event; "
                  f"supersede the old manifest explicitly (see {CONTRACT_PATH}), never overwrite it.")
            return 2
        try:
            man = seal(calibration.read_outcomes(store or calibration.PIR_OUTCOMES_PATH), store=store)
        except HoldoutActivationError as e:
            print(f"REFUSED: {e}")
            return 2
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(json.dumps(man, ensure_ascii=True, indent=2) + "\n")
        pol = man["chain"][0]
        print(f"sealed: {pol['holdout_n']} holdout / {pol['optimisation_n']} optimisation of "
              f"{pol['real_n']} REAL rows -> {args.out} (chain_root {man['chain_root'][:16]}…). "
              f"Commit the manifest — the seal is only public once it is in git.")
        return 0

    if cmd == "verify":
        try:
            with open(args.manifest, encoding="utf-8") as f:
                man = json.load(f)
        except (OSError, ValueError) as e:
            print(f"INTEGRITY: cannot load manifest {args.manifest}: {e}")
            return 4
        rows = calibration.read_outcomes(store or man.get("store") or calibration.PIR_OUTCOMES_PATH)
        res = verify(man, store_rows=rows)
        print(("OK: " if res["ok"] else "INTEGRITY: ") + res["reason"])
        return 0 if res["ok"] else 4

    if cmd == "read":
        try:
            rows = read_holdout(args.who, args.purpose, manifest_path=args.manifest,
                                store_path=store, log_path=args.log)
        except ValueError as e:
            print(f"REFUSED: {e}")
            return 2
        except HoldoutIntegrityError as e:
            print(f"INTEGRITY: {e}")
            return 4
        for r in rows:
            print(json.dumps(r, ensure_ascii=True))
        sys.stderr.write(f"holdout read: {len(rows)} rows; access logged to {args.log}\n")
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
