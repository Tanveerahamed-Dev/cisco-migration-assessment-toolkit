# `research_lane/` — the egress-fenced "eyes" (Phase 5, D2)

The one place external **egress is allowed**. It sweeps PSIRT/advisory sources, **Rule-3-sanitizes** the
result, **signs** it, and emits a frozen `docs/intel/feed-*.jsonl` that the air-gapped repo consumes
read-only via [`cisco_toolkit/intel_feed.py`](../cisco_toolkit/intel_feed.py). Only the frozen, sanitized,
signed artifact crosses in — so the repo stays byte-identical-reproducible when disconnected.

## Why it's outside `cisco_toolkit/`

The no-egress attestation (`cisco_toolkit/attestation.py`) and `tests/test_readonly_and_no_egress.py` scan
**only** `cisco_toolkit/`. This package is deliberately *outside* that scope, so its egress code (the
`urllib` fetch in `producer.http_source`) can exist without breaking the air-gapped guarantee. The
dependency is one-way: `research_lane` imports `cisco_toolkit` (to reuse the feed signing contract), **never
the reverse** — nothing here can pull an egress import into the attested package. Full suite stays green with
the attestation at `0 network + 0 LLM imports`.

## Running it (from a network-connected worktree/host — not an air-gapped repo session)

```bash
# Offline (default, no network): turn a local advisories JSON into a signed, sanitized feed.
python -m research_lane.producer --fixture advisories.json --generated 2026-07-07 --forbidden Acme,SiteA

# Live egress (explicit opt-in — needs BOTH --live AND --url; a stray --live fetches nothing):
python -m research_lane.producer --live --url https://<advisory-json-endpoint> --generated 2026-07-07 --forbidden Acme
```

The pipeline is `fetch → sanitize (Rule-3) → sign (build_feed) → write docs/intel/feed-<date>.jsonl`. Only
the fetch touches the network, and only in the live path; everything after it is deterministic and offline
(so it is unit-tested in [`tests/test_research_lane.py`](../tests/test_research_lane.py) without a network,
including a producer→consumer roundtrip proving the signing contract holds and client identity is scrubbed).

## Discipline

- **Egress is opt-in and isolated.** Default is a fixture. Live needs `--live --url` (mirrors the nightly
  wrapper's dry-run/live split). This session authored the lane; it does **not** perform live sweeps
  unprompted.
- **Rule-3 first.** `research_lane/sanitize.py` scrubs forbidden tokens + IPs + emails and records the
  proof; a feed is signed `sanitized: true` only because the scrub actually ran. The consumer re-verifies
  (sanitized attestation + SHA-256 + its own forbidden scan) before use.
- **The producer is the only writer of `docs/intel/`.** The air-gapped repo never fetches; it reads.
