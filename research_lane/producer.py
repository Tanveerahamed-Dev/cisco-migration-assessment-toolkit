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
from typing import Any, Dict, List, Optional, Tuple

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
        forbidden: Tuple[str, ...] = (), generated: str = "", redact_ips: bool = True,
        allow_empty: bool = False) -> Tuple[str, List[str]]:
    """Produce a feed from already-fetched advisories and write it under ``out_dir``. Returns ``(path,
    redactions)``. The fetch is the caller's choice (fixture vs live), keeping this write step egress-free.

    **An EMPTY feed is refused by default** (2026-07-28): a signed, ``sanitized: true`` feed carrying zero
    advisories is indistinguishable, to the air-gapped consumer, from a fetch that verified there was
    nothing to report — so a source that silently failed publishes a valid-and-current attestation over no
    data at all. The source layer now raises on unreachability (``sources.SourceUnavailable``); this is the
    second, publish-side gate. Pass ``allow_empty=True`` to record a genuinely-empty sweep deliberately."""
    if not raw_advisories and not allow_empty:
        raise ValueError(
            "refusing to publish a SIGNED feed with zero advisories: to the consumer that is a positive "
            "attestation that the source was read and had nothing, which a failed fetch cannot claim. "
            "Fix/retry the source, or pass allow_empty=True (CLI: --allow-empty) if the sweep really was "
            "empty.")
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
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # cp1252 console -> never garble a dash
    except Exception:
        pass

    def _opt(name: str, default: str = "") -> str:
        return argv[argv.index(name) + 1] if name in argv and argv.index(name) + 1 < len(argv) else default

    out_dir = _opt("--out", os.path.join("docs", "intel"))
    generated = _opt("--generated", "")
    # .strip() per token: `--forbidden Acme, SiteA` is how a list gets typed, and an unstripped
    # " SiteA" demanded a literal leading space and matched nothing. sanitize._token_pattern strips
    # too; doing it here as well keeps the tuple the operator can see equal to the one that runs.
    forbidden = tuple(t for t in (s.strip() for s in _opt("--forbidden", "").split(",")) if t)
    allow_empty = "--allow-empty" in argv
    fetch_stats: Dict[str, Any] = {}

    source = _opt("--source")
    if source == "cisa-kev":
        from research_lane.sources import cisa_kev_source                # LIVE egress (fenced adapter)
        lim = _opt("--limit")
        print(f"[research-lane] LIVE egress: CISA KEV (Cisco{f', last {lim}' if lim else ''})")
        raw = cisa_kev_source(limit=int(lim) if lim else None)
    elif source == "cisco-psirt":
        # LIVE egress, CREDENTIAL-gated: the authoritative fixed-version source (openVuln). Fetches the
        # fixed releases for the CVEs already in the feed (or --cve-file). No creds -> no egress.
        from research_lane.sources import cisco_psirt_source
        cid, csec = os.environ.get("CISCO_OPENVULN_CLIENT_ID"), os.environ.get("CISCO_OPENVULN_CLIENT_SECRET")
        if not (cid and csec):
            print("[research-lane] --source cisco-psirt needs CISCO_OPENVULN_CLIENT_ID + "
                  "CISCO_OPENVULN_CLIENT_SECRET (openVuln API creds, https://apiconsole.cisco.com/) — "
                  "no creds, no egress.")
            return 2
        cve_file = _opt("--cve-file")
        if cve_file:
            cves = [ln.strip() for ln in open(cve_file, encoding="utf-8") if ln.strip()]
        else:                                               # default: the CVEs already in the consumed feed
            from cisco_toolkit.intel_feed import load_feeds
            cves = sorted({a["id"] for a in load_feeds().get("advisories", []) if a.get("id")})
        print(f"[research-lane] LIVE egress: Cisco PSIRT openVuln — fixed versions for {len(cves)} CVE(s)")
        from research_lane.sources import SourceUnavailable
        try:
            raw = cisco_psirt_source(cves, client_id=cid, client_secret=csec, stats=fetch_stats)
        except SourceUnavailable as ex:                     # reached-and-empty != could-not-reach
            print(f"[research-lane] REFUSED — {ex}")
            print(f"[research-lane] nothing was written (fetch stats: {fetch_stats})")
            return 3
    elif "--live" in argv:
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
                  "[--forbidden A,B] [--out docs/intel] [--allow-empty]   |   --source cisa-kev "
                  "[--limit N]   |   --source cisco-psirt [--cve-file F]   |   --live --url <url>")
            return 2
        raw = fixture_source(fx)

    try:
        path, redactions = run(raw, out_dir=out_dir, forbidden=forbidden, generated=generated,
                               allow_empty=allow_empty)
    except ValueError as ex:                                # the empty-feed publish gate
        print(f"[research-lane] REFUSED — {ex}")
        return 3
    skipped = (f"; {fetch_stats['no_advisory']} CVE(s) had no Cisco advisory"
               if fetch_stats.get("no_advisory") else "")
    print(f"[research-lane] wrote {path} ({len(raw)} advisory(ies); {len(redactions)} redaction(s) "
          f"applied{skipped})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
