# Changelog

Release-level highlights. The complete, engineering-grade change history (one dated row
per change, with verification evidence) lives in
[`COLLECT_PARSE_V3_23_0.md → Change Log`](COLLECT_PARSE_V3_23_0.md#change-log).

## [Unreleased]

### Fixed
- **`build_cloud` coverage-honesty on a parser crash**: the v3.25.0 typed-parser-defaults change made
  `_safe_parse` return a list parser's registered empty shape (`[]`) on a raise — which slips past
  `build_cloud`'s `isinstance(sgs, list)` guard and reports `{security_groups: []}` ("cloud observed,
  nothing world-open" = false-health) instead of not-observed `{}`. `build_cloud` now pins `_default={}`
  (a non-list crash sentinel the guard converts back to not-observed), while a genuine clean `[]` on the
  happy path is preserved. Latent today (`parse_aws_security_groups` never raises) → **golden byte-
  unchanged**. The `build.py` call-site anti-drift test learns the one intentional off-registry sentinel
  (a `shape-sentinel` marker + a pin-test scoping the exemption to exactly that site), and a pre-existing
  crash test whose `lambda` mock masked the real list-shape fallback (so it passed regardless) is made
  faithful. Found by adversarial review of the v3.25.0 wave.
- **`coverage_matrix` false-health — a not-collected device no longer vanishes** (PR #279): the matrix joined
  the (device × axis) grid on `snap['devices']`, which is built only from hosts that COLLECTED — so a device
  the collection never reached (unreachable / auth-fail) emitted zero rows and read as fully covered (on the
  [HISTORY-REDACTED] fleet, all 50 of 303/253 not-collected devices would disappear). The join is now the inventory UNION
  (`snap['devices'] ∪ collection_completeness`), and a never-reached host abstains `not_collected` on every
  base axis (its capture/parse "covered-by-silence" inference is invalid).
- **`coverage_matrix` inventory join hardened** (PR #282): an architecture-coverage row is emitted only for a
  host that IS an inventory device; an observed class contributing no inventory device collapses to one
  `(fleet)` covered row — guarding a malformed/bare struct-keyed controller axis (`{faults:.., nodes:..}`)
  from leaking fake `device='faults'` rows into `by_device` and the covered count.
- **`coverage_matrix` correctness**: the synthetic `(fleet)` row no longer pollutes `by_device` (it is
  not a device); `summary.n_axes` counts the coverage *dimensions* (collection/capture/parse/architecture),
  not each architecture key (was ~32 on a real fleet); a parse-axis event keyed by the FS-sanitized
  collection-dir basename is mapped back to the raw inventory host, so a hostname with an FS-reserved char
  no longer silently reads "covered"; and `set(devices)` is hoisted out of the per-event loop.
- **`Verdict` string-safety**: `__str__`/`__format__` pinned to `str`'s, so `str()`/f-string/`%s` yield the
  bare value (`"proven"`) not `"Verdict.PROVEN"` — safe for any future surface that interpolates a raw member.
- **`gen_oui_registry`**: a bare-filename `--out` no longer crashes on `os.makedirs('')`, and a leading
  space no longer defeats the no-egress URL refusal.
- **Test hardening**: two coverage guards that silently asserted nothing on the shipped fixtures are now
  synthetic and always-run — the `_carry` `''`-cache sentinel and the collection false-health guard.

## [v3.25.0] — 2026-07-03 — Plan-A remainder wave (8 items) + project SSOT registry

The tail of the Plan-A backlog (Tier-2/3 remainder + the greenfield north-star's additive first
steps), plus a project-wide single-source-of-truth registry.

### Correctness & types
- **Typed parser defaults**: `_safe_parse` returns each parser's OWN empty shape via a frozen
  `PARSER_RETURN_SHAPE` (55 dict / 47 list / 2 str / 1 int) — closing the `{}`-vs-`[]` hazard at its
  root; a totality + `build.py` call-site anti-drift test keeps it from ever drifting.
- **`Verdict` ADT** (`Proven | Refuted | NotObserved | Indeterminate`, a str-mixin enum in `model.py`)
  makes abstention a TYPE, not a per-module string convention; threaded additively into the ACL
  shadow-proof findings (the other verify surfaces migrate behind it next).
- **ntc-templates CI referee** widened from 3 IOS commands to 7 across IOS **and** NX-OS
  (superset-only; a TextFSM error on an off-shape fixture → skip, never a false fail).

### Coverage & footprint
- **Coverage-as-a-first-class row**: `snap['coverage_matrix']` composes the four coverage sources
  (collection / capture / parse / architecture) into one per-(device, axis) table — coverage-honest
  (abstention explicit, never a fabricated "covered").
- The on-disk snapshot's `interfaces` subtree is **sparse-encoded** (~70% of its fields are empty
  defaults), losslessly restored via `InterfaceData.from_sparse` on read; the workbook and every
  consumer are unaffected (the in-memory snapshot stays dense).

### Performance & structure
- The shared `_link_carries` primitive on the failure-impact / causality hot path is **memoized
  per-model** (`_carry`) — a provably output-neutral drop from O(H·V·L) to O(V·L).
- **Typed `AnalysisContext`** (`cisco_toolkit/context.py`) is introduced as the strangler seam for
  the 1300-line `main()`; the leaf finalize stage is extracted onto it (`_stage_finalize`),
  golden-neutral. The remaining stages migrate move by move.
- **Rig/KB hygiene**: an offline `gen_oui_registry.py` (parses a local Wireshark `manuf`; refuses a
  URL — no-egress), an `eoldb` provenance/review-vintage guard, and `.claude/worktrees/` excluded
  from graphify.

### Governance
- **Project SSOT registry** at `docs/ssot.md` — "one index, many owners": the single map of where
  the authoritative truth for every fact lives (reference, never restate), with a
  `test_ssot_registry.py` integrity gate that fails if a pointer rots, folded into graphify, and
  referenced from `CLAUDE.md`.

## [v3.24.0] — 2026-07-02 — Plan A (EVOLVE) Move-0 + Tier-1 + Tier-2 + Tier-3

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
