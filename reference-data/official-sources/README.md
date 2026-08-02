# Retained official registry sources

This directory contains the exact primary-source CSV bytes used to generate the
offline OUI and port packs, plus a fact-only semantic fixture for 17 official
Cisco lifecycle bulletins. Runtime lookup never uses the network. Wheels omit
this directory; sdists retain it so a source checkout or release verifier can
prove the full chain:

1. the source inventory pins the official HTTPS URL, retrieval timestamp,
   byte length, SHA-256, UTF-8 encoding, CSV header, and row count;
2. each generator verifies those contracts before parsing;
3. deterministic gzip output (`mtime=0`) is bound into
   `cisco_toolkit/data/registry_manifest.json`; and
4. repository tests verify the retained bytes, inventory, generated pack, and
   runtime loader as one chain; and
5. the EoL verifier byte-checks its retained JSON, validates 17 exact Cisco
   URLs, and compares all 44 date/PID-scope claims to runtime code.

The 2026-07-30 build produces:

- 53,486 unique OUI lookup keys from 53,489 IEEE rows. IEEE currently
  publishes two MA-L keys with conflicting organization names; the generator
  preserves every published claimant in a deterministic combined value and
  records `conflicting_prefix_count: 2` instead of silently choosing one.
- 12,352 port records: 12,341 unique IANA assignments plus 11 overlay-only
  records. The 226 duplicate IANA keys retain all 232 additional official
  aliases in source order.
- 21 bounded curated multicast records. Curated port semantics and multicast
  records are explicitly non-authoritative; generic 232/8 and 239/8 AV/on-air
  claims are not present.
- 44 bounded Cisco lifecycle scopes from 17 exact official bulletin URLs,
  cryptographically and semantically bound by `cisco/eol-bulletins.json`.

The generated gzip streams use `mtime=0`, and their manifest timestamp is the
retained source batch timestamp. Rebuilding from the same evidence is therefore
byte-identical.

The retained inputs were acquired on 2026-07-30 directly from:

- IEEE Registration Authority MA-L:
  `https://standards-oui.ieee.org/oui/oui.csv`
- IEEE Registration Authority MA-M:
  `https://standards-oui.ieee.org/oui28/mam.csv`
- IEEE Registration Authority MA-S:
  `https://standards-oui.ieee.org/oui36/oui36.csv`
- IANA Service Name and Transport Protocol Port Number Registry:
  `https://www.iana.org/assignments/service-names-port-numbers/service-names-port-numbers.csv`
- 17 Cisco End-of-Life bulletin URLs enumerated exactly in
  `cisco/eol-bulletins.json`.

Refreshing is an explicit evidence update: download to a temporary location,
verify strict UTF-8 and the expected CSV schema, replace the retained input,
then update the inventory hash/size/row count and regenerate. Do not add live
network fetching to the generators. Registry and EoL authority expire after
180 days; timestamps more than five minutes in the future are rejected.
