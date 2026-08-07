# Offline Data-Pack Provenance Audit — 2026-07-30 (historical; reconciled 2026-08-07)

> **Status: CLOSED / SUPERSEDED.** This file preserves the point-in-time findings
> from 2026-07-30. Its original present-tense findings and open release checklist
> are not the current work queue. Current authority lives in
> `reference-data/official-sources/manifest.json`,
> `cisco_toolkit/data/registry_manifest.json`, the generator/verifier modules,
> their regression tests, and `RELEASING.md`.

## Reconciliation — 2026-08-07

| Original finding | Current disposition |
|---|---|
| Port regeneration could silently replace the full registry with an overlay-only pack | **Closed.** The authoritative build is now no-egress and consumes the retained, hash-pinned IANA CSV. Schema, UTF-8, inventory, and non-regression failures abort before publication; overlay-only output requires an explicit non-authoritative mode and cannot target the canonical pack. Pack and manifest publication is transactional. |
| OUI provenance depended on a Wireshark `manuf` snapshot | **Superseded.** The shipped registry is rebuilt deterministically from retained IEEE MA-L, MA-M, and MA-S primary CSVs. The legacy `manuf` path is non-authoritative and cannot replace the shipped pack. Public PyPI publication was separately rejected in `RELEASING.md`; reopening public distribution requires a fresh licensing review. |
| Generated packs lacked source/build manifests | **Closed.** The retained-source inventory and adjacent pack manifest bind exact URLs, retrieval timestamps, source SHA-256/byte/row counts, generators, output hashes/counts, authority scope, and overlay metrics. Release verification additionally binds the distribution to the Git commit/tree. |
| Lifecycle rows lacked exact bulletin references and could make negative `active` claims | **Closed.** The table now contains only bounded claims tied to exact Cisco bulletin IDs and HTTPS URLs; unmatched PIDs abstain. There are no `active` evidence rows or derived EoS/LDoS dates. The byte- and semantic-bound Cisco fixture ships with wheels and Atlas, and installed self-test/release gates require full lifecycle authority. |
| Artifact-content auditing was incomplete | **Closed.** Wheel and sdist member policy, privacy checks, installed-wheel smoke tests, and retained-source distribution verification are release gates. |

Two maintenance conditions remain intentionally explicit: retained evidence must
be refreshed before its 180-day freshness limit, and a future public-package
decision must reopen the licensing review. The adjacent registry manifest names
the generator and records overlay metrics rather than carrying literal
`generator_revision` / `overlay_revision` keys; the release proof's exact
commit/tree binding is the accepted revision identity.

## Scope and decision

This review covers the three bundled knowledge bases that can influence assessment output:

1. `cisco_toolkit/data/oui_registry.tsv.gz`
2. `cisco_toolkit/data/port_registry.tsv.gz`
3. the curated lifecycle table in `cisco_toolkit/eoldb.py`

It also covers the wheel and source distribution that could publish those assets.

**Decision at audit time:** the IANA-derived port data is suitable for redistribution with better build metadata; the
lifecycle table is suitable only as an explicitly curated advisory source; and public redistribution of
the current Wireshark-derived OUI pack should be held until the project owner resolves its license and
attribution posture. This is an engineering release gate, not a legal opinion.

## What was verified

### Port and protocol registry

`cisco_toolkit/data/gen_port_registry.py` names the IANA Service Name and Transport Protocol Port
Number Registry as its long-tail source, then applies a project-curated overlay for migration-specific
categories such as routing, storage, OT/ICS, and broadcast A/V.

Official references:

- Registry: <https://www.iana.org/assignments/service-names-port-numbers/service-names-port-numbers.xhtml>
- CSV used by the generator: <https://www.iana.org/assignments/service-names-port-numbers/service-names-port-numbers.csv>
- IANA/IETF licensing statement: <https://www.iana.org/help/licensing-terms>

The IANA/IETF statement dedicates applicable rights in protocol registry data under CC0 1.0 and says
the registries are intended to be freely usable for any purpose. That makes the authoritative IANA
portion the cleanest-provenance bundled data source in this project.

At the time of this audit, two engineering gaps remained:

1. The generated gzip contains no adjacent machine-readable manifest recording source URL, retrieval
   time, source digest, row count, generator revision, or overlay revision.
2. In online mode, the generator catches any IANA download or parse failure and continues with only
   the curated overlay. It then writes that partial result to the canonical output path and returns
   success. A transient network or schema failure can therefore replace the full IANA-derived registry
   with a much smaller overlay-only pack without a failing command.

**Required follow-up at audit time (now closed):** make online regeneration fail closed before touching the existing pack; reserve
partial overlay generation for the explicit `--offline` option. Add a deterministic provenance manifest
and a minimum expected IANA-row guard.

### OUI registry

At the time of this audit, `cisco_toolkit/gen_oui_registry.py` regenerated the pack from a locally downloaded Wireshark `manuf`
file and correctly refuses URLs at runtime. The upstream file itself states that it is generated from
IEEE public allocation lists plus Wireshark/Michael Patton additions and carries
`SPDX-License-Identifier: GPL-2.0-or-later`.

Official references:

- Current Wireshark data download: <https://www.wireshark.org/download/automated/data/manuf>
- Upstream file/header and history: <https://gitlab.com/wireshark/wireshark/-/blob/master/manuf>
- Wireshark repository licensing statement: <https://gitlab.com/wireshark/wireshark/>

The compact TSV reviewed at that time preserved allocation prefixes and vendor names but did not preserve the
source header, source revision/digest, retrieval date, or an attribution/license notice. Meanwhile,
`RELEASING.md` describes the repository as having no license / all rights reserved and also supports an
optional public PyPI release. Those positions are not sufficiently reconciled for a public package that
contains a transformed GPL-labelled upstream dataset.

The exact source snapshot used for the gzip reviewed at that time could not be reconstructed from repository metadata:
there is no source digest or generation manifest. That missing chain of provenance is itself the audit
finding.

**Release gate recorded at audit time (now superseded):** choose and document one defensible path:

- rebuild from a source whose redistribution terms have been reviewed and record that source precisely;
- retain the Wireshark-derived data with the required license/attribution and align the project's
  distribution terms accordingly; or
- omit the OUI pack from public artifacts and require an operator-side local generation step.

The owner should obtain qualified licensing advice before selecting among those paths.

### Hardware lifecycle table

The lifecycle table has two strong controls already:

- `_EOL_REVIEWED` records a curation vintage; and
- tests require every row to carry a non-empty source and a known confidence classification.

At the time of this audit, many source values were descriptive labels rather than exact Cisco bulletin identifiers or
URLs. Rows marked `active` are surfaced as "Active (no end-of-life announced)", which is stronger than
the evidence supports after the review date. The accurate claim is that the curated table had no EOL
date recorded for that model **as of the review vintage**.

Official policy reference:

- <https://www.cisco.com/c/en/us/products/eos-eol-policy.html>

Cisco's current general policy provides five years of hardware TAC support from end of sale, but the
policy also says it does not apply to products already subject to an EOL notification as of
2022-09-29. Product bulletins remain the authority. Therefore `EoS + 5 years` is acceptable only as a
clearly labelled derived estimate, never as a substitute for the exact bulletin date.

**Required follow-up at audit time (now closed):** replace descriptive source labels with exact bulletin IDs/URLs, and render
`active` rows as "no EOL date recorded as of <review date>; verify on Cisco EoX" rather than as a
current evergreen fact.

## Distribution-content audit added in this branch

The previous package CI installed from the source tree and smoke-tested runtime assets, but it did not
inspect the member list of the artifact that would be published. The PyPI workflow also uploaded both a
wheel and source distribution after metadata checks without a confidentiality scan.

This branch adds `tools/audit_wheel.py` (the filename is retained, but it audits both artifact types):

- the wheel is restricted to the runtime package/module roots plus one `.dist-info` directory;
- required OUI, port, explorer, and entry-module assets must be present;
- raw collection directories, every registered command-capture family, collection metadata sidecars,
  snapshots, SQLite state, Office deliverables, and logs are rejected;
- the source distribution receives the same confidentiality checks, while allowing explicitly
  reviewable synthetic captures and sidecars under `tests/`; and
- CI installs the exact audited wheel, while the release workflow audits both the wheel and sdist
  before a PyPI upload step can run.

## Release checklist — current disposition

| Priority | Action | Current status (2026-08-07) |
|---|---|---|
| P0 | Prevent raw client evidence and AssessHub DB state from being committed | Implemented + regression tested against every registered capture filename |
| P0 | Audit wheel and sdist contents before install/publish | Implemented + regression tested |
| P0 | Resolve OUI-pack licensing/attribution before public PyPI release | **Superseded / dormant:** shipped data is IEEE-derived and public PyPI is explicitly out of scope; reopen review if that policy changes |
| P1 | Add source URL/date/SHA-256/row-count manifests for OUI and port packs | Implemented + full-chain tested |
| P1 | Make online port-registry regeneration fail closed | Implemented through a stronger retained-source, no-egress build contract |
| P1 | Replace lifecycle source labels with exact Cisco bulletin references | Implemented + exact fixture/runtime semantic binding tested |
| P1 | Time-bound the UI wording for lifecycle `active` rows | Superseded by stronger abstention; the evidence table contains no negative `active` rows |

## Non-findings and limits

The generators reviewed in 2026 did not read collection directories or AssessHub databases, and no
client-derived network captures were identified in the bundled OUI, port, or lifecycle packs. At audit
time, the compressed packs lacked generation manifests, so their exact source snapshots could not be
independently reconstructed from repository metadata. That gap is now closed by retained-source and
generated-pack manifests plus release source binding. The identified historical risk was provenance,
reproducibility, and release licensing—not an observed customer-data leak. Artifact guards prevent
future packaging changes from silently adding raw customer material alongside the packs.
