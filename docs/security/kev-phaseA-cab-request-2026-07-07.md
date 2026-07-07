# CAB Change Request — KEV Phase A: close the actively-exploited surface (interim mitigation)

**Type:** Security / normal change · **Risk:** Low–Medium · **Reload required:** **No** · **Status:** DRAFT for
CAB · **Requested by:** automated senior-engineer engagement · **Prepared:** 2026-07-07

> Board-facing approval ask. The execution detail is the MOP; this is the decision summary. Nothing has been
> applied — approval + a window are what this requests.

## 1. What & why (one paragraph)
Close two **actively-exploited** (CISA-KEV) attack surfaces on the IOS/IOS-XE fleet **without a reload**:
disable **Smart Install** (CVE-2018-0171 RCE) on the 96 IOS devices where it is flagged, and disable or
ACL-restrict the **IOS-XE HTTP/HTTPS Web UI** (CVE-2023-20198 + -20273, CVSS 10, mass-exploited) on the 8 IOS
devices where it is flagged. These are config-plane changes; they do not upgrade software and do not reboot.

## 2. Scope (SSOT-reconciled, QA-approved)
| Action | Devices | Source of truth |
|---|---|---|
| A1 — disable Smart Install (`no vstack`) | **96** IOS | `kev-exposure-2026-07-07-devices.json :: smart_install_flagged` (IOS members) |
| A2 — disable / ACL-restrict Web UI | **8** IOS | same file `:: http_server_flagged` (IOS members) |
| Canaries (do first) | **3** confirmed-`exposed` instances on 2 devices: `AAS13-BC-CR02R03-TCDOH` (both surfaces), `AS01-BC-CA01RA13-CXDOH` (Web UI) | independently verified |
| **Explicitly OUT of scope** | 55 NX-OS (IOS CVEs don't apply — screening artifacts); all software upgrades (Phase B); the 56 NOT_COLLECTED devices | verified by MOP + NRFU + QA |

## 3. Risk & impact (grounded in the blast-radius annex)
- **Smart Install (A1): data-plane impact = none.** TCP/4786 control-plane listener; appears in no VLAN/route/
  gateway path. Disabling changes zero modeled reachability.
- **Web UI (A2): management-plane only.** No modeled data-plane dependency. But the model cannot see mgmt-HTTP
  dependencies (RESTCONF / Prime / Catalyst Center) — so **OOB console standby is mandatory** for all 8, and
  `AS01/AS02-BC-CAR11RD22` (unknown platform, highest lock-out consequence) use **ACL-restrict, not disable**,
  with platform verified in the pre-check.
- **Blast radius of the change itself:** none require a reload, so the reload blast-radius (the 21 priority
  devices) does **not** apply to Phase A — that is Phase B.

## 4. Rollback & backout criteria
- **Rollback:** re-enable `ip http server`/`secure-server` or correct/remove the `ip http access-class`; for A1,
  re-add `vstack` — via console/OOB, `write memory`, confirm management restored (full matrix in MOP §9).
- **Backout trigger:** loss of RESTCONF / Catalyst Center / Prime management, NMS webhook failure, or the mgmt
  host cannot reach after the ACL.

## 5. Success criteria (independent — owned by `nrfu-validator`, not the implementer)
Per-device surface-closed observable = PASS: `show vstack config` → OFF / no `vstack`; `show ip http server
status` → Disabled (or Enabled **with** an access-class limited to the mgmt host). A single counterexample
blocks the wave. Full ATP: `kev-remediation-nrfu-2026-07-07.md`.

## 6. Proposed window & sequencing
Short maintenance window (config-plane only, no reload). Order: **the 2 canary devices first** (console
standby) → the remaining IOS devices in small batches. Est. change duration per device < 5 min; per-device
pre-check + post-check bracket each.

## 7. Approvals requested
- [ ] Change Advisory Board — approve the window
- [ ] Security lead — accept the residual (verify-flag devices where the service may already be off)
- [ ] Network operations — OOB console availability confirmed for the 8 Web-UI devices

## 8. What this CAB does NOT cover (stated, not hidden)
- **Phase B (software upgrades)** — blocked on the **PSIRT fixed-version sweep** (KEV lacks fixed releases); a
  separate CAB with per-wave reload blast-radius (blast-radius annex) and the per-device redundancy pre-check.
- **The 56 NOT_COLLECTED devices** — a read-only collection must run first; their exposure is UNKNOWN, not clean.

**References (the full propose-only package):** `kev-exposure-2026-07-07.md` (finding) ·
`kev-exposure-2026-07-07-devices.json` (SSOT) · `kev-remediation-mop-2026-07-07.md` (execution MOP) ·
`kev-remediation-nrfu-2026-07-07.md` (acceptance) · `kev-remediation-blast-radius-2026-07-07.md` (blast radius).
