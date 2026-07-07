# MOP — KEV exposure remediation (Smart Install + IOS-XE Web UI) — 2026-07-07

> **PROPOSE-ONLY / DRAFT-FOR-REVIEW.** This is a reviewable change artifact (a PR), **not** an execution
> record. Nothing here has been run. The authoring agent (`mop-change-author`) **never writes to a device,
> never executes this MOP, never merges its own work.** Every step below is applied only by a **human change
> engineer**, inside an approved **CAB maintenance window**, after independent dry-run validation. Forward
> steps each carry an explicit rollback with trigger conditions (see the [Rollback matrix](#9-rollback-matrix)).

| | |
|---|---|
| **Document ID** | MOP-KEV-2026-07-07 |
| **Version** | 0.1 (draft — pre-CAB) |
| **Status** | PROPOSE-ONLY — awaiting the gates in §3 before CAB submission |
| **Gate position** | Assess → *(finding approved)* → **MOP + rollback (this artifact)** → *(dry-run + CAB)* → NRFU acceptance → cutover → PIR |
| **Author** | `mop-change-author` (machine; proposer only — does **not** apply changes) |
| **Verifier (independent)** | `nrfu-validator` — owns NRFU/ATP acceptance criteria (**not** authored here; see §8) |
| **Blast-radius (independent)** | `topology-reachability-analyst` — owns per-wave reachability / SPOF report (gate; see §3) |
| **Driving finding** | `docs/security/kev-exposure-2026-07-07.md` (verified) |
| **Device roster (SSOT)** | `docs/security/kev-exposure-2026-07-07-devices.json` — the authoritative per-device group membership; this MOP does **not** maintain a second copy |
| **Current-state baseline** | `Migration_Assessment_AUTOFILLED_20260613_063201.snapshot.json` (`software_risk.per_device`) |
| **Reproduce / re-assess** | `python -m cisco_toolkit.intel_feed --dir docs/intel Migration_Assessment_AUTOFILLED_20260613_063201.snapshot.json` |

---

## 1. Purpose & background

Today's CISA **Known-Exploited-Vulnerabilities** sweep (the research lane's signed feed) matched the engine's
`software_risk` config-screening surfaces to CVEs that are **actively exploited in the wild**, promoting two
attack surfaces from *"verify someday"* to *"remediate now"*:

| Exploited CVE(s) | Surface | Engine flag |
|---|---|---|
| **CVE-2018-0171** — Cisco Smart Install RCE (unauth, TCP/4786) | `smart-install` | 151 devices `verify`/`exposed` |
| **CVE-2023-20198 + CVE-2023-20273** — IOS XE Web UI privilege-escalation → RCE (CVSS 10, mass-exploited Oct 2023) | `http-server` | 63 devices `verify`/`exposed` |

This MOP proposes a **three-phase** remediation:

- **Phase A — interim mitigation** (fast, low-risk, no reload): close the actively-exploited surface *now* by
  disabling / restricting the vulnerable service on the flagged devices.
- **Phase B — durable upgrade** (phased, with reloads): move the end-of-maintenance devices to a PSIRT-fixed
  release, priority devices first.
- **Phase C — close the coverage gap**: collect running versions for the 56 devices whose exposure is
  currently **unknown** (read-only).

---

## 2. Scope & SSOT reconciliation

Every count and roster below is reconciled to `kev-exposure-2026-07-07-devices.json` (SSOT) — verified
programmatically (`len()` per key == `_counts`). The **platform cohort split** inside each group is a
*command-correctness* decomposition (it does not change the SSOT totals): `no vstack` is an IOS/IOS-XE-only
CLI, and CVE-2023-20198/20273 are IOS-XE-Web-UI-specific — **neither applies to NX-OS**, so NX-OS/FEX members
must not receive the IOS commands.

| SSOT group (JSON key) | Count | Platform cohorts | KEV CVE applicability | Handled in |
|---|---:|---|---|---|
| `smart_install_flagged` | **151** | 96 IOS + 55 NX-OS (Nexus N5K/N6K/N9K + 11 FEX) | CVE-2018-0171 → **IOS/IOS-XE Smart Install client only** | A1 (96 IOS) · A3 (55 NX-OS, verify-only) |
| `http_server_flagged` | **63** | 8 IOS + 55 NX-OS | CVE-2023-20198/20273 → **IOS-XE Web UI only** | A2 (8 IOS) · A3 (55 NX-OS, verify-only) |
| `priority21_eol_and_exposed` | **21** | 19 IOS + 2 NX-OS — a strict **subset** of `replace_upgrade_train` | old train **and** exposed surface | B — Wave 1 |
| `replace_upgrade_train` | **54** | 52 IOS XE 3.x + 2 NX-OS 6.x | past software maintenance | B — Wave 1 (21) + Waves 2+ (33) |
| `not_collected_version` | **56** | version blank → `NOT_COLLECTED` | **UNKNOWN — not assessed, not "clean"** | C |

Reconciliation checks (all pass): `96 + 55 = 151`; `8 + 55 = 63`; `priority21 ⊂ replace_upgrade`;
`21 + 33 = 54`. **62 of the 63** `http_server` devices are also in `smart_install` (the 55 NX-OS + 7 IOS); the
one `http_server`-only device is `AS01-BC-CA01RA13-CXDOH` (IOS).

### 2.1 Surface-confirmed-OPEN devices — do these FIRST (canaries)

Only these carry an engine flag of **`exposed`** (surface confirmed open), vs. `verify` (service present,
enabled-state unconfirmed). They are the highest-priority targets and the per-phase canaries:

| Device | Platform / model | Software | Exposed surface(s) |
|---|---|---|---|
| **`AAS13-BC-CR02R03-TCDOH`** | IOS / WS-C4948E | 15.2(2)E7 (Classic IOS 15.x) | **BOTH** Smart Install **and** HTTP Web UI |
| **`AS01-BC-CA01RA13-CXDOH`** | IOS / WS-C3850-48T | 03.06.06E (IOS XE 3.x) | HTTP Web UI |

> **Coverage-honesty (Law 3).** All other flagged devices are `verify`, not confirmed-enabled. Each must have
> its current service state confirmed in the phase pre-checks **before** any change. The KEV feed lacks
> fixed-versions, so Phase B targets are stated as **TBD (PSIRT sweep required)** — no version is fabricated.

---

## 3. Preconditions & gate status (GATE — do not submit to CAB until green)

This MOP is authored now because the driving finding is verified and the interim mitigation is time-critical.
It **must not be executed** until the following are satisfied. Items marked **OUTSTANDING** are hard blockers
owned by other roles.

| # | Precondition | Owner | Status |
|---|---|---|---|
| P1 | Verified KEV finding (current-state baseline) | assessment / research lane | ✅ met (`kev-exposure-2026-07-07.md`) |
| P2 | Device roster reconciled to SSOT | this MOP | ✅ met (§2) |
| P3 | **Per-wave blast-radius / reachability report** — mgmt-plane dependency (Phase A), redundancy & routing adjacency (Phase B) | `topology-reachability-analyst` | ⛔ **OUTSTANDING** |
| P4 | **Independent NRFU / ATP acceptance criteria** + pre/post diff plan | `nrfu-validator` | ⛔ **OUTSTANDING** (proposer ≠ verifier — see §8) |
| P5 | **PSIRT / openVuln sweep → per-CVE fixed-version per model** (Phase B target) | research lane | ⛔ **OUTSTANDING** (feed lacks fixed-versions) |
| P6 | Out-of-band **console** access confirmed reachable for every target (recovery path if in-band mgmt is lost) | change engineer | ⛔ verify per device pre-window |
| P7 | Off-box backup of `running-config` + `startup-config` captured per target immediately pre-change | change engineer | per-step |
| P8 | Rollback image archived + md5 recorded (Phase B only); flash free-space confirmed | change engineer | per-wave |
| P9 | CAB approval + scheduled maintenance window per phase/wave | CAB / Change Manager | ⛔ pending |

---

## 4. Owners & RACI

| Role | Responsibility |
|---|---|
| **Change Executor** — Network Change Engineer (human) | Runs the steps in-window; the **only** party that touches a device |
| **Approver** — CAB / Change Manager | Approves the window and go/no-go |
| **Blast-radius** — `topology-reachability-analyst` | Per-wave reachability/SPOF report (P3) |
| **Acceptance** — `nrfu-validator` | Independent NRFU/ATP criteria + pre/post diff sign-off (P4) |
| **Monitoring** — NOC / Network Ops on-call | Watches reachability/telemetry during & after each step; declares rollback triggers |
| **Author** — `mop-change-author` | This artifact only; **does not execute, does not approve, does not merge** |

**Windowing summary** (calendar slots assigned by CAB):

| Phase | Change type | Window need | Indicative effort |
|---|---|---|---|
| A (interim mitigation) | mgmt-plane config, **no reload** | standard change window(s); batch by cohort | ~2–5 min/device incl. verify |
| B (upgrade) | image change **+ reload** | full maintenance window per wave | ~15–30 min/device incl. NRFU |
| C (version collect) | **read-only** collection (no device write) | change-awareness only; no reload | one collection pass |

---

## 5. Phase A — interim mitigation (close the exploited surface now)

**Goal:** remove/limit reachability to the actively-exploited services without waiting for the upgrade.
**Sequencing rule:** within every sub-phase, do the **`exposed` canaries first** (§2.1), validate, then
proceed by cohort batch. **No reload** is involved; impact is confined to the management plane.

### 5.1 — A1: Disable Smart Install on the IOS/IOS-XE cohort (96 devices)

*Roster: the IOS members of SSOT `smart_install_flagged` (96 of 151). Canary: `AAS13-BC-CR02R03-TCDOH`.*

**Pre-checks (capture evidence per device):**
```
show vstack config                     ! role (client/director) + Oper Mode (Enabled/Disabled)
show tcp brief | include 4786          ! is the Smart Install listener actually up?
show running-config | section vstack   ! current config to back up
show running-config | include transport input   ! confirm SSH mgmt is independent of this change
```
- If `show vstack config` shows this device is an **active director** or a client in a live zero-touch
  provisioning workflow, flag to the Approver before disabling (dependency check).
- Confirm OOB/console reachability (P6) and take the off-box config backup (P7).

**Change steps (in window, per device, exposed canary first):**
```
configure terminal
 no vstack
end
write memory
```

**Post-checks (operator confirmation the surface is closed):**
```
show vstack config              ! expect: Oper Mode Disabled / role none
show tcp brief | include 4786   ! expect: no listener on 4786
```
- Confirm the live SSH session is still up and the NMS still polls the device.
- **NRFU hook →** independent acceptance owned by `nrfu-validator` (§8) — not authored here.

**Rollback:** trigger = a dependent Smart Install/ZTP workflow breaks, or device management is lost after the
change. Action = console/OOB → `configure terminal` → `vstack` → `write memory`; confirm mgmt restored.
*Re-enabling restores the vulnerable surface — do so only to recover service, then escalate for an alternative.*

### 5.2 — A2: Disable or ACL-restrict the IOS-XE HTTP/HTTPS Web UI (8 IOS devices)

*Roster: the IOS members of SSOT `http_server_flagged` (8 of 63): `AAS13-BC-CR02R03-TCDOH`,
`AS01-BC-CA01RA13-CXDOH`, `AS01-BC-CAR11RD22`, `AS02-BC-CAR11RD22`, `DS17-BC-CA05R46-AJDOH`,
`DS18-BC-CA05R47-AJDOH`, `DS19-BC-CA11D03`, `DS20-BC-CA11D04` — cache of SSOT. Canaries: the two `exposed`
devices `AAS13-BC-CR02R03-TCDOH` and `AS01-BC-CA01RA13-CXDOH`.*

> ⚠ **`AS01-BC-CAR11RD22` and `AS02-BC-CAR11RD22` are `not_collected_version`** (blank `model`+`sw_version`;
> only `platform=ios` is asserted, uncorroborated) **and carry the highest lock-out consequence** (L3, stranded
> ≈527 each — blast-radius annex §2/§4). Do **not** default these two to Option A. **Verify the platform in the
> pre-check first**, and **prefer Option B (ACL-restrict, retains management)** over disable. Treat them as their
> own micro-wave with console standby (annex §2).

**Pre-checks (capture evidence per device):**
```
show ip http server status                  ! HTTP + secure-server Enabled/Disabled, port, active sessions
show running-config | include ip http        ! current server / secure-server / access-class / auth
show running-config | include restconf|netconf-yang   ! does RESTCONF/NETCONF ride this HTTP server?
```
- **Dependency check:** on IOS-XE, RESTCONF and some NMS (Prime / Catalyst Center) ride the HTTP(S) server.
  If a device depends on it, choose **Option B (restrict)** instead of **Option A (disable)**.
- Confirm OOB/console (P6), SSH independent path, and off-box backup (P7).

**Change steps — Option A (default: Web UI/HTTP not required):**
```
configure terminal
 no ip http server
 no ip http secure-server
end
write memory
```

**Change steps — Option B (HTTP mgmt required → restrict to a management host):**
```
configure terminal
 ip access-list standard ACL-HTTP-MGMT
  permit host <MGMT-HOST-IP>          ! <-- supplied by design/NRFU; do NOT invent
  deny   any log
 ip http access-class ipv4 ACL-HTTP-MGMT
 ip http secure-server                ! retained, now access-class-limited
 no ip http server                    ! drop cleartext HTTP even when HTTPS is retained
end
write memory
```

**Post-checks (operator confirmation the surface is closed):**
```
show ip http server status      ! Option A: HTTP + secure-server Disabled
                                ! Option B: secure-server Enabled WITH access-class ACL-HTTP-MGMT
```
- From a **non-management** host the Web UI (TCP 80/443) must now be refused; from the mgmt host (Option B)
  it must still respond. *Formal reachability pass/fail = NRFU, owned by `nrfu-validator` (§8).*
- **NRFU hook →** `nrfu-validator` (independent).

**Rollback:** trigger = loss of RESTCONF / Catalyst Center / Prime management, NMS webhook failure, or the
mgmt host cannot reach after the ACL. Action = console/OOB → re-enable `ip http server` / `ip http
secure-server` or correct/remove `ip http access-class` → `write memory`; confirm mgmt restored.

### 5.3 — A3: NX-OS / FEX carve-out (55 devices) — verify-only, **no IOS commands**

*Roster: the NX-OS members of SSOT `smart_install_flagged` **and** `http_server_flagged` (the same 55 Nexus
N5K/N6K/N9K + FEX). These appear in the engine's config-screening surface groups, but the KEV CVEs do **not**
apply to NX-OS.*

**Coverage-honest rationale:** CVE-2018-0171 targets the **Catalyst IOS/IOS-XE** Smart Install client
(`vstack`, TCP/4786) — NX-OS has no `vstack` CLI and does not run that client. CVE-2023-20198/20273 target the
**IOS-XE** `web_ui` — NX-OS uses NX-API / `feature http-server`, a different surface. **FEX have no independent
control plane** — any action is on the parent Nexus. Therefore this cohort receives **verification, not the
IOS remediation.**

**Verify-only steps (read-only — no config change for the KEV CVEs):**
```
show sockets connection | include 4786    ! expect: NO Smart Install listener on NX-OS
show feature | include nxapi|http         ! NX-API / http-server feature state
show nxapi                                ! NX-API listener, port, sandbox enabled?
```

**Optional platform-appropriate hardening (OUT OF KEV SCOPE — track as a separate, lower-priority change,
not part of this actively-exploited-CVE MOP):** if NX-API / `feature http-server` is enabled and not required,
propose `no feature nxapi` / `no feature http-server`, or restrict NX-API to the management VRF / an ACL — via
its **own** MOP with its own pre/post/rollback. **No `vstack` or `ip http server` command is issued to any
device in this cohort.**

**Rollback:** none for the verify-only steps (read-only). Any optional NX-OS hardening carries its own
rollback in its own MOP.

---

## 6. Phase B — durable upgrade (phased; the fix that survives)

**Goal:** move end-of-maintenance devices onto a PSIRT-fixed release so the surface is closed by the software,
not just masked by config. **Requires a reload → full maintenance window per wave.** Gated on P5 (PSIRT
fixed-version) and P3 (per-wave reachability).

> **Target release = "PSIRT-fixed release (TBD)".** The KEV feed provides the CVE + product but **not** the
> Cisco-fixed release. The precise *"upgrade model X to release Y"* target is produced by the per-CVE **Cisco
> PSIRT / openVuln** sweep (P5). **No version is fabricated in this MOP.** Waves are grouped by **model × train**
> so each cohort maps to exactly one target image once P5 lands.

### 6.1 — Wave 1: the 21 priority devices (`priority21_eol_and_exposed`) — do first

EOL train **and** an exposed exploited surface. Roster = SSOT key `priority21_eol_and_exposed` (see Appendix A,
a cache of SSOT). Image cohorts:

| Model | Current train | Devices |
|---|---|---:|
| WS-C3850-48P | IOS XE 3.x 03.06.06E | 5 |
| WS-C3850-48T | IOS XE 3.x 03.06.06E | 5 |
| WS-C4500X-32 | IOS XE 3.x (03.08.08.E / 03.11.03a.E / 03.11.04.E) | 5 |
| WS-C4500X-16 | IOS XE 3.x (03.08.07.E / 03.11.04.E / 03.11.07.E) | 4 |
| N6K-C6001-64P | NX-OS 6.x 6.0(2)N2(3) | 2 |

### 6.2 — Waves 2+: the remaining 33 `replace_upgrade_train` devices (54 − 21)

All IOS XE 3.x. Image cohorts (schedule as separate windows by cohort/site):

| Model | Current train | Devices |
|---|---|---:|
| WS-C3850-48P | IOS XE 3.x 03.06.06E | 16 |
| WS-C3850-48T | IOS XE 3.x 03.06.06E | 12 |
| WS-C4500X-32 | IOS XE 3.x 03.06.06.E | 3 |
| WS-C4500X-32 | IOS XE 3.x 03.06.03.E | 2 |

### 6.3 — Per-device upgrade procedure (applies to every wave)

**Pre-checks / preconditions:**
- P5 target image confirmed for this model+CVE; P3 reachability report reviewed for the wave.
- Capture rollback baseline: `show version`, `show boot`, `dir flash:` / `dir bootflash:` (record the
  **current image + its md5** as the rollback image); back up `running-config` + `startup-config` off-box.
- Confirm flash/bootflash free space for the new image (`show file systems`).
- For **stacks / VSS / redundant pairs**, confirm the partner carries load, or schedule to avoid a dual outage.
- Capture the **pre-upgrade NRFU baseline** (routing adjacencies, interface states, CPU/mem) — criteria owned
  by `nrfu-validator` (§8).

**Change steps (in window):**
```
! 1) Stage image OUT of window, then verify integrity:
copy scp: flash:                         ! (or tftp/ftp/usb per site)
verify /md5 flash:<new-image>            ! MUST equal the PSIRT-published md5

! 2) IOS / IOS-XE: point boot var at the new image
configure terminal
 no boot system
 boot system flash:<new-image>
end
write memory
reload                                    ! in-window

! 2') NX-OS (N6K-C6001): use the install workflow instead
!   copy scp: bootflash: ; then:  install all nxos bootflash:<new-image>
```

**Post-checks (operator confirmation):**
```
show version                    ! expect: running release == PSIRT-fixed target
show vstack config              ! expect: Smart Install still disabled (Phase A persisted)
show ip http server status      ! expect: Web UI still disabled/restricted (Phase A persisted)
```
- **NRFU hook →** independent post-upgrade acceptance owned by `nrfu-validator` (routing/interfaces/features
  vs. the pre-upgrade baseline) (§8).

**Rollback:** triggers = image md5 mismatch; device boot-loops / fails to boot the new image; post-upgrade
NRFU fails (adjacency/interface/feature regression); performance degradation beyond the agreed threshold; or
the new image does not actually clear the surface. Action = set boot var back to the **archived prior image**
→ `reload` → restore the saved config if it changed → confirm the device is back on the prior release with the
NRFU baseline restored. (NX-OS: `install all` back to the prior image.)

---

## 7. Phase C — close the coverage gap (56 `not_collected_version`)

**Goal:** collect a running version for the 56 devices with a blank `sw_version` so their KEV exposure can be
**assessed**. **These are not remediable and are not "clean" until assessed.** Roster = SSOT key
`not_collected_version`.

**This is a read-only collection — no device write, no reload.** Per the engine guardrail, a live read-only
collection runs **only when explicitly approved** (it SSHes to gear); it does not auto-run.

**Proposed steps:**
1. Build a scoped devices-file for the 56 hosts (derived from the SSOT key — not a hand-maintained copy).
2. Run a read-only collection of `show version` (SSH `show`-text via `cisco-assess` targeted at the subset;
   for any controller-fabric members use the read-only `python -m cisco_toolkit.rest_collect` GET-only path).
3. Re-run the finding reproduce command against the refreshed snapshot to re-derive exposure with versions
   populated:
   ```
   python -m cisco_toolkit.intel_feed --dir docs/intel <refreshed>.snapshot.json
   ```
4. Feed any newly-classified exposed/EOL devices back into Phase A (interim mitigation) and Phase B (upgrade)
   scoping.

**Rollback:** none — read-only. If collection cannot reach a device, record it as still-`NOT_COLLECTED`
(explicitly **not** assumed clean).

---

## 8. Verification ownership — proposer ≠ verifier

The **operator post-checks** in each phase confirm *"did my change take effect on this box"* (part of the
change step). They are **not** the acceptance gate. The formal **NRFU / ATP acceptance criteria** — the
independent pass/fail that a wave is signed off on, plus the pre/post diff — are **owned by `nrfu-validator`**
and are **deliberately not authored in this MOP**. This preserves the proposer ≠ verifier separation:

- `nrfu-validator` defines and runs: surface-closed reachability proof (Phase A), post-upgrade
  routing/interface/feature acceptance vs. baseline (Phase B), and the `--compare OLD NEW` snapshot diff.
- `topology-reachability-analyst` supplies the per-wave blast-radius / SPOF report (P3).
- CAB gives go/no-go using both, plus this MOP.

---

## 9. Rollback matrix

Every forward step maps to a trigger and a rollback action. Recovery is always available via the **OOB console**
(P6) even if in-band management is lost.

| Step | Forward action | Rollback **trigger** | Rollback action | Owner |
|---|---|---|---|---|
| **A1** Smart Install (96 IOS) | `no vstack` + `write memory` | Dependent Smart Install/ZTP workflow breaks, **or** device management lost | Console → `vstack` → `write memory`; confirm mgmt; escalate for alternative | Change Executor |
| **A2** HTTP Web UI (8 IOS) — Option A | `no ip http server` / `no ip http secure-server` | RESTCONF / Catalyst Center / Prime / NMS management lost | Console → re-enable `ip http server` / `ip http secure-server` → `write memory` | Change Executor |
| **A2** HTTP Web UI (8 IOS) — Option B | `ip http access-class ACL-HTTP-MGMT` (restrict) | Mgmt host cannot reach the Web UI after the ACL | Console → correct/remove `ip http access-class`; re-validate mgmt reach | Change Executor |
| **A3** NX-OS/FEX (55) | Verify-only (read) | n/a (no change) | n/a | Change Executor |
| **B** Upgrade — image stage | `copy` + `verify /md5` | md5 ≠ PSIRT-published md5 | Do **not** boot; re-stage the image; abort wave if it recurs | Change Executor |
| **B** Upgrade — boot/reload | set boot var → `reload` (IOS) / `install all` (NX-OS) | Boot-loop / fails to boot new image | Set boot var to **archived prior image** → reload → confirm prior release | Change Executor |
| **B** Upgrade — post | run on new release | Post-upgrade **NRFU fails** (adjacency/interface/feature regression) | Roll back to prior image + restore saved config; re-run NRFU baseline | Change Executor + `nrfu-validator` |
| **B** Upgrade — post | run on new release | **Performance degradation** beyond agreed threshold (CPU/mem/convergence) | Roll back to prior image; capture diagnostics for PIR | Change Executor + NOC |
| **B** Upgrade — post | run on new release | New image does **not** close the surface | Roll back; escalate to research lane (wrong PSIRT target) | Change Executor |
| **C** Version collect (56) | read-only `show version` | Collection unreachable | Record host as still `NOT_COLLECTED` (**not** assumed clean) | Change Executor |

**Global rollback triggers (any phase, declared by NOC / on-call):** loss of routing/reachability to a
production segment, loss of device management with no OOB recovery in progress, or any customer-impacting
outage → **halt the wave, roll back the last step, convene the CAB bridge.**

---

## 10. Post-implementation & handoff

1. After each phase/wave, re-run the reproduce command against a fresh snapshot and confirm the flagged counts
   drop as expected (Phase A → `smart-install`/`http-server` surfaces closed on the IOS cohorts; Phase B →
   affected models off the Replace/Upgrade train; Phase C → the 56 populated).
2. Produce the cutover diff for the audit trail: `cisco-assess --compare <pre>.snapshot.json
   <post>.snapshot.json --output KEV-Remediation-Diff.xlsx` → route to `release-captain`.
3. `nrfu-validator` signs off acceptance (§8); PIR captures any rollback events and threshold breaches.

## 11. Outstanding items / next intel (blockers for CAB)

- **P5 — PSIRT/openVuln sweep** → attach per-CVE fixed-versions per model, converting Phase B "TBD" targets to
  device-precise releases. *Blocks Phase B execution.*
- **P3 — per-wave blast-radius / reachability report** from `topology-reachability-analyst`. *Blocks CAB.*
- **P4 — independent NRFU/ATP acceptance criteria** from `nrfu-validator`. *Blocks CAB sign-off.*
- **P6 — per-device OOB console verification** and **P7/P8 backups** before each window.

---

## Appendix A — Wave 1 roster (cache of SSOT `priority21_eol_and_exposed`)

> Reproduced from `kev-exposure-2026-07-07-devices.json` key `priority21_eol_and_exposed` for reviewer
> convenience. The JSON is the source of truth; if these differ, the JSON wins.

`10GSW01-BC-CA11F17`, `10GSW02-BC-CA11F18`, `ACS01-BC-CA11G20-PGDOH`, `AS-BC-VSS-CAR07R07-AJDOH`,
`AS01-BC-CA01RA13-CXDOH`, `AS20-BC-TR12SatR2-BCDOH`, `AS20-MGM-CA11B29-Stack`, `AS21-BC-TE421R01`,
`AS21-MGM-TE421R02`, `AS22-BC-CA04R2-BCDOH`, `AS22-BC-TE421R01`, `AS24-BC-TR11SatR2-Stack`,
`AS25-BC-TR11SatR2-BCDOH`, `AS26-BC-TR11SatR2-BCDOH`, `DS-VSS-AVID-CAR05-R37-AJDOH`,
`DS-VSS-BC-CAR6R1-CAR11RF16-DOH`, `DS-VSS-CA05R27CA11F17-SW`, `DS-VSS-CAR3-R13-ARDOH`,
`DS01-DC-INVESTIGATIVE-AJSS-DCDOH`, `DS21-BC-CA11G17`, `SW01-BC-CAR11RF16` — **21 devices**.

*Rosters for A1 (96 IOS smart-install), A2 (8 IOS http), A3 (55 NX-OS), Waves 2+ (33), and Phase C (56) are the
correspondingly-filtered members of the SSOT JSON — not duplicated here to avoid a divergent second copy.*
