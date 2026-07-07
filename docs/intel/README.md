# Intel feed — the egress research lane's drop-box (consumer side, no-egress)

Phase 5 "eyes" of [`docs/autonomous-brain-plan-v4-final-2026-07-06.md`](../autonomous-brain-plan-v4-final-2026-07-06.md).
An **egress-fenced research lane** (a separate worktree — **not wired yet; gated on explicit authorization**)
would sweep PSIRT/advisory sources and drop **frozen, Rule-3-sanitized, signed** feed files *here*. The
air-gapped repo consumes them **read-only** via [`cisco_toolkit/intel_feed.py`](../../cisco_toolkit/intel_feed.py) —
no egress on this side. This directory defines the **contract the producer must meet**.

## Feed file format — `feed-<date>.jsonl`

Line 1 is a **manifest**; every subsequent line is one advisory (JSON). Produce it with
`cisco_toolkit.intel_feed.build_feed(entries, sanitized=True, generated="YYYY-MM-DD")` so the producer and the
consumer sign/verify identically:

```
{"kind":"intel-feed-manifest","sha256":"<hash of the entry lines>","sanitized":true,"producer":"research-lane","generated":"2026-07-07","n":2}
{"id":"cisco-sa-...","title":"...","affected":["IOS XE","Catalyst 9300"],"severity":"High","source":"...","published":"2026-07-07","summary":"..."}
{"id":"cisco-sa-...","title":"...","affected":["NX-OS"],"severity":"Critical","source":"...","published":"2026-07-06","summary":"..."}
```

## The provenance gate (where no-egress is enforced on intake)

`intel_feed.verify_feed` **refuses** a feed unless **all** hold — a bad feed is refused *whole*, never
partially consumed:

1. the manifest attests **`sanitized: true`** (Rule-3 — no client identifiers);
2. the **SHA-256** of the entry lines matches the manifest (tamper / corruption evident);
3. no configured **forbidden identifier** appears despite the sanitized flag (defense-in-depth).

Then `match_fleet` intersects each advisory's `affected` with the fleet's platforms → PSIRT hits, and
`advisory_drift_items` projects a hit into a [`self_healing`](../../cisco_toolkit/self_healing.py) drift item
(routed to `config-security-auditor`) — so a PSIRT hit proposes a remediation exactly like a snapshot
regression (propose-only; never a device write). Coverage-honest: no feed present → "no intel feed (gated)",
never "no advisories affect the fleet".

```
python -m cisco_toolkit.intel_feed --dir docs/intel <snapshot.json>
```

## Status

**Consumer + provenance gate: built and tested** (`tests/test_intel_feed.py`). **Producer (the egress
research lane): NOT wired** — it breaks the no-egress doctrine (fenced) and is gated on explicit
authorization, along with the ADR-0001 vault-digest amendment and the Ollama dependency (D2/D3/D4). No real
feed files live here yet; absence is reported as absence.
