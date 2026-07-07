---
name: hardening-mop-platform-partition
description: When authoring config-hardening remediation MOPs here, partition every gap count by platform (IOS vs NX-OS vs FEX) before writing per-command steps — the finding's headline counts blend platforms.
metadata:
  type: feedback
---

When authoring a config-plane hardening/remediation MOP off the engine `security` block, **partition every
gap count by device platform (IOS vs NX-OS vs "Fex"-named) before writing any per-command step.** Match each
host in `docs/assessment/config-hardening-devices.json` against `snap['devices'][host]['platform']` (all hosts
reconcile, 0 unmatched) and split the SSOT count into cohorts.

**Why:** the finding's headline counts silently blend platforms, and IOS remediation syntax does **not** map to
NX-OS, so a platform-blind MOP would instruct an operator to run impossible commands. Concretely, in the
2026-06-13 snapshot the *same 55 NX-OS devices* trip vty-hardening + weak-user-pw + password-encryption, and:
- `service password-encryption` is **IOS-only** (no such NX-OS command) — it applied to only 9 of the 64
  "password-encryption unset" devices; the other 55 are an NX-OS check-applicability artifact, not a fixable gap.
- `username X algorithm-type sha256 secret` (Type-8/9) and `transport input ssh` are IOS-XE syntax; NX-OS uses
  Type-5/role-based users and `feature telnet`/`line vty` controls.
- 11 entries named `Fex*`/`FEX*` (model `N5K-C56128P`) are **resolve-first, not silent-exclude**: a true fabric
  extender has no independent VTY/user/SNMP/SSH plane (configure at the parent), but a 5600 switch informally
  named "Fex" is directly configurable — pre-check must resolve which before pushing config.

**How to apply:** do the reconciliation with a throwaway script (owner of totals = `cisco_toolkit.ssot.canonical_facts`;
303/253/50), present a cohort table (SSOT total = IOS + NX-OS switch + resolve-first), write **per-platform
command blocks**, and defer exact NX-OS syntax to dry-run (N5K/N6K/N9K versions differ). Do **not** restate the
counts as durable — regenerate them from the snapshot each time. Keep the MOP propose-only and parameterize every
credential/ACL/scheme input. Related: [[hardening-wave-mop-status]].
