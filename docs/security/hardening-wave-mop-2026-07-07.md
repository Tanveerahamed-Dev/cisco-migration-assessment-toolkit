# Hardening Wave — Remediation MOP + Rollback (config-plane, no-reload) — 2026-07-07

> ## ⛔ PROPOSE-ONLY — NOT EXECUTION-READY TODAY
> This is a **reviewable candidate artifact** authored by the mop-change-author agent. It is a
> **human-owned change (a PR)**. The agent that wrote it **does not and cannot execute it**: no device
> writes, no `git push`, no merge, no self-approval. It becomes executable **only** after all three of:
> **(a)** the SNMPv3 credential scheme is supplied by the customer (§2, H3); **(b)** NMS-first SNMPv3
> coordination is confirmed (§H3 sequencing); and **(c)** CAB approval, following an **independent
> dry-run** by the nrfu-validator / topology-reachability-analyst. Until then every `<placeholder>`
> below is unfilled by design. **Proposer ≠ verifier:** the NRFU/ATP acceptance suite is authored
> *separately* by the nrfu-validator (§NRFU hand-off), not here.

---

## 0. Document control & provenance

| Field | Value |
|---|---|
| MOP ID | HARDEN-WAVE-2026-07-07 (propose-only) |
| Change class | Config-plane, **no reload**, fleet-wide risk reduction (assessment remediation **action #2**) |
| Gate position | Assess → *(approved)* → **MOP + rollback (this doc)** → *(dry-run + CAB)* → NRFU → cutover → PIR |
| Author | mop-change-author (delivery engineer) — authors only; never executes |
| Drives from | `docs/assessment/config-hardening-2026-07-07.md` (finding) + `docs/assessment/config-hardening-devices.json` (device-level gap SSOT) |
| State evidence | `Migration_Assessment_AUTOFILLED_20260613_063201.snapshot.json` — `security`, `acls`, `devices[].platform` |
| Fleet counts owner | `cisco_toolkit.ssot.canonical_facts(snap)` → 303 total / **253 assessable** / 50 not-collected |
| Status | **PROPOSE-ONLY.** Not approved, not scheduled, not executable (see banner). |

**Why a markdown MOP and not the engine DOCX.** The engine's `write_mop_docx` (`cisco_toolkit/mop.py`)
keys off migration **move-groups / waves** in `snap['move_groups']`. This hardening wave is a
**config-plane security remediation**, not a topology move-group, so it is authored here in the engine's
MOP house style (pre-checks → ordered steps → post-checks → **explicit quantified rollback triggers** →
rollback procedure → RACI → per-window gates) rather than emitted by `write_mop_docx`.

---

## 1. Scope, cohorts & coverage-honest carve-outs

**Scope:** the **253 config-assessable** devices. The **50 not-collected devices are excluded — not
assessed, not "clean."** This wave is three coordinated, no-reload sub-changes plus one review, all
config-plane:

- **H1 — VTY line hardening** (247 devices)
- **H2 — local credential hardening** (73 weak-user-pw High + 64 password-encryption + 2 weak-enable)
- **H3 — SNMPv2c → SNMPv3** (106 devices)
- **ACL review** (8 devices holding 32 `permit any→any` rules) — a review, **not** a bulk change.

### 1.1 Every count reconciles to the SSOT — and partitions by platform

The device lists in `config-hardening-devices.json` were matched host-by-host against
`devices[].platform` in the snapshot. **All hosts matched (zero unmatched).** The remediation **syntax is
platform-dependent**, so each SSOT count is partitioned into the cohort that actually receives each command:

| Sub-change | SSOT total | IOS | NX-OS switch | "Fex"-named (resolve first) | Notes |
|---|---:|---:|---:|---:|---|
| **H1** vty-hardening | **247** | 192 | 44 | 11 | NX-OS VTY control differs from IOS (see 1.2). |
| **H2** weak-user-pw (High) | **73** | 18 | 44 | 11 | IOS `secret` syntax ≠ NX-OS (see 1.2). |
| **H2** password-encryption | **64** | 9 | 44 | 11 | `service password-encryption` **applies to the 9 IOS only** — it is **not an NX-OS command** (see 1.2). |
| **H2** weak-enable | **2** | 2 | 0 | 0 | Folded into H2 (`enable secret`). IOS-only, consistent — NX-OS has no `enable secret`. |
| **H3** insecure-snmp | **106** | 87 | 19 | 0 | No Fex; SNMPv3 syntax differs IOS vs NX-OS. |
| **ACL** permit-any | **8** (32 rules) | 8 | 0 | 0 | All IOS; 5 of 8 are `DS-VSS-*` core/dist pairs (broad permits often legitimate). |

*The same 55 NX-OS devices trip H1, H2-weak-user-pw and H2-password-encryption — one Nexus cohort viewed
three ways, not three independent populations.*

### 1.2 Coverage-honesty carve-outs (Law 3 — do not silently mis-apply IOS commands to NX-OS)

1. **`service password-encryption` is IOS-only.** It **does not exist on NX-OS** (NX-OS stores local
   secrets Type-5/encrypted by default). Of the 64 "password-encryption unset" devices, **55 are NX-OS**,
   where the check is measuring an **IOS token that cannot exist** — a check-applicability artifact, **not
   a confirmed, fixable-by-this-command gap.** ⇒ H2's `service password-encryption` step targets the
   **9 IOS devices only.** The NX-OS password-storage posture is a **separate question for
   security-design / dry-run**, not something this MOP "fixes" with an IOS command.

2. **User-hardening syntax differs.** `username X algorithm-type sha256 secret …` (Type-8/9) is IOS-XE
   syntax. NX-OS uses `username X password [5 <hash>] role <role>` (Type-5, role-based) and has **no
   `algorithm-type`**. ⇒ H2 user migration is written per-platform; the exact **NX-OS credential scheme is
   a security-design input**, deferred (parameterized), not fabricated.

3. **VTY control differs.** `transport input ssh` is IOS. On NX-OS telnet is a **feature** (`feature
   telnet`, off by default) and SSH is `feature ssh`; `line vty` supports `exec-timeout <min>` /
   `access-class … in` / `session-limit`, and Nexus mgmt is often via a **mgmt VRF + CoPP**. ⇒ H1 is
   written per-platform; **exact NX-OS VTY/line syntax must be validated per NX-OS version in dry-run**
   (N5K/N6K/N9K differ) before it is trusted.

4. **The 11 "Fex"-named entries are a RESOLVE-FIRST cohort, not a silent exclude.** They carry model
   `N5K-C56128P` (a Nexus **5600-class switch** model) yet are named `Fex 100 … Fex128 / FEX CAR11 RACK
   F15`. Manageability is **ambiguous in the evidence**: a *true* fabric extender has **no independent
   control plane** (no VTY, no local user DB, no SSH — you configure it at the **parent** Nexus), whereas
   a 5600 switch informally named "Fex" **is** directly configurable. Supporting-but-not-conclusive signal:
   these 11 are **absent from the SNMP gap list**, consistent with (but not proof of) no independent mgmt
   plane. ⇒ **Pre-check MUST resolve each one** (confirm an SSH endpoint + `line vty` + local users, or
   `show fex` on the parent) **before** any H1/H2 command is pushed to that name. **Never push config to a
   name you cannot SSH.**

5. **Screening, not a pen-test.** The `security` block is **CIS-aligned screening from parsed config**; a
   `fail` means the hardening token was **not observed** — a strong but not absolute signal on parsed data.
   The 32 `permit any→any` count is **structural breadth, not intent** — a **review list**, not 32
   confirmed misconfigurations.

---

## 2. Prerequisites & gating inputs (the MOP cannot run without these)

**Hard gate — all of these are unfilled today; this MOP is NOT executable until they exist:**

| # | Required input | Owner | Blocks | Why it is not fabricated here |
|---|---|---|---|---|
| **(a)** | **SNMPv3 scheme** — v3 user / group / view names, auth-proto (SHA/SHA-256), priv-proto (AES-128/256), passphrase policy | Customer security-design | **H3** | Credential-bearing customer design input → `<SNMPv3-scheme TBD>`. |
| **(b)** | **NMS-first coordination** — NMS/poller reconfigured for SNMPv3 and **confirmed polling per device** | Customer monitoring/NMS team | **H3** | Sequencing dependency; monitoring goes dark if inverted (§H3). |
| **(c)** | **CAB approval** after independent dry-run | Customer CAB + nrfu-validator / topology-reachability-analyst | **all** | Governance gate; proposer ≠ verifier. |
| (d) | **`<mgmt-ACL>` contents** — the permitted management source subnets (the ACL that `access-class` enforces) | Customer security-design | **H1** | Wrong contents = fleet mgmt lockout → parameterized `<mgmt-ACL>`. |
| (e) | **Per-policy secrets** — new local-user & enable secrets (IOS Type-8/9; NX-OS Type-5 scheme) | Customer security-design | **H2** | Credential input → `<per-policy>`; never invented. |
| (f) | **OOB / console reachability confirmed** to every in-scope device + **off-box golden config backup** | Customer ops | **all** | Rollback path for lockout classes (H1/H2). |

> Items **(a) (b) (c)** are the three the task calls out explicitly as blocking execution. (d)–(f) are the
> additional design/operational inputs the same three sub-changes require. **None are filled in this
> propose-only artifact.**

---

## 3. Global pre-checks (once, before the first window — evidence capture)

Run read-only, archive output off-box as the rollback baseline (the "golden" per device):

1. **Golden config** per in-scope device: `show running-config` (IOS) / `show running-config all` (NX-OS) → off-box.
2. **Reachability & OOB:** confirm SSH management reachability **and** an independent OOB/console path to every device.
3. **Platform confirm:** `show version` — reconcile platform (IOS vs NX-OS) against the cohort table (1.1).
4. **"Fex" resolution (the 11):** for each `Fex*`/`FEX*` name, determine directly-manageable switch vs.
   parent-managed extender (§1.2 #4). Record disposition **before** they enter any H1/H2 batch.
5. **Existing state snapshot** for each sub-change's pre-check (§H1.pre / §H2.pre / §H3.pre).
6. **Dry-run validation PASSED** (nrfu-validator / topology-reachability-analyst) — blast-radius on the
   mgmt-plane and SNMP-polling paths reviewed. **No window opens without this.**

---

## 4. RACI & war-room roles (AS change model)

| Activity | Responsible | Accountable | Notes |
|---|---|---|---|
| MOP prep, per-platform config staging, pre/post checks | Delivery engineer (author) | Customer network owner | Reviewed & approved before CAB |
| Design inputs (a)/(d)/(e) — SNMPv3 scheme, mgmt-ACL, secrets | Customer security-design | Customer network owner | This MOP parameterizes them |
| NMS SNMPv3 reconfigure + per-device polling confirm (b) | Customer monitoring/NMS team | Customer network owner | H3 pre-step & gate |
| Change approval & scheduling (c) | Customer change manager | CAB | Standard CAB process |
| In-window execution (exactly as written) | Customer ops / implementing engineer | Change owner | Delivery engineer advises only |
| **Go/no-go & rollback decision** | **Change owner (network owner)** | Change owner | **Only person who calls a rollback** |
| Post-check evidence + sign-off | Verifier (validation lead) | Change owner | Independent of the executor |
| Independent NRFU/ATP acceptance | **nrfu-validator** | Customer network owner | **Separate author — see NRFU hand-off** |

**War-room roles:** Change owner (go/no-go) · Executor (runs steps) · **Verifier (independent of executor)**
· Escalation/bridge lead. **T-minus cadence:** T-1wk (CAB approved, MOP+rollback distributed) · T-1d
(readiness re-confirmed, inputs (a)/(d)/(e) present) · T-1h (war room open, OOB + golden backups
confirmed) · T-0 (start) · per-step gate called on the bridge · T-plus (window closed **PROCEEDED** or
**ROLLED-BACK**, evidence archived). **Escalation:** L1 war room → L2 engineering → L3 Cisco TAC
(pre-open an SR for the highest-risk ring) → Rollback authority = change owner.

---

## 5. Staged rollout model & per-window gates

A 247-device fleet-wide change is **staged, never big-bang.** Order rings **least-critical → most-critical**
so the highest-blast-radius devices go last with the most evidence behind them.

| Ring | Population (selection criteria — confirm exact members with customer) | Gate to advance |
|---|---|---|
| **Pilot / canary** | A small representative set: **both platforms**, **non-core**, OOB-reachable, from the gap lists (e.g. an IOS access switch + one NX-OS access switch). *Candidates, not a mandate.* | **G1:** all pilot post-checks pass, **zero** rollback triggers fired, monitoring intact 24 h. |
| **Ring 1 — access** | Access-layer `AS*` / `AAS*` / `ACS*` devices. | **G2:** ring post-checks pass; no trigger stands. |
| **Ring 2 — distribution / core / VSS** | `DS*`, `CS*`, `DS-VSS-*`, `AS-BC-VSS-*` — highest blast radius, done **last**. | **G3:** post-checks pass; PIR-ready. |

**Per-window go/no-go gate (G0, every window):** CAB approved · inputs (a)(d)(e) delivered · NMS team on
bridge (for H3) · OOB/console confirmed · golden config backed up · dry-run PASSED · rollback owner
identified and rollback walked. **If any is false, the window does not open.**

**In-window sub-change order (per device):** **H2 → H3 → H1.** Rationale: establish **known-good
credentials first** (H2, verified in a second session), then the **additive-then-remove** SNMP change
(H3, NMS-gated), and apply the **highest-lockout-risk** step **last** (H1 `access-class`, with a reserved
session + OOB fallback).

---

## H1 — VTY line hardening (247: 192 IOS + 44 NX-OS + 11 resolve-first)

**Goal:** on every VTY line — `transport input ssh` (no telnet), `exec-timeout <N> 0` (N>0), and
`access-class <mgmt-ACL> in`. **Highest-lockout-risk sub-change** (a wrong `<mgmt-ACL>` can lock out all
management). Requires input **(d) `<mgmt-ACL>`** and **(f) OOB**.

### H1.pre — pre-checks (per device)
- `show run | section line vty` — enumerate the **actual** vty ranges (may be `0 4` + `5 15`, up to `0 98`); capture current `transport input` / `exec-timeout` / `access-class`.
- `show ip http server status` (IOS) — **confirm** HTTP/HTTPS server state. *If enabled and not required,
  active Web-UI remediation is owned by the **KEV wave**, not here* (avoid double-owning the KEV Web-UI surface).
- Confirm the connecting mgmt source is **inside** `<mgmt-ACL>`; confirm **OOB/console** is up.
- **NX-OS:** `show feature | include telnet|ssh`; confirm SSH reachable; note mgmt VRF.

### H1.steps — ordered (keep TWO sessions open throughout)

**IOS (192):**
```
! 1) Define the mgmt ACL FIRST (contents = input (d), per-policy)
ip access-list standard <mgmt-ACL>
 permit <mgmt-subnet-1> <wildcard>
 permit <mgmt-subnet-2> <wildcard>
 ! implicit deny any
! 2) Apply to EACH vty range found in H1.pre (example ranges shown)
line vty 0 4
 transport input ssh
 exec-timeout <N> 0            ! N>0 per policy (e.g. 10 0); NEVER 0 0 (disables timeout)
line vty 5 15
 transport input ssh
 exec-timeout <N> 0
! 3) access-class LAST, from a reserved session, OOB confirmed:
line vty 0 4
 access-class <mgmt-ACL> in    ! add 'vrf-also' if mgmt arrives over a VRF, else VRF mgmt is NOT filtered/allowed as intended
line vty 5 15
 access-class <mgmt-ACL> in
```
**NX-OS switch (44) — validate exact syntax per NX-OS version in dry-run:**
```
no feature telnet             ! only if telnet enabled and not required
feature ssh
ip access-list <mgmt-ACL>
 permit ip <mgmt-subnet> any
line vty
 exec-timeout <N>             ! NX-OS = minutes only (no trailing 0)
 session-limit <n>
 access-class <mgmt-ACL> in
```
**"Fex" 11:** **do not run** until §3.4 resolution says the name is a directly-manageable switch;
otherwise harden at the **parent** Nexus.

### H1.post — post-checks
- `show run | section line vty` shows **all three** (`transport input ssh`, `exec-timeout <N> 0`, `access-class <mgmt-ACL> in`) on **every** range.
- **Open a NEW SSH session from an authorized mgmt subnet — it must succeed** (proves the ACL admits legitimate mgmt) **before** closing the reserved session.
- NMS/automation still reaches the device.

### H1.rollback
- **Trigger:** a new SSH from an authorized mgmt subnet is **refused**, OR the live session is lost and cannot reconnect, OR NMS/automation loses device access.
- **Action:** from OOB/console, `no access-class <mgmt-ACL> in` on the affected vty ranges (and restore prior `transport input` if a required telnet path broke). Restore golden if needed.
- **Owner:** change owner declares; executor runs.

---

## H2 — Local credential hardening (73 weak-user-pw High + 64 password-encryption + 2 weak-enable)

**Goal:** IOS → `service password-encryption`, migrate local users to **Type-8/9** `secret`, set Type-8/9
**enable secret**. NX-OS → per-platform Type-5/role scheme (§1.2). Requires input **(e) `<per-policy>`**
secrets. **Lockout risk:** a fat-fingered new secret on the only account. **Golden rule: verify the NEW
credential in a SECOND session BEFORE removing the old and before closing the first.**

### H2.pre — pre-checks
- `show run | include ^username|service password-encryption|enable ` (IOS) / `show run | include ^username` (NX-OS) — capture current local users, secret types, enable-secret presence.
- Confirm whether the device uses **centralized AAA** (TACACS/RADIUS) with local as **break-glass** — if so, the local account is the fallback and must remain known-good.
- Confirm **OOB/console** available.

### H2.steps — ordered

**IOS (18 weak-user-pw + 9 password-encryption + 2 weak-enable):**
```
service password-encryption                                   ! IOS only; encrypts Type-0/7 at rest
username <user> algorithm-type sha256 secret <per-policy>     ! Type-8 (PBKDF2); or 'algorithm-type scrypt' = Type-9
enable  algorithm-type sha256 secret <per-policy>             ! Type-8 enable secret
! --- VERIFY new credential in a SECOND session (login + enable) BEFORE next line ---
no username <old-legacy-Type7-or-Type0-form>                  ! remove legacy entry ONLY after verify
```
**NX-OS switch (44) — exact scheme is a security-design input (e), validate in dry-run:**
```
! NX-OS: no 'service password-encryption'; local secrets are Type-5 by default
username <user> password <per-policy> role <role>            ! auto-hashes Type-5
! or pre-hashed: username <user> password 5 <per-policy-hash> role <role>
! --- VERIFY login in a SECOND session BEFORE removing any prior account ---
```
**"Fex" 11:** resolve-first (§1.2 #4) before any `username` push.

### H2.post — post-checks
- `show run | include ^username|^enable secret` — new users show **Type-8/9** (IOS) / **Type-5** (NX-OS); no residual Type-0/7 on IOS; `service password-encryption` present (IOS cohort).
- **Second-session login with the new credential succeeded** (recorded) — this is the gate before removing the old account.

### H2.rollback
- **Trigger:** login with the **new** credential **fails** in the verification session (or `enable` with new secret fails).
- **Action:** restore the prior `username` / `enable secret` lines from the golden config (do **not** remove the old account until the new one is verified — so the old path is still live).
- **Owner:** executor; change owner confirms.

---

## H3 — SNMPv2c → SNMPv3 (106: 87 IOS + 19 NX-OS)

**Goal:** remove `snmp-server community <v2c>`; add SNMPv3 group/user/view with **auth + priv**. Requires
inputs **(a) `<SNMPv3-scheme TBD>`** and **(b) NMS-first coordination**.

### ⚠️ CRITICAL SEQUENCING (from the QA) — additive-then-remove, NMS-gated per device
> The NMS/poller **MUST be reconfigured for SNMPv3 and confirmed polling** **BEFORE** the v2c string is
> removed **on each device**, or monitoring goes dark. This is an **explicit gated pre-step**, not a
> best-effort ordering. **Never remove v2c on a device until that device is confirmed polling over v3.**

### H3.pre — pre-checks
- **Pre-step (NMS team, gate G-H3a):** reconfigure the NMS/poller for SNMPv3 using scheme (a). **Do not touch any device SNMP until this is done.** If the NMS cannot be prepared → **abort H3** (leave v2c intact).
- Per device: `show run | include snmp-server` — capture the **exact** current `community` string(s) (the real string comes from the device's own config at execution time — **not guessed here**).

### H3.steps — ordered, PER DEVICE

**IOS (87):**
```
! 1) ADD SNMPv3 (additive — v2c still live, monitoring intact)
snmp-server view  <view>  iso included
snmp-server group <group> v3 priv read <view> [access <mgmt-ACL>]
snmp-server user  <user>  <group> v3 auth <sha|sha256> <auth-pass> priv <aes 128|256> <priv-pass>
! 2) GATE (G-H3b): confirm the NMS is polling THIS device over v3 (walk succeeds, data flowing)
! 3) ONLY IF gate passes — remove v2c (exact string from H3.pre):
no snmp-server community <v2c-string> [RO|RW]
```
**NX-OS (19) — validate exact syntax in dry-run:**
```
snmp-server user <user> <role> auth sha <auth-pass> priv aes-128 <priv-pass>
! GATE: confirm NMS polling this device over v3
no snmp-server community <v2c-string> group <group>
```

### H3.post — post-checks
- `show run | include snmp-server community` returns **no v2c** on the device.
- `show snmp user` (IOS) / `show snmp user` (NX-OS) shows the v3 user with auth+priv.
- **NMS confirms continued polling over v3** for the device (the same signal that opened gate G-H3b).

### H3.rollback
- **Trigger (pre-removal):** NMS **not** confirmed polling over v3 within the gate window → **do NOT remove v2c**; device stays **dual-stack**; investigate.
- **Trigger (post-removal):** monitoring for the device **goes dark** after v2c removal.
- **Action:** immediately re-add `snmp-server community <v2c-string> RO` (from golden) to restore polling; then diagnose v3 offline.
- **Owner:** NMS team detects; executor re-adds; change owner confirms.

---

## ACL review — 8 devices / 32 `permit any→any` rules (REVIEW, not a bulk change)

**This is a design review, not an executed change.** For each device, enumerate the broad ACEs and give
each a disposition; **each `permit any→any` is justified or scoped by design** — no automation, no bulk edit.

- **Devices (all IOS, from SSOT):** `ACS01-BC-CA11G01-ENDOH`, `ACS01-BC-CA11G20-PGDOH`,
  `AS-BC-VSS-CAR07R07-AJDOH`, `DS-VSS-AVID-CAR05-R37-AJDOH`, `DS-VSS-BC-CAR6R1-CAR11RF16-DOH`,
  `DS-VSS-CA05R27CA11F17-SW`, `DS-VSS-CAR3-R13-ARDOH`, `DS21-BC-CA11G17`.
- **Note (coverage-honest):** 5 of 8 are `DS-VSS-*` / `AS-BC-VSS-*` **core/distribution VSS pairs**, where a
  broad permit is **often a legitimate transit/infra rule** — structural breadth, not confirmed misconfig.
- **Procedure (per device):** `show access-lists` → for each `permit any→any` ACE record
  **{ACL, sequence, context}** → disposition = **justify** (document intent) | **scope** (replace with
  required src/dst/ports) | **remove**. Output a per-ACE disposition table → hand to **design-author**.
  Any scoping that results becomes **its own change** with its own MOP + rollback (out of scope here).

---

## Consolidated rollback matrix (step → trigger → action → owner)

| Step | Explicit trigger (boolean) | Rollback action | Owner |
|---|---|---|---|
| **Global** any step | Device unreachable / unexpected reload / crash | Restore golden config from OOB/console; open/attach Cisco TAC SR | Change owner |
| H1-1 define `<mgmt-ACL>` | (additive — no traffic impact until referenced) | `no ip access-list … <mgmt-ACL>` | Executor |
| H1-2 `transport input ssh` | A **required** telnet mgmt/automation path breaks | Restore prior `transport input …` from golden | Executor |
| H1-3 `exec-timeout <N> 0` | (idle-timeout only; no session impact) | Restore prior `exec-timeout` | Executor |
| **H1-4 `access-class … in`** | New SSH from an authorized mgmt subnet **refused**, OR live session lost & no reconnect, OR NMS/automation loses access | **From OOB/console:** `no access-class <mgmt-ACL> in` on affected vty; restore golden | **Change owner** declares; executor runs |
| H2-1 `service password-encryption` (IOS) | (at-rest only) | `no service password-encryption` (already-encrypted secrets stay encrypted) | Executor |
| H2-2 migrate local user (Type-8/9 / NX Type-5) | New-credential login **fails** in verification session | Restore prior `username` from golden; keep old account until new verified | Executor / change owner |
| H2-3 `enable` Type-8/9 secret | `enable` with new secret **fails** | Restore prior `enable secret` from golden | Executor |
| H3-0 NMS reconfigure for v3 (pre-step) | NMS **cannot** be prepared for v3 | **Abort H3** — no device SNMP touched | NMS team |
| H3-1 add SNMPv3 group/user/view | Device rejects v3 config / CPU spike | `no snmp-server user/group/view …` (v2c still live) | Executor |
| **H3-2 NMS polling GATE (pre-removal)** | NMS **not** confirmed polling this device over v3 in gate window | **Do NOT remove v2c**; leave dual-stack; investigate | Verifier / change owner |
| **H3-3 remove `snmp-server community <v2c>`** | Monitoring for the device **goes dark** after removal | Immediately re-add `snmp-server community <v2c-string> RO` from golden | NMS team detects; executor re-adds |
| ACL review | (review only — not executed) | N/A — any resulting scoping is a separate change | design-author |

---

## Deferred / out-of-scope for this wave (explicit — not silently dropped)

The following hardening long-tail from the finding is **Info/Low** and is **not** part of H1/H2/H3; it is
deferred to a separate low-risk hygiene tranche so this wave stays focused and reconcilable:

- **no-ntp — 9** (`AS01-BC-CA01A03-AJM-STD01`, `AS01-CI-BC-CAR1and2-AJA`, `AS02-BC-CA01A03-AJM-STD01`,
  `EVS01-BC-CAR7R181-ARDOH`, `EVS02-BC-CAR1-2R5-ARDOH`, `EVS03-BC-CAR21RC10-ARDOH`,
  `SW01-BC-NEXIS-CAR05R41`, `SW01-BC-ST5LED-CAR05R79A`, `SW02-BC-NEXIS-CAR05R41`)
- **no-banner — 2** (`AS01-BC-CAR11RD22`, `AS02-BC-CAR11RD22`)
- **no-logging — 1** (`AS02-BC-CA01A03-AJM-STD01`, NX-OS)

Also **not** owned here: the **KEV** exploited surfaces (Smart Install / Web UI) — a separate, more urgent
wave; H1's `show ip http` step only **observes** state and defers active Web-UI remediation to that wave.

---

## Execution-readiness gate & NRFU hand-off

**This MOP is NOT execution-ready today.** It becomes executable only after:
**(a)** the **SNMPv3 scheme** (2.a) is supplied; **(b)** **NMS-first SNMPv3 coordination** (2.b) is
confirmed; **(c)** **CAB approval** (2.c) following an independent dry-run — plus design inputs (d)/(e) and
OOB/golden (f). Every `<placeholder>` above is unfilled by design.

**NRFU hand-off (proposer ≠ verifier).** The post-checks in this MOP prove *"the command landed and the box
still works."* They are **not** the independent acceptance suite. The **NRFU/ATP acceptance** — a pre/post
baseline diff proving no mgmt-plane reachability regression, no SNMP-polling coverage loss, no credential
lockout, no ACL side-effects — is authored **independently by the nrfu-validator** against the current-state
baseline, and reviewed by deliverable-qa-reviewer. Dry-run reachability/blast-radius is owned by the
topology-reachability-analyst. **This agent does not write, run, or self-approve that acceptance.**

---

## Appendix — how to reproduce the reconciliation (auditability)

Counts and cohorts are recomputed, not asserted:
- **Fleet totals:** `cisco_toolkit.ssot.canonical_facts(snap)` → `n_devices=303`, `n_collected=253` (50 not-collected excluded).
- **Per-gap platform partition:** each host list in `docs/assessment/config-hardening-devices.json` matched
  against `snap['devices'][host]['platform']` — **all hosts matched (0 unmatched)**; the "Fex"-named split is
  by hostname pattern + model `N5K-C56128P`. Result = the cohort table in §1.1
  (H1 247=192+44+11 · weak-user-pw 73=18+44+11 · password-encryption 64=9+44+11 · SNMP 106=87+19+0 · ACL 8 IOS).
- **Source of truth:** device-level gaps → `config-hardening-devices.json`; narrative/severity →
  `config-hardening-2026-07-07.md`; state → the snapshot's `security` + `acls` blocks.
