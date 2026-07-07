# Config-hardening & access-control posture (CIS-aligned) — 2026-07-07

**Status:** PROPOSE-ONLY assessment finding (rounds out the security assessment: this = config-hardening +
ACL hygiene; KEV = exploited surfaces; fleet-risk = SNMP + currency). **Evidence:** the engine's `security`
block (CIS-aligned per-device findings) + `acls`, in `Migration_Assessment_AUTOFILLED_20260613_063201.snapshot.json`.
**Scope:** 253 config-assessable devices (the 50 not-collected are excluded — not assessed, not clean).

## Headline — the fleet is broadly under-hardened, and the gaps are config-plane (cheap to fix)

Failed CIS-aligned checks across the 253 assessable devices: **76 High · 418 Medium · 12 Low**. **74 of 253
devices carry ≥1 High** hardening failure. None require a reload to remediate.

| Failed check | Devices | Severity | Risk |
|---|---|---|---|
| **VTY line hardening gap** | **247 / 253** (98%; **100% of VTY-bearing devices**) | Medium | ≥1 VTY line missing `access-class` **or** `exec-timeout` — a multi-part OR check, so *partial* hardening still trips it. The mgmt plane is broadly reachable, but this is "≥1 gap," not "unhardened." |
| **Weak local user password storage** | **73** | **High** | Type-7 / cleartext local credentials (not Type-8/9) — recoverable if a config leaks. The dominant High finding. |
| **Insecure SNMP access** | **106** (105 Medium + 1 High) | Medium/High | **The same 106 devices** as the SNMP v2c finding (fleet-risk synthesis) — one check viewed two ways, *not* an independent corroboration. Cleartext community strings. |
| **`service password-encryption` unset** | **64** | Medium | Type-0 cleartext secrets in running-config. |
| **Weak / missing enable secret** | **63** | High(2)/Info | Privileged-EXEC secret weak or absent on a few; advisory on most. |
| No NTP · no logging / banner | 9 · 1 / 2 | Info/Low | Long-tail hygiene. **0 devices have telnet enabled** (the `telnet` check's 6 hits are `na` = "no VTY lines", not enabled telnet). |

**ACL hygiene:** 3,507 ACL rules across 253 devices; **32 `permit any → any`** entries — overly-broad
permits to review (some are legitimate infra rules; each should be justified or scoped).

## What this adds to the security picture
The assessment's security findings now span three tiers, coherent and non-overlapping:
1. **Exploited now** — KEV surfaces (Smart Install, Web UI). *Urgent.*
2. **Cleartext / weak secrets** — SNMP v2c (106) **+ weak local passwords (73 High) + password-encryption
   (64)**. *Credential exposure.*
3. **Access-plane hygiene** — VTY hardening (247), permit-any ACLs (32). *Broad management-plane exposure.*

## Prioritized remediation direction (propose-only; config-plane, no reload)
1. **VTY hardening (247) + password migration (73 High + 64)** — the biggest, cheapest fleet-wide risk
   reduction after KEV Phase-A: apply an SSH-only + `access-class` + `exec-timeout` VTY template, migrate
   Type-7 → Type-8/9, set `service password-encryption`. All config-plane, no reload — a strong candidate to
   **batch with the SNMPv3 change** in one hardening CAB.
2. **ACL review (32 permit-any)** — justify or scope each; a review, not a bulk change.

## Coverage-honesty (Law 3)
- The `security` block is **CIS-aligned screening from parsed config evidence**, not a raw-config audit or a
  penetration test — a `fail` means the hardening token was not observed, which on parsed data is a strong but
  not absolute signal. The 50 not-collected devices are **excluded**, not passed.
- `permit any → any` counts *structural* breadth, not intent — some are legitimate (e.g. an infrastructure
  ACL); the 32 are a **review list**, not 32 confirmed misconfigurations.

**Bottom line:** the fleet is broadly under-hardened (98% have a VTY hardening gap; 73 devices with recoverable
local passwords), but almost every gap is a **no-reload config change** — pairing VTY-hardening +
password-migration + SNMPv3 into one hardening wave is the highest cheap-risk-reduction move after the KEV
Phase-A mitigation. (Note: the SNMP count here is the *same* 106-device population as the fleet-risk finding,
not an additional one.)
