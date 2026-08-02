# Offline data-authority contract

Atlas treats byte integrity, source authority, and coverage as separate facts.
An intact file is not authoritative merely because it has a hash, and an
uncovered product family is not healthy merely because no lifecycle row exists.

## IEEE OUI authority

`cisco_toolkit/data/oui_registry.tsv.gz` is generated from the retained IEEE
Registration Authority MA-L, MA-M, and MA-S CSVs. The exact official URLs,
bytes, hashes, schemas, retrieval batch, and row counts are pinned in
`official-sources/manifest.json`. Runtime loading verifies the generated pack;
repository verification additionally proves the pack back to those retained
primary-source bytes. An installed wheel can verify its code-pinned pack build,
but reports `source_authoritative: false` because wheels intentionally omit the
retained CSVs.

## IANA port authority

`cisco_toolkit/data/port_registry.tsv.gz` is generated from the retained IANA
Service Name and Transport Protocol Port Number Registry, then augmented by the
repository's documented semantic overlay and multicast table. The generator is
no-egress and refuses a missing, changed, malformed, or regressed official
input without replacing the current pack. All 232 additional aliases on 226
duplicate IANA keys are preserved. Official service labels never yield to the
overlay; known collisions at 4444/udp, 4455/udp, and 8800/udp are disclosed and
their curated AV inference is suppressed. Pack-wide authority remains false
because curated overlay and multicast records are intentionally
non-authoritative.

## Cisco lifecycle authority

`cisco_toolkit/eoldb.py` contains only EoS and LDoS dates copied from exact
Cisco EoL bulletins. Its 44 bounded PID scopes are backed by 17 named `EOL…`
bulletins and exact official Cisco URLs. There are no derived support dates and
no negative "no EoL announced" claims. Broad or unlisted families return
`Unknown`; callers must verify the exact PID in Cisco EoX rather than infer
support from absence. `official-sources/cisco/eol-bulletins.json` is a
hash-pinned, fact-only primary-source fixture. The verifier requires its 17
URLs, 44 PID scopes, dates, and runtime rows to match exactly.

All three authority domains expose a 180-day freshness limit and reject source
timestamps more than five minutes in the future. A trust decision requires
both source authority and freshness; byte integrity alone is insufficient.

The focused offline proof is:

```text
python -m pytest -q tests/test_registry_integrity.py \
  tests/test_gen_oui_registry.py tests/test_eoldb_provenance.py \
  tests/test_lifecycle.py
```
