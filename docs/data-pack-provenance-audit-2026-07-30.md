# Offline Data-Pack Provenance Audit — 2026-07-30

## Scope and decision

This review covers the three bundled knowledge bases that can influence assessment output:

1. `cisco_toolkit/data/oui_registry.tsv.gz`
2. `cisco_toolkit/data/port_registry.tsv.gz`
3. the curated lifecycle table in `cisco_toolkit/eoldb.py`

It also covers the wheel and source distribution that could publish those assets.

**Decision:** the IANA-derived port data is suitable for redistribution with better build metadata; the
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

Two engineering gaps remain:

1. The generated gzip contains no adjacent machine-readable manifest recording source URL, retrieval
   time, source digest, row count, generator revision, or overlay revision.
2. In online mode, the generator catches any IANA download or parse failure and continues with only
   the curated overlay. It then writes that partial result to the canonical output path and returns
   success. A transient network or schema failure can therefore replace a full 12k-row registry with a
   much smaller pack without a failing command.

**Required follow-up:** make online regeneration fail closed before touching the existing pack; reserve
partial overlay generation for the explicit `--offline` option. Add a deterministic provenance manifest
and a minimum expected IANA-row guard.

### OUI registry

`cisco_toolkit/gen_oui_registry.py` regenerates the pack from a locally downloaded Wireshark `manuf`
file and correctly refuses URLs at runtime. The upstream file itself states that it is generated from
IEEE public allocation lists plus Wireshark/Michael Patton additions and carries
`SPDX-License-Identifier: GPL-2.0-or-later`.

Official references:

- Current Wireshark data download: <https://www.wireshark.org/download/automated/data/manuf>
- Upstream file/header and history: <https://gitlab.com/wireshark/wireshark/-/blob/master/manuf>
- Wireshark repository licensing statement: <https://gitlab.com/wireshark/wireshark/>

The shipped compact TSV preserves allocation prefixes and vendor names but does not preserve the
source header, source revision/digest, retrieval date, or an attribution/license notice. Meanwhile,
`RELEASING.md` describes the repository as having no license / all rights reserved and also supports an
optional public PyPI release. Those positions are not sufficiently reconciled for a public package that
contains a transformed GPL-labelled upstream dataset.

The exact source snapshot used for the current gzip cannot be reconstructed from repository metadata:
there is no source digest or generation manifest. That missing chain of provenance is itself the audit
finding.

**Release gate before public PyPI distribution:** choose and document one defensible path:

- rebuild from a source whose redistribution terms have been reviewed and record that source precisely;
- retain the Wireshark-derived data with the required license/attribution and align the project's
  distribution terms accordingly; or
- omit the OUI pack from public artifacts and require an operator-side local generation step.

The owner should obtain qualified licensing advice before selecting among those paths.

### Hardware lifecycle table

The lifecycle table has two strong controls already:

- `_EOL_REVIEWED` records a curation vintage; and
- tests require every row to carry a non-empty source and a known confidence classification.

However, many source values are descriptive labels rather than exact Cisco bulletin identifiers or
URLs. Rows marked `active` are surfaced as "Active (no end-of-life announced)", which is stronger than
the evidence supports after the review date. The accurate claim is that the curated table had no EOL
date recorded for that model **as of the review vintage**.

Official policy reference:

- <https://www.cisco.com/c/en/us/products/eos-eol-policy.html>

Cisco's current general policy provides five years of hardware TAC support from end of sale, but the
policy also says it does not apply to products already subject to an EOL notification as of
2022-09-29. Product bulletins remain the authority. Therefore `EoS + 5 years` is acceptable only as a
clearly labelled derived estimate, never as a substitute for the exact bulletin date.

**Required follow-up:** replace descriptive source labels with exact bulletin IDs/URLs, and render
`active` rows as "no EOL date recorded as of <review date>; verify on Cisco EoX" rather than as a
current evergreen fact.

## Distribution-content audit added in this branch

The previous package CI installed from the source tree and smoke-tested runtime assets, but it did not
inspect the member list of the artifact that would be published. The PyPI workflow also uploaded both a
wheel and source distribution after metadata checks without a confidentiality scan.

This branch adds `tools/audit_wheel.py` (the filename is retained, but it audits both artifact types):

- the wheel is restricted to the runtime package/module roots plus one `.dist-info` directory;
- required OUI, port, explorer, and entry-module assets must be present;
- raw collection directories, sensitive command captures, snapshots, SQLite state, Office
  deliverables, and logs are rejected;
- the source distribution receives the same confidentiality checks, while allowing explicitly
  reviewable synthetic captures under `tests/`; and
- CI installs the exact audited wheel, while the release workflow audits both the wheel and sdist
  before a PyPI upload step can run.

## Release checklist

| Priority | Action | Status in this branch |
|---|---|---|
| P0 | Prevent raw client evidence and AssessHub DB state from being committed | Implemented + regression tested |
| P0 | Audit wheel and sdist contents before install/publish | Implemented + regression tested |
| P0 | Resolve OUI-pack licensing/attribution before public PyPI release | **Open release gate** |
| P1 | Add source URL/date/SHA-256/row-count manifests for OUI and port packs | Open |
| P1 | Make online port-registry regeneration fail closed | Open |
| P1 | Replace lifecycle source labels with exact Cisco bulletin references | Open |
| P1 | Time-bound the UI wording for lifecycle `active` rows | Open |

## Non-findings

No evidence was found that the bundled OUI, port, or lifecycle packs contain client-derived network
captures. Their risk is provenance, reproducibility, and release licensing—not customer-data leakage.
The artifact guards added here ensure that future packaging changes cannot silently add raw customer
material alongside them.
