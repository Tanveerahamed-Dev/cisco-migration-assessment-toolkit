# `research_lane/` — the egress-fenced "eyes" (Phase 5, D2)

The one place external **egress is allowed**. It sweeps PSIRT/advisory sources, **Rule-3-sanitizes** the
result, **SHA-256 hash-seals** it, and emits a frozen `docs/intel/feed-*.jsonl` that the air-gapped repo consumes
read-only via [`cisco_toolkit/intel_feed.py`](../cisco_toolkit/intel_feed.py). Only the frozen, sanitized,
hash-sealed artifact crosses in — so the repo stays byte-identical-reproducible when disconnected. The
unkeyed digest is corruption-evident but deliberately declares `authentication: none`: it is not a digital
signature and does not establish who produced the feed.

## Why it's outside `cisco_toolkit/`

The no-egress attestation (`cisco_toolkit/attestation.py`) and `tests/test_readonly_and_no_egress.py` scan
**only** `cisco_toolkit/`. This package is deliberately *outside* that scope, so its egress code (the
`urllib` fetch in `producer.http_source`) can exist without breaking the air-gapped guarantee. The
dependency is one-way: `research_lane` imports `cisco_toolkit` (to reuse the feed integrity contract), **never
the reverse** — nothing here can pull an egress import into the attested package. Full suite stays green with
the attestation at `0 network + 0 LLM imports`.

## Running it (from a network-connected worktree/host — not an air-gapped repo session)

```bash
# Offline (default, no network): turn a local advisories JSON into a hash-sealed, sanitized feed.
python -m research_lane.producer --fixture advisories.json --generated 2026-07-07 --forbidden Acme,SiteA

# Live egress (explicit opt-in — needs BOTH --live AND --url; a stray --live fetches nothing):
python -m research_lane.producer --live --url https://<advisory-json-endpoint> --generated 2026-07-07 --forbidden Acme
```

The pipeline is `fetch → sanitize (Rule-3) → hash-seal (build_feed) → write docs/intel/feed-<date>.jsonl`. Only
the fetch touches the network, and only in the live path; everything after it is deterministic and offline
(so it is unit-tested in [`tests/test_research_lane.py`](../tests/test_research_lane.py) without a network,
including a producer→consumer roundtrip proving the integrity contract holds and client identity is scrubbed).

The producer is wired and `docs/intel/feed-2026-07-07.jsonl` is a tracked 93-entry CISA KEV feed. Its
v2 envelope declares `integrity: sha256`, `hash_scope: entry-lines`, and `authentication: none`, and passes
the strict entry-count, JSON, hash, and sanitization checks. No live sweep runs automatically.

## Discipline

- **Egress is opt-in and isolated.** Default is a fixture. Live needs `--live --url` (mirrors the nightly
  wrapper's dry-run/live split). This session authored the lane; it does **not** perform live sweeps
  unprompted.
- **HTTP intake is guarded.** Live sources require credential-free public HTTPS, validate every DNS answer,
  pin the connection to a validated address, disable environment proxies, restrict redirects to allowed
  hosts, and enforce per-response, aggregate-byte, response-count, redirect, and wall-clock limits. Cisco
  OAuth/API adapters additionally pin their endpoint hostnames.
- **Rule-3 first.** `research_lane/sanitize.py` scrubs client-resolving identifiers and records the
  literals it removed as audit detail; this includes IPv4/IPv6 addresses, MAC addresses, Cisco chassis
  serials, email addresses, and configured client/site/device tokens (including identifier spellings).
  A feed records `sanitized: true` only after the scrub runs. That flag is a claim, not authentication.
  The consumer independently checks the claim, strict envelope/entry structure, entry count, SHA-256,
  every decoded key/value for the standard identifier classes, and an engagement-specific denylist before
  fleet-aware use. The snapshot-aware CLI and remediation/upgrade consumers derive that denylist from the
  engagement inputs; callers without such inputs must pass an explicit denylist rather than treating an
  empty list as proof of privacy.
- **The producer is the only writer of `docs/intel/`.** The air-gapped repo never fetches; it reads.
