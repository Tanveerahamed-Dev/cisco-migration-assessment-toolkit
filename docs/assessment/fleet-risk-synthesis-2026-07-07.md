# Fleet current-state risk synthesis — beyond KEV (2026-07-07)

**Status:** PROPOSE-ONLY assessment finding · **evidence:** `Migration_Assessment_AUTOFILLED_20260613_063201.snapshot.json`
(`software_risk.summary`, `health_scores`, `collection_completeness`) · **reproduce:** the `software_risk`
block is the engine's own computed output — read `snap['software_risk']['summary']`.

> The KEV package addressed two *actively-exploited* surfaces. This is the wider picture a senior engineer
> would not stop short of: the fleet's **software-currency debt, health distribution, and the largest finding
> class** — a 106-device SNMP exposure the KEV pass did not touch.

## Headline — three fleet-scale risks

| Risk | Magnitude | So what |
|---|---|---|
| **Software-currency debt** | **Only 11 of 303 (3.6%) are `Current-era`**; **54 `Replace/Upgrade` + 163 `Verify-EoL` + 75 `Unknown`** | ~72% of the fleet is on end-of-life or replace-grade software — a standing exposure + support risk far larger than the 21 KEV-priority devices. |
| **Device health** | **202 of 303 (67%) are `Critical` (117) or `Poor` (85)**; only **22 `Good`**, 50 `Insufficient Data` | The fleet is broadly unhealthy, not a few hotspots — migration/refresh is warranted at scale, not device-by-device. |
| **SNMP v2c exposure** | **106 devices** flagged `snmp-v2c-ro` (the single largest finding class, `by_kind`) | SNMPv2c community strings are **cleartext, unauthenticated** — sniffable for recon/inventory. Bigger by device count than the KEV surfaces. Remediate to **SNMPv3** (auth+priv). |

## Software-currency detail (`software_risk.summary.trains`)
| Train | Devices | Band |
|---|---|---|
| Classic IOS 15.x | 102 | Verify EoL |
| IOS XE 3.x | 52 | Replace/Upgrade |
| NX-OS 7.x | 34 | Verify EoL |
| IOS XE 16.x | 27 | Verify EoL |
| IOS XE 17.x | 11 | Current-era |
| NX-OS 6.x | 2 | Replace/Upgrade |
| (unknown) | 56 | Unknown |
| numeric `(05.xx)`/`(07.69)` | ~19 | (likely FEX / module firmware — verify, not a chassis train) |

## Coverage-honesty (Law 3)
- **50 devices are `not collected`** (`collection_completeness.summary.not_collected = 50`) and **56 have no
  version** — they are **not assessed**, never "clean". They overlap the KEV NOT_COLLECTED set; a read-only
  collection must run before any currency verdict for them.
- The numeric `(05.xx)` "trains" are almost certainly **FEX / line-card firmware**, not chassis IOS trains —
  do not schedule a chassis upgrade off them; verify per device.
- `Verify-EoL` is a **prompt to confirm lifecycle status against the Cisco EoL/EoS bulletins**, not a proven
  EoL — the engine flags the band; the PSIRT/EoX lookup confirms the date (the research lane's PSIRT source,
  now built, is the same egress path that resolves this).

## Prioritized remediation direction (propose-only; routes to the existing pipeline)
1. **SNMP v2c → SNMPv3 (106 devices)** — config-plane, no reload, low-risk; the fastest fleet-wide risk
   reduction. Same MOP/NRFU pattern as KEV Phase-A (a surface-closure change with a `--compare` regression
   gate). *Candidate for the next CAB after KEV Phase-A.*
2. **Software-currency campaign (217 EoL/Replace devices)** — a phased, multi-wave upgrade/refresh program
   (far larger than the 21 KEV devices); gate each wave on the blast-radius annex's per-device redundancy
   pre-check + PSIRT fixed-versions (`task_91dc2880`). This is a *program*, not a change window.
3. **Close the collection gap (50 not-collected)** — read-only collection so the 50 + 56 version-unknown leave
   UNKNOWN and can be assessed.

**Bottom line:** KEV was the *urgent* slice (actively exploited). This is the *large* slice — a fleet that is
3.6% current, 67% Critical/Poor, with a 106-device cleartext-SNMP exposure. Every figure is the engine's own
`software_risk`/`health_scores`/`collection_completeness` output, reproducible from the snapshot.
