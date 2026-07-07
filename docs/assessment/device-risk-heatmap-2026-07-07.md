# Device risk heat-map — where to start (cross-finding synthesis, 2026-07-07)

**Status:** PROPOSE-ONLY assessment synthesis (ranks devices across *all* findings; the remediation program's
"start here"). **Evidence:** `devices` + `software_risk` + `health_scores` + `security`. **Full ranked SSOT:**
[`device-risk-heatmap.json`](device-risk-heatmap.json). **Scope:** 253 config-assessable devices (50
not-collected are **unscored** — absent, not safe).

## Headline — 8 devices stack five risks; 93 carry four or more
Cross-referencing the six independent findings at the device level, a severity-weighted score
(`KEV 5 · weak-password 4 · poor-health 3 · EoL 2 · SNMP 2 · VTY 1 · no-encryption 1`) yields a clear
priority order:

- **8 devices score the maximum (14)** — hit by **five** of the seven dimensions: an actively-exploited **KEV**
  surface, an **EoL** train, a **weak local password** (High), **insecure SNMP**, and a **VTY** hardening gap.
- **93 of 253 devices carry ≥ 4** distinct risk dimensions — a large, concentrated high-risk cohort.
- **This axis is *security-finding density* only — it does NOT weight topological consequence / blast-radius.**
  So the fleet's highest-confidence SPOF, `DS-VSS-CAR3-R13-ARDOH` (blast-radius annex), scores **12** here —
  *below* the eight access/distribution boxes — because it lacks the SNMP dimension. An access switch with a
  v2c string is **not** more critical than the core SPOF; this list orders *how many security gaps stack on a
  box*, and MUST be read **with** the [blast-radius annex](../security/kev-remediation-blast-radius-2026-07-07.md)
  for change sequencing.

### The priority-0 list (score 14 — fix these first, once, across all waves)
`AS22-MGM-CA05R70-stack` · `AS20-MGM-CA11B29-Stack` · `DS-VSS-CA05R27CA11F17-SW` ·
`AS25-BC-TR11SatR2-BCDOH` · `AS20-BC-TR12SatR2-BCDOH` · `AS22-BC-TE421R01` · `AS21-BC-TE421R01` ·
`AS21-MGM-TE421R02`

(The confirmed-`exposed` KEV canary `AAS13-BC-CR02R03-TCDOH` scores 11 — already Phase-A wave-0.)

## Why this matters — batch by DEVICE, not just by finding
The remediation waves are organized by *finding* (KEV Phase-A, the hardening wave, the currency program). But
these 8 (and the 93) devices appear in **several waves at once**. Touching them **once, coordinated** — Phase-A
mitigation + hardening + scheduling their upgrade together — is cheaper and lower-risk than visiting the same
device in three separate windows. The heat-map is the join that makes that possible; several high-scoring
devices (`AS20/21/25-*`) are also in the KEV blast-radius priority set — so those change-sequencing pre-checks
already apply — while `DS-VSS-CAR3-R13` (score 12, the annex's top SPOF) shows the two views are complementary:
security-gap density here, topological consequence there. So the
change-sequencing pre-checks already apply to them.

## Coverage-honesty (Law 3)
- The score is a **heuristic ranking aid**, not a calibrated risk measure — the weights are defensible defaults
  (mirroring the engine's own "uncalibrated ScoringConfig" posture), useful for **ordering**, not for an
  absolute number. A device's *presence* on the list is grounded (each dimension is a real finding); its
  *rank* is indicative.
- The **50 not-collected devices are unscored** — excluded, not low-risk. Their risk is unknown until collected.
- KEV here = IOS device with an exposed Smart-Install/Web-UI surface (the CVE-applicable population), consistent
  with the platform-corrected KEV finding.

**Bottom line:** don't remediate finding-by-finding for the worst devices — the **8 max-risk + 93 ≥4-dimension**
devices should be sequenced as **coordinated per-device touches**. This is the operational bridge from the
five findings to a change plan; it turns "which devices first" from a judgement call into a grounded, ordered list.
