# Intel feed — the egress research lane's drop-box (consumer side, no-egress)

Phase 5 "eyes" of [`docs/autonomous-brain-plan-v4-final-2026-07-06.md`](../autonomous-brain-plan-v4-final-2026-07-06.md).
The wired **egress-fenced research lane** sweeps approved PSIRT/advisory sources and drops **frozen,
Rule-3-sanitized, SHA-256 hash-sealed** feed files *here*. The air-gapped repo consumes them **read-only** via
[`cisco_toolkit/intel_feed.py`](../../cisco_toolkit/intel_feed.py) — no egress on this side. The hash is
unkeyed and the current envelope declares `authentication: none`: it is corruption-evident, not a digital
signature or proof of source identity.

## Feed file format — `feed-<date>.jsonl`

Line 1 is a **manifest**; every subsequent line is one advisory (JSON). Produce it with
`cisco_toolkit.intel_feed.build_feed(entries, sanitized=True, generated="YYYY-MM-DD")` so the producer and the
consumer serialize and verify the integrity envelope identically:

```
{"kind":"intel-feed-manifest","manifest_version":2,"integrity":"sha256","hash_scope":"entry-lines","authentication":"none","sha256":"<hash of the entry lines>","sanitized":true,"producer":"research-lane","generated":"2026-07-07","n":2}
{"id":"cisco-sa-...","title":"...","affected":["IOS XE","Catalyst 9300"],"severity":"High","source":"...","published":"2026-07-07","summary":"..."}
{"id":"cisco-sa-...","title":"...","affected":["NX-OS"],"severity":"Critical","source":"...","published":"2026-07-06","summary":"..."}
```

## The provenance gate (where no-egress is enforced on intake)

`intel_feed.verify_feed` **refuses** a feed unless **all** hold — a bad feed is refused *whole*, never
partially consumed:

1. the manifest attests **`sanitized: true`** (Rule-3 — no client identifiers);
2. the v2 manifest declares the supported `integrity: sha256`, `hash_scope: entry-lines`, and
   `authentication: none` contract (unsupported versioned contracts are refused);
3. the declared entry count equals the actual line count, every line is strict JSON, and every advisory has
   a unique non-empty string `id`;
4. the **SHA-256** of the entry lines matches the manifest (corruption evident, not source-authenticated);
5. no IPv4/IPv6 address, MAC address, Cisco chassis serial, or email address appears anywhere in the
   decoded manifest or entries (consumer-owned standard scan, independent of producer claims);
6. for engagement-aware intake, a usable client/site/device denylist was derived from the snapshot and no
   spelling of those identifiers appears despite the sanitized flag (defense-in-depth).

Then `match_fleet` intersects each advisory's `affected` with the fleet's platforms → PSIRT hits, and
`advisory_drift_items` projects a hit into a [`self_healing`](../../cisco_toolkit/self_healing.py) drift item
(routed to `config-security-auditor`) — so a PSIRT hit proposes a remediation exactly like a snapshot
regression (propose-only; never a device write). Coverage-honest: no feed present → "no intel feed (gated)",
never "no advisories affect the fleet".

```
python -m cisco_toolkit.intel_feed --dir docs/intel <snapshot.json>
```

The snapshot CLI derives its engagement denylist before opening the feed. The remediation and upgrade
consumers do the same from their roster/snapshots and refuse intake when no usable engagement identifier is
available. `load_feeds()` remains usable for generic, non-engagement inspection, but a caller that will
join feed data to an engagement must set `require_forbidden=True` and supply the derived tokens. Duplicate
advisory IDs across separate feed files are ambiguous, so every implicated file is refused whole. Intake
also refuses links/reparse points, special files, file-identity changes, invalid UTF-8, and per-file,
aggregate-byte, or file-count overages.

## Status

**Producer, consumer, and intake gate are built and tested** (`tests/test_research_lane.py`,
`tests/test_intel_feed.py`, `tests/test_research_http_guard.py`). The tracked
`feed-2026-07-07.jsonl` contains 93 verified CISA KEV entries under the current v2 envelope
(`integrity: sha256`, `hash_scope: entry-lines`, `authentication: none`). Verification establishes the
sanitization claim, structure/count, and entry-hash integrity — not producer authentication. Live HTTP is
explicit and guarded: public HTTPS only, validated/pinned DNS, no environment proxy, host-confined
redirects, chunked reads, and bounded response/byte/count/redirect/overall-deadline budgets. Absence is
still reported as absence.
