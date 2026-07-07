---
name: hardening-wave-mop-status
description: The hardening-wave remediation MOP (assessment action #2) is authored propose-only at docs/security/hardening-wave-mop-2026-07-07.md, blocked on 3 execution inputs.
metadata:
  type: project
---

The **hardening wave** (assessment remediation **action #2** — config-plane, no-reload fleet-wide risk
reduction) has a PROPOSE-ONLY MOP + rollback authored at
`docs/security/hardening-wave-mop-2026-07-07.md` (three sub-changes: **H1** VTY hardening,
**H2** local-credential hardening, **H3** SNMPv2c→SNMPv3, plus an ACL review of 8 devices / 32 permit-any).

**Why:** it rounds out the security assessment (config-hardening + ACL hygiene tier) alongside the KEV and
fleet-risk findings; the finding recommends batching VTY + password + SNMPv3 into one hardening CAB.

**How to apply:** it is **NOT execution-ready** — gated on **(a)** the customer SNMPv3 scheme, **(b)**
NMS-first SNMPv3 coordination (poller confirmed polling per device *before* v2c removal — the QA-flagged
sequencing), and **(c)** CAB approval after an independent dry-run. Proposer ≠ verifier: the NRFU/ATP
acceptance is authored separately by **nrfu-validator**, not in this MOP. If asked to advance it, check
those gates first and do not fill the `<placeholder>` design inputs by inventing values. See
[[hardening-mop-platform-partition]] for the per-platform cohort discipline this MOP depends on.
