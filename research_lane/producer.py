"""Research-lane producer (egress-fenced, D2) — fetch → Rule-3-sanitize → sign → emit the intel feed.

The pipeline is source-agnostic: a *source* is any callable returning a list of raw advisory dicts. Two are
provided — :func:`fixture_source` (offline, no network) and :func:`http_source` (LIVE egress, isolated).
Everything after the fetch (sanitize → sign → write) is deterministic and offline, so the whole thing is
tested without a network. The signed feed uses :func:`cisco_toolkit.intel_feed.build_feed`, so the repo's
consumer verifies exactly what this produces.

**Egress discipline (mirrors the nightly wrapper):** the default CLI path is a fixture; live egress needs
``--live`` **and** an explicit ``--url`` — a stray ``--live`` alone fetches nothing. Run this from a
network-connected worktree/host; the air-gapped repo only ever reads the emitted feed.
"""
from __future__ import annotations

import json
import os
from typing import Any, Callable, Dict, List, Optional, Tuple

from research_lane.sanitize import sanitize_advisories


def fixture_source(path: str) -> List[Dict[str, Any]]:
    """Offline source: read raw advisories from a local JSON file (a list of advisory dicts). No network."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else [data]


def http_source(urls: List[str], *, timeout: int = 15) -> List[Dict[str, Any]]:
    """LIVE EGRESS source — fetches JSON advisories over the network (stdlib ``urllib``). Isolated here in
    the fenced lane and never called unless the CLI is run with ``--live --url``. Each URL must return a
    JSON list (or object) of advisories."""
    import urllib.request                                   # lazy: keep the egress import inside the fenced call
    out: List[Dict[str, Any]] = []
    for u in urls:
        with urllib.request.urlopen(u, timeout=timeout) as resp:   # noqa: S310 (fenced, opt-in egress)
            data = json.loads(resp.read().decode("utf-8"))
        out += data if isinstance(data, list) else [data]
    return out


def produce_feed(raw_advisories: List[Dict[str, Any]], *, forbidden: Tuple[str, ...] = (),
                 generated: str = "", redact_ips: bool = True) -> Tuple[str, List[str]]:
    """Sanitize then sign. Returns ``(feed_text, redactions)``. ``sanitized: true`` is attested only because
    the scrub actually ran here (the redactions are the proof)."""
    clean, redactions = sanitize_advisories(raw_advisories, forbidden=forbidden, redact_ips=redact_ips)
    from cisco_toolkit.intel_feed import build_feed          # the one signing contract, shared with the consumer
    feed = build_feed(clean, sanitized=True, producer="research-lane", generated=generated)
    return feed, redactions


def run(raw_advisories: List[Dict[str, Any]], out_dir: str = os.path.join("docs", "intel"), *,
        forbidden: Tuple[str, ...] = (), generated: str = "", redact_ips: bool = True) -> Tuple[str, List[str]]:
    """Produce a feed from already-fetched advisories and write it under ``out_dir``. Returns ``(path,
    redactions)``. The fetch is the caller's choice (fixture vs live), keeping this write step egress-free."""
    feed, redactions = produce_feed(raw_advisories, forbidden=forbidden, generated=generated,
                                    redact_ips=redact_ips)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"feed-{generated or 'latest'}.jsonl")
    with open(path, "w", encoding="utf-8") as f:
        f.write(feed)
    return path, redactions


def main(argv: Optional[List[str]] = None) -> int:
    """CLI. Offline (default): ``python -m research_lane.producer --fixture <advisories.json> --generated
    2026-07-07 [--forbidden Acme,SiteA]``. Live egress (explicit): ``... --live --url <json-url> ...`` —
    fetches over the network. Writes ``docs/intel/feed-<date>.jsonl`` the repo consumes."""
    import sys
    argv = list(sys.argv[1:] if argv is None else argv)

    def _opt(name: str, default: str = "") -> str:
        return argv[argv.index(name) + 1] if name in argv and argv.index(name) + 1 < len(argv) else default

    out_dir = _opt("--out", os.path.join("docs", "intel"))
    generated = _opt("--generated", "")
    forbidden = tuple(t for t in _opt("--forbidden", "").split(",") if t)

    if "--live" in argv:
        url = _opt("--url")
        if not url:
            print("[research-lane] --live requires --url <json-advisory-endpoint> — refusing to fetch nothing.")
            return 2
        print(f"[research-lane] LIVE egress fetch: {url}")
        raw = http_source([url])
    else:
        fx = _opt("--fixture")
        if not fx:
            print("usage: python -m research_lane.producer --fixture <advisories.json> [--generated DATE] "
                  "[--forbidden A,B] [--out docs/intel]   |   ... --live --url <url>")
            return 2
        raw = fixture_source(fx)

    path, redactions = run(raw, out_dir=out_dir, forbidden=forbidden, generated=generated)
    print(f"[research-lane] wrote {path} ({len(raw)} advisory(ies); {len(redactions)} redaction(s) applied)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
