# Domain pack — Security / ISE-TrustSec-firewalls

A **retrieval lens**, not a standing agent (D6). Loaded by `cisco_toolkit.domain_packs.select_packs` **iff**
one of its architecture classes was *observed*. Surfaced on demand as a `/council` lens for security-touching
outputs.

**Architecture classes this pack reviews** (keys into `cisco_toolkit/design_advisor.py ::
_ARCH_COVERAGE_REGISTRY`):

| class key | what | channel |
|---|---|---|
| `cts` | TrustSec / CTS segmentation | ssh |
| `ise` | Cisco ISE (Identity Services Engine) | json |
| `firewall` | Cisco firewall (ASA/FTD: HA + capacity) | ssh |
| `fmc` | Cisco Secure Firewall Mgmt Center | json |
| `fortigate` | Fortinet FortiGate HA (cluster sync) | ssh |
| `juniper` | Juniper SRX chassis cluster (HA) | ssh |
| `cloud` | Public cloud exposure (AWS security groups) | json |
| `copp` | Control-plane policing (CoPP) | ssh |
| `ntp` | Time synchronization (NTP) | ssh |
| `port_security` | Access-edge port-security | ssh |

## Domain review checklist

- **TrustSec / CTS.** Environment data downloaded (no `cts-environment-data-not-downloaded`)? SGT
  classification + propagation intact across the path? SGACL enforcement where the design requires it.
- **ISE.** All deployment nodes reachable? PSN redundancy present (no single policy-service node)?
  Admin / MnT redundancy?
- **Firewalls.** ASA/FTD HA failover healthy + no resource exhaustion; FMC — device connected, no pending
  deployment, no version inversion, manager-HA healthy; FortiGate cluster **in sync**; Juniper SRX
  chassis-cluster HA not degraded. A stateful-firewall pair that fails open/asymmetric is a cutover risk.
- **Cloud exposure.** No security group with open ingress (`0.0.0.0/0`) to sensitive ports
  (`cloud-security-group-open-ingress`).
- **Device hardening baseline.** CoPP policing present and not dropping legitimate control traffic; NTP
  time-sync + logging baseline (so logs are correlatable and evidence is trustworthy); access-edge
  port-security.

## Coverage-honesty (Law 3)

`not-observed` ≠ secure. No ISE export / no CoPP capture means the posture was **not** assessed — never let
"not observed" become "hardened". The bare `show logging`-on-NX-OS false-health class is the canonical trap.

## Promotion rule (D6 / D1)

Pack + lens only; standing sub-agent solely when a real engagement sustains the load and the eval proves the
pack insufficient (client-gated). Roster stays at 8.
