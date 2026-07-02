# Changelog

Release-level highlights. The complete, engineering-grade change history (one dated row
per change, with verification evidence) lives in
[`COLLECT_PARSE_V3_23_0.md → Change Log`](COLLECT_PARSE_V3_23_0.md#change-log).

## [Unreleased] — Plan A (EVOLVE) Move-0 + Tier-1 + Tier-2 + Tier-3

Hardening + instrumentation tranche executed in the load-bearing order of
`IMPROVEMENT_AND_GREENFIELD_PLANS.md`.

### Test-oracle & gate integrity (Move-0)
- The golden harness can no longer silently re-baseline: a missing golden FAILS, and
  `UPDATE_GOLDEN=1` rejects contract shrinkage vs git HEAD without `ALLOW_GOLDEN_SHRINK=1`.
- `webapp/tests` joined the default pytest gate; the entry module joined coverage
  (`source_pkgs`); CI coverage floor raised 80 → 85.

### Correctness instrumentation (Tier-1/2)
- `snap['parse_yield']`: zero-parse yield telemetry at the `cmdio` chokepoint —
  "collected-but-unparsed" is now a visible ledger row, never silently "feature absent";
  surfaced in the workbook, the explorer and AssessHub.
- Capture integrity widened from run-config-only to every collected capture, streaming;
  new `unverified_prompt` class for prompt-unconfirmed (timing-fallback) captures.
- Executed JS↔Python parity gate: the explorer's embedded FIB port runs under node
  against a 119-pair corpus and must match `fib.trace_fib_path` exactly.

### Confidentiality (Tier-1)
- AssessHub: CORS wildcard removed (localhost-origin regex), loopback-or-`ASSESSHUB_TOKEN`
  guard on all `/api`, explorer iframe sandboxed without `allow-same-origin`.
- Raw collection dir: unconditional `[SENSITIVE]` warning + opt-in `--redact-collection`
  in-place secret scrub; `password_env`/`$CISCO_PASS` is the documented credential default
  (`devices.example.json`).

### Structure (Tier-2)
- `_PER_DEVICE_AXES` registry: all 40 per-device evidence axes are one entry each
  (golden-byte-stable refactor — proven with no golden regeneration).
- Explorer `MODES` registry: one table drives mode wiring; the five historically
  shortcut-less modes gained keyboard shortcuts (x/w/p/v/d).
- Product surface: README describes the actual product (13 explorer modes, multi-vendor,
  proof engines); `LICENSE` and this `CHANGELOG.md` added; sample fleet regenerated with
  the full current snapshot schema.

### Confidentiality (Tier-1) — hardened further
- Explorer CSP pinned against silent regression: a test asserts the direct-open template
  and the snapshot-embedded HTML both keep `default-src` / `connect-src` / `object-src` /
  `base-uri` at `'none'` with no external origin ever allowed (Plan-A #9).
- Adversarial redaction leak corpus: 20 seeded-sentinel secret shapes across
  IOS / NX-OS / FortiGate / Junos — which caught and fixed a real miss, the
  `snmp-server host … version 1|2c <community>` trap community that survived the scrub
  (Plan-A #13).

### Performance (Tier-2)
- `compute_failure_impact` / topology: the VLAN-range parse is memoized — the one measured
  superlinear term (the same trunk-allowed / STP lists were re-split per VLAN per link).
  Membership-only and cached; a 23-case differential contract plus a cache-hit proof keep
  every output byte-identical (Plan-A #12).

### Structure (Tier-2) — webapp half of the axis pin
- A conformance test ties the webapp's `_ALLOWED_SECTIONS` (the section endpoint's
  allowlist) to what the engine actually emits and to the live `_PER_DEVICE_AXES` keys, so
  a renamed / removed section can no longer leave a dead 404 tab — the "months-dead NOS
  quartet" bug class (Plan-A #8 remainder).

### Contracts & interfaces (Tier-3)
- `cmdio.PARSER_CONTRACTS`: an as-built command → parser contract for the SSH `show`
  channel, reconciled against `build.py`'s own source by a totality test (every named
  parser exists; no phantom command; every inline dispatch is registered) — the recurring
  parser ↔ command drift class now fails the suite. Writing it immediately caught one
  unregistered dispatch (`show policy-map interface control-plane` → `parse_copp_drops`)
  (Plan-A #16).
- Snapshot JSON is written compact (tight separators, no indent) — a size win with
  round-trip and golden-neutral guarantees (Plan-A #14).
- Optional read-only MCP server (`cisco_toolkit.mcp_server`; `cisco-mcp-server` entry
  point; `[mcp]` extra): seven query tools over a produced snapshot — overview, inventory,
  device dossier, findings, failure impact, chokepoints, architecture coverage. Offline,
  no egress, import-guarded so the base package never depends on `mcp` (Plan-A #18).

## [v3.23.176] — 2026-06-11

Last tagged release before the Plan A tranche: the multi-vendor + controller-REST
assessment engine (Cisco IOS/IOS-XE/NX-OS + ACI/SD-WAN/ISE/FMC via REST, Arista,
Juniper SRX, FortiGate, AWS security groups), 12-document deliverable family,
Device Risk Register, AssessHub web platform, and the offline explorer.
See `COLLECT_PARSE_V3_23_0.md` for the full history.
