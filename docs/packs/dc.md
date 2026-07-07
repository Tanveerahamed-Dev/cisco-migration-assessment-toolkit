# Domain pack — DC / ACI

A **retrieval lens**, not a standing agent (D6). Loaded by `cisco_toolkit.domain_packs.select_packs` **iff**
one of its architecture classes was *observed* in the snapshot's `architecture_coverage`. Surfaced on demand
as a `/council` lens for consequential DC-touching outputs.

**Architecture classes this pack reviews** (keys into the authoritative
`cisco_toolkit/design_advisor.py :: _ARCH_COVERAGE_REGISTRY` — that registry owns the detector ids; cite it,
don't restate):

| class key | what | channel |
|---|---|---|
| `aci` | Cisco ACI (APIC fabric) | json (controller-REST) |
| `overlay` | VXLAN-EVPN overlay (NVE / EVPN / VNI) | ssh show-text |
| `arista` | Arista EOS DC fabric (MLAG + BGP-EVPN) | ssh show-text |

## Domain review checklist (evidence-grounded — cite the field/line, never infer state)

- **APIC fabric health.** Fabric fully-fit? Any critical faults raised (F-codes)? Every node
  active/registered (not `aci-node-not-active`)? Fabric-health not degraded?
- **ACI segmentation.** Any VRF with enforcement *unenforced*? That is an open segmentation posture —
  confirm it is intended, not an accident (`aci-vrf-enforcement-unenforced`).
- **VXLAN-EVPN overlay.** All NVE peers up? The EVPN control plane (BGP L2VPN-EVPN) up? Every configured
  VNI mapped and up (no `vxlan-nve-vni-down`)?
- **vPC / MLAG.** Peer-link **and** keepalive both up? Domain parameters consistent across the pair? Any
  orphan ports carrying VLANs that are single-homed (blast radius on a peer failure)?
- **BGP-EVPN (Arista/NX).** All EVPN peers established? Route-type 2/5 advertised as designed?
- **ACI migration move-groups.** `design_blueprint.target_state.aci_move_groups` reconciled to the target
  state; per-EPG/BD move ordering respects contracts + L4-L7 service graphs; no move that strands a
  provider/consumer.

## Coverage-honesty (Law 3)

`not-observed` for `aci` is **not** "healthy" — it means no APIC export was collected. If ACI is in scope,
collect read-only first (`python -m cisco_toolkit.rest_collect apic --url … --user <ro> --password <pw>
--out-dir <dir>`), then analyze `--no-collect`. A missing NVE/MLAG capture is an evidence gap, not a clean
fabric.

## Promotion rule (D6 / D1)

This stays a pack + lens. It becomes a standing sub-agent **only** when a real engagement sustains the load
**and** the eval shows the pack alone is insufficient — client-gated. The standing roster stays at 8.
