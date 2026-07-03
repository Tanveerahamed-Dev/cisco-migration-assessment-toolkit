# Parser format-fidelity verification

A parser that silently returns `[]` (or fabricates a healthy state) on a real device's output turns the
engine's prime doctrine — *coverage-honest* — into its opposite: **coverage-blind**. The architecture-class
parsers were originally validated only against synthetic fixtures authored alongside the parsers, so the test
and the code shared the same assumptions about what real Cisco output looks like. This page records the
adversarial verification campaign that closed that gap, the bugs it found, and the residual gaps.

## The campaign

A 33-lane workflow ran one skeptical verifier per universal-architecture parser. Each agent read the actual
function from `parse.py`, web-researched the **real** output of its command across platforms/trains (primary
Cisco docs + real captures), and adversarially checked whether the parser's exact assumptions — regex anchors,
fixed-column positions, JSON keys, state tokens — match real output on the *firing path* (would the detector's
key field be correctly extracted?). Verdict distribution: **13 match, 2 mismatch, 21 partial**. Every flagged
verdict was then re-verified against the code + cited source before any change; each genuine firing-path bug
was fixed **test-first** (a fixture built from the *real* format → watch it fail → fix → watch it pass).

**The dominant bug class:** a parser built/tested against ONE platform's format silently fails on the OTHER
platform's real output — NX-OS vs IOS-XE column/label splits — or on the BGP-summary line-wrap that occurs for
wide addresses/ASNs. Several were empirically reproduced against the live parser by the verifiers. This matters
acutely because the canonical AJ fleet's DS/CS core + EVS vPC pair are **Nexus** — so the NX-OS blind spots hit
the real target estate, not a hypothetical one.

## Fixes (15 parser functions, test-first, real-format fixtures)

| Parser | Real-world failure (before) | Fix |
|---|---|---|
| `_parse_bgp_summary_rows` (EVPN + VPNv4) | a wrapped row read the AS number as the state → **fabricated `Established` for a genuinely Idle/down peer** (false-health); IPv6/asdot peers dropped | stitch wrapped rows; accept IPv4/IPv6/asdot |
| `parse_bgp_ipv6_summary` | a wrapped long-IPv6 peer vanished entirely (down peer read as "no IPv6 BGP") | delegate to the fixed shared helper |
| `parse_dmvpn_peers` | a tunnel up/down ≥24h (`48w0d`) or `never` was dropped — the *most common* real broken case | broaden the UpDn anchor to Cisco compact-uptime + `never` |
| `parse_bfd_neighbors` | a wide 32-bit discriminator drifted the columns → State read as the Holdown `)` / the interface; a real Down session missed | read State by TOKEN (after the Holdown paren), not header char-position |
| `parse_copp_drops` | NX-OS one-line `module N : … dropped Y bytes` (counter mid-line) missed → CoPP-drop blind on Nexus (CoPP is a Nexus default) | scan counters anywhere in the line |
| `parse_ipv6_interface_addrs` | NX-OS format entirely different → `[]` for every Nexus → a `[DUPLICATE]` DAD failure on the Nexus core read as clean | add an NX-OS branch (header / `IPv6 address:` block / link-local) |
| `parse_hsrp_detail` | HSRPv2 header `Vlan50 - Group 50 (version 2)` failed the `$`-anchored regex → whole group dropped → FHRP detector blind on HSRPv2 | relax the anchor; capture the version |
| `parse_pim_rp_mapping` | NX-OS prints `Group ranges:` (not `Group(s)`) → groups empty → SSM-only valve dead → **false-positive** "PIM up, no RP" on a healthy SSM-only Nexus | accept the NX-OS wording (findall, multi-range) |
| `parse_neighbors_detail` | NX-OS LLDP has no `Local Intf:` → one Frankenstein record for N neighbours → shadow-infra detector fed garbage on every Nexus switch | platform-aware split (`Chassis id:` / `Local Port id:`); NX-OS CDP `IPv4 Address` |
| `parse_ipv6_route_summary` | the real number-first comma list (`37 local, 35 connected, …`) matched no branch → `by_source` empty | add a number-first comma-list branch |
| `parse_mpls_l2vpn_vc` | a two-word `ADMIN DOWN` status dropped the row entirely | anchor on the VC-ID position; status = everything to its right |
| `parse_pim_neighbors` | a PIM-over-Tunnel (DMVPN/mGRE WAN) neighbour failed the interface-validity gate and vanished | add `Tunnel`→`Tu` to `normalize_ifname` + `VALID_IFACE_RE` |
| `parse_nve_peers` / `parse_nve_vni` | IOS-XE Catalyst 9000 VXLAN layout differs (VNI in col 2, `L2CP/L3CP` fusion) → `[]` for the entire IOS-XE VTEP fleet | add an IOS-XE branch (formats web-verified against the Catalyst 9300 BGP-EVPN-VXLAN guide) |
| `parse_cts_environment_data` | NX-OS prints `Current State : CTS_ENV_DNLD_ST_ENV_DOWNLOAD_DONE` — a **colon** separator and an **enum** success token (not `= COMPLETE`) → the parser returned `{}` **and** the detector would **false-fire** on a fully-downloaded *healthy* Nexus | accept `:`; normalize the NX-OS DONE enum → `COMPLETE` (verified vs the DevNet NX-API CTS ref) |
| `parse_policymap_drops` | IOS 15.x+ LLQ priority classes report drops as `b/w exceed drops: N` on the `Priority:` line — the parser's `Priority:` `continue` skipped it, so a **voice/video LLQ shedding real-time traffic reported 0 drops** and the HIGH detector never fired | capture `b/w exceed drops`; `max()`-guard so a co-present aggregate `queue stats for all priority classes` 0/0/0 line can't clobber it (format web-verified) |

Each fix is locked by a real-format regression test in `tests/test_parsers.py`; the golden snapshot is
**unchanged** (the fixes are purely additive — existing fixtures parse identically; only previously-unhandled
real formats gain coverage).

## Detector enhancements (follow-up — closed 2 of the 3 residuals)

Two residuals were closed not by a parser-format fix but by a **detector** change — test-first, golden
unchanged, and **AJ-re-verified coverage-honest**: both stay silent on the AJ fleet (which collected neither
axis, so AJ holds steady at 40 decisions) and would fire on a customer that has the condition.

- **`_d_storm_control_active`** (new detector) — fires on an observed storm-control `Filter State = Blocking`
  (a broadcast/multicast/unicast storm being suppressed *right now*). Directly observed, so it works on the
  Catalyst `show storm-control` form that omits the Action column — exactly where `_d_storm_control_action` was
  structurally dead. Registered in `_DETECTORS` + the coverage registry; only `Blocking` fires (Forwarding /
  link-down / absent stay silent).
- **`parse_policymap_drops` NX-OS ingress** — the egress-only `_flush` gate now also records NX-OS `(queuing)`
  classes regardless of direction, so **Nexus ingress (VOQ) queue drops** are seen by `_d_qos_runtime_drops`;
  an IOS-XE *non-queuing* input policy stays correctly ignored (egress-only).

## Residual gaps (1 remaining — documented, not guessed)

Per the rigor floor (don't ship code for an unverified format) and proportion, this is recorded rather than
guessed:

| Parser | Gap | Why deferred / fix approach |
|---|---|---|
| `parse_port_security_detail` | NX-OS un-blinding needs two things this command can't cleanly give: **(a)** the per-interface DETAIL layout / interface-delimiter could not be authoritatively obtained (cisco.com 403s; DevNet + ManualsLib give only field *labels*); **(b)** on NX-OS a violation err-disable shows `port_status=secure-down` — but `secure-down` is **also** a plain link-down port, so the IOS-XE detector (fires on `secure-shutdown`) cannot be reused without a `secure-down AND violation_count>0` guard — a detector-semantics change with cry-wolf risk | fix when a real NX-OS `show port-security interface` capture is in hand: broaden the enable-anchor to `Configured/Opertional Port Security` [sic] + add the `secure-down`+violation guard |

## Method note

The campaign embodies *proposer ≠ verifier*: the per-parser agents proposed verdicts; the consequential ones
were re-verified against code + primary sources before any edit, and the highest-stakes JSON-controller lanes
(ACI/SD-WAN attribute keys) were independently cross-checked by hand against the APIC/vManage object models
(all confirmed `match`). The lesson generalises: **validating a parser only against a fixture you authored
proves the fixture, not the parser** — real-format fidelity must be checked against real output.
