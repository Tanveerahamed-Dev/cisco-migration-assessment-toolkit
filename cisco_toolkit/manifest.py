"""Sealed, navigable run-manifest chain-of-custody (roadmap D2 + J4) — offline, deterministic.

The offline answer to NetClaw's GAIT immutable transcript: an append-only, hash-chained ledger of the
assessment pipeline's steps. Each row carries `prev_sha256` and a `sha256` over `(prev_sha256 + canonical
step payload)`, so editing any earlier row breaks every hash after it — tamper-evidence without a Git (or
any) dependency. Pure stdlib `hashlib`; no LLM, no network; determinism is the whole point (same inputs ->
same chain), which is why it is the engine's seal and not NetClaw's non-deterministic agent transcript.

SCOPE OF "append-only" — the property holds WITHIN one sealed manifest: rows are only ever appended to a
chain, and any edit to an earlier row invalidates every hash after it. It is NOT a claim that manifests
accumulate across runs. `COLLECT_PARSE_V3_23_0.build_run_manifest` seals one run's artifact set, and a
re-run to the same `--output` replaces that file along with the artifacts it hashes (a manifest outliving
its artifacts would seal files that no longer exist). Read a manifest as "this artifact set, sealed", not
as an engagement history; the append-across-runs ledger is `cisco_toolkit.gate_state`'s audit array.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional, Tuple

GENESIS = "0" * 64
_RESERVED = ("seq", "prev_sha256", "sha256")


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
    chain = hash_chain(steps or [])
    return {
        "tool": meta.get("tool", "cisco-assess"),
        "schema_version": meta.get("schema_version"),
        "generated_at": meta.get("generated_at"),
        "collected_at": meta.get("collected_at"),
        "devices_file_sha256": meta.get("devices_file_sha256"),
        "artifacts": [{"name": n, "sha256": s} for n, s in sorted((artifacts or {}).items())],
        "abstention_ledger": meta.get("abstention_ledger") or {},
        "chain": chain,
        "chain_root": chain[-1]["sha256"] if chain else GENESIS,
    }
