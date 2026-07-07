# PSIRT / KEV exposure — actively-exploited CVEs vs. the assessed fleet (2026-07-07)

**Status:** PROPOSE-ONLY finding · **produced by:** the eyes→self-healing loop (research-lane CISA-KEV sweep
⊕ engine `software_risk`) · **evidence:** `Migration_Assessment_AUTOFILLED_20260613_063201.snapshot.json` +
`docs/intel/feed-2026-07-07.jsonl` · **reproduce:**
`python -m cisco_toolkit.intel_feed --dir docs/intel Migration_Assessment_AUTOFILLED_20260613_063201.snapshot.json`

## Headline — external intel sharpens the internal assessment

The engine's `software_risk` block flags two attack surfaces as **`verify`/`exposed`** (config-evidence
*screening*, not a vulnerability scan — `verify` = check whether the service is enabled, `exposed` = surface
confirmed open). Today's CISA **Known-Exploited-Vulnerabilities** sweep shows both are tied to CVEs that are
**actively exploited in the wild**, which promotes them from *"verify someday"* to **"verify / remediate
now":**

| Engine surface flag | Flagged (`verify`+`exposed`) | **IOS/IOS-XE (CVE-applicable)** | NX-OS (screening artifact) | Matching actively-exploited CVE |
|---|---|---|---|---|
| `smart-install` | 151 | **96** (+1 confirmed `exposed`: `AAS13-BC-CR02R03-TCDOH`) | 55 | **CVE-2018-0171** — Smart Install RCE |
| `http-server` | 63 | **8** (+2 confirmed `exposed`: `AAS13…`, `AS01-BC-CA01RA13-CXDOH`) | 55 | **CVE-2023-20198 + -20273** — IOS XE Web UI RCE (CVSS 10, mass-exploited Oct 2023) |

> **Platform-correctness (surfaced by independent verification — proposer ≠ verifier).** CVE-2018-0171 and
> CVE-2023-20198/-20273 are **IOS/IOS-XE** vulnerabilities. The engine's IOS-oriented `software_risk` detector
> also raises a `verify` flag on the **55 NX-OS** devices, where `vstack` (Smart Install) and IOS `ip http
> server` **do not exist** — so those NX-OS flags are **screening artifacts, not IOS-CVE exposure** (the NX-OS
> equivalent is NXAPI/`feature nxapi`, checked separately). The **actively-exploited, CVE-applicable exposure is
> 96 Smart-Install + 8 Web-UI IOS/IOS-XE devices**, with the **3 confirmed `exposed`** instances as priority-0.
> Both downstream deliverables (the MOP and the NRFU acceptance) independently reached this same carve-out.

Of the fleet, **45 of the 93** Cisco KEV advisories match the platforms present (`ios` 198, `nxos` 105).

## Priority — old train **and** an exposed exploited surface

**21 devices** are on a `Replace/Upgrade` train **and** carry one of the exploited surfaces above — remediate
these first (they are both unpatched-by-age and exposed on an exploited service). Software-currency context:

| train_band | devices | note |
|---|---|---|
| Replace/Upgrade | 54 | 52 on **IOS XE 3.x**, 2 on **NX-OS 6.x** — past software maintenance |
| Verify EoL | 163 | confirm lifecycle status |
| Current-era | 11 | — |
| Unknown | 75 | version not classifiable |

## Coverage-honesty (Law 3 — do not overstate)

- **`verify` ≠ confirmed-enabled.** The engine flagged these surfaces for verification; it did **not** confirm
  the service is live. The intel raises the *priority* of that verification (the vuln is being exploited), it
  does not by itself prove exposure. Each flagged device must be checked for the enabled service.
- **56 of 303 devices have a blank `sw_version` → `NOT_COLLECTED`.** They are **not** assessed here and are
  **not** "clean" — their exposure is unknown until a version is collected.
- **The feed lacks fixed-versions.** CISA KEV gives the CVE + product but **not** the Cisco-fixed release, so
  a precise *"upgrade device X to release Y"* target requires the per-CVE **Cisco PSIRT advisory** (not in
  this feed). *Next intel enrichment:* a PSIRT/openVuln sweep (the research lane's next source) to attach
  fixed-versions and make the remediation device-precise.

## Propose-only remediation direction (never a device write here)

Route to **`mop-change-author`** to author the change as a reviewable MOP + rollback, verified independently
by **`nrfu-validator`** (proposer ≠ verifier); apply only in a CAB maintenance window:

1. **Interim mitigation (fast, low-risk):** on flagged devices, verify and where safe **disable the exploited
   service** — `no vstack` (Smart Install) and restrict/disable the IOS-XE **HTTP/HTTPS Web UI** (or ACL it to
   a management host). This closes the actively-exploited surface without waiting for the upgrade.
2. **Upgrade path (the durable fix):** phase the **21 top-priority** devices first, then the 54
   Replace/Upgrade train devices, to a PSIRT-fixed release (target release from the PSIRT sweep above). Group
   by model/train into move-groups; each wave gets pre/post NRFU.
3. **Collect the 56 NOT_COLLECTED versions** so their exposure can be assessed (close the coverage gap).

Every figure above is derived deterministically from the snapshot + the signed feed and is reproducible with
the command in the header — this is a finding to action, not an opinion.
