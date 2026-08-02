"""Optional localhost-Ollama semantic re-rank for the vault digest (D4, ADR-0001 Amendment 1).

Lives at the repo ROOT — deliberately **outside** ``cisco_toolkit/`` — so its ``urllib``/Ollama use never
trips the no-egress attestation, which forbids network libraries anywhere in ``cisco_toolkit/`` at any
nesting depth. :func:`cisco_toolkit.recall.ollama_digest_rank` invokes this as a **subprocess**, exactly like
:func:`cisco_toolkit.recall.graph_rank` shells out to graphify. Zero external egress: it talks only to a
**local** Ollama on 127.0.0.1:11434 (an on-host service, not the network) — so the air-gapped repo's
reproducibility is unchanged.

GRACEFUL DEGRADATION (D4 — optional dependency, ADR 0001 Amendment 1): if Ollama is not installed / not listening, this
prints **nothing** and exits 0, so recall falls back to the lexical vault signal (and graph+docs). It never
hangs (it fast-fails on a closed port) and never raises out.

Usage (called by recall, not by hand): ``python ollama_recall.py "<query>" <digest_dir>``
"""
from __future__ import annotations

import glob
import json
import math
import os
import socket
import sys
from typing import Any, Dict, List

from cisco_toolkit.attestation import loopback_only as _loopback_only

#: Validated at import: the local-inference carve-out is only a carve-out while the endpoint is
#: genuinely on-host. See cisco_toolkit.attestation.loopback_only.
OLLAMA_HOST = _loopback_only(os.environ.get("OLLAMA_HOST", "127.0.0.1:11434"))
OLLAMA_EMBED_MODEL = os.environ.get("OLLAMA_EMBED_MODEL", "nomic-embed-text")


def _no_redirect_opener():
    """A urllib opener that REFUSES redirects — the second half of the loopback pin.

    ``loopback_only`` pins the FIRST hop only; ``urlopen`` then follows a 301/302/303, so a process
    answering on 127.0.0.1:11434 that is not Ollama could bounce this call to a remote host and have
    its body accepted as the embedding. Measured with a faked transport before this existed: the
    second hop opened ``ollama.corp.example``. See :mod:`ollama_judge` for the full note."""
    import urllib.error
    import urllib.request

    class _Refuse(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            raise urllib.error.URLError(
                f"refusing an HTTP {code} redirect from the local Ollama endpoint to {newurl!r}: "
                f"following it would leave loopback (no-egress doctrine; ADR-0001 Amendment 1 "
                f"covers ON-HOST compute only).")

    return urllib.request.build_opener(_Refuse)


def _listening(hostport: str, *, timeout: float = 0.4) -> bool:
    """Fast TCP probe — is a local Ollama actually up? Lets us degrade in <0.5s when it isn't."""
    try:
        host, _, port = hostport.partition(":")
        with socket.create_connection((host or "127.0.0.1", int(port or "11434")), timeout=timeout):
            return True
    except Exception:
        return False


def cosine(a: List[float], b: List[float]) -> float:
    """Pure cosine similarity (unit-tested). Mismatched/empty vectors -> 0.0 (never a fabricated score)."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _embed(text: str, *, timeout: int = 8) -> List[float]:
    """One embedding via the LOCAL Ollama API. ``urllib`` is imported lazily and this file is outside the
    ``cisco_toolkit/`` fence, so the engine's no-egress import graph is untouched."""
    import urllib.request                                    # localhost only; outside the cisco_toolkit fence
    req = urllib.request.Request(
        f"http://{OLLAMA_HOST}/api/embeddings",
        data=json.dumps({"model": OLLAMA_EMBED_MODEL, "prompt": text}).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with _no_redirect_opener().open(req, timeout=timeout) as r:  # noqa: S310 (localhost, opt-in)
        return json.load(r).get("embedding") or []


def rank(query: str, entries: List[Dict[str, Any]]) -> List[str]:
    """Rank entry ids best-first by cosine of their embedding to the query's. ``entries`` = ``[{id, text}]``."""
    qv = _embed(query)
    scored = []
    for e in entries:
        s = cosine(qv, _embed(str(e.get("text", ""))))
        if s > 0:
            scored.append((str(e.get("id")), s))
    scored.sort(key=lambda kv: (-kv[1], kv[0]))
    return [i for i, _ in scored]


def _load_verified(digest_dir: str) -> List[Dict[str, Any]]:
    """Load + provenance-verify the signed digest(s) into ``[{id, text}]`` (reuses the shared gate)."""
    try:
        from cisco_toolkit.intel_feed import verify_feed
    except Exception:
        return []
    out: List[Dict[str, Any]] = []
    for p in sorted(glob.glob(os.path.join(digest_dir, "digest-*.jsonl"))):
        try:
            res = verify_feed(open(p, encoding="utf-8").read())
        except Exception:
            continue
        if res.get("ok"):
            for e in res["entries"]:
                txt = " ".join(str(e.get(f, "")) for f in ("title", "detail", "notes", "tags"))
                out.append({"id": str(e.get("id")), "text": txt})
    return out


def main(argv: List[str]) -> int:
    if len(argv) < 2:
        return 0
    query, digest_dir = argv[0], argv[1]
    if not _listening(OLLAMA_HOST):          # Ollama not running -> degrade silently + fast
        return 0
    entries = _load_verified(digest_dir)
    if not entries:
        return 0
    try:
        for eid in rank(query, entries):
            print(eid)
    except Exception:
        return 0                              # any Ollama error -> print nothing -> recall uses the lexical signal
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
