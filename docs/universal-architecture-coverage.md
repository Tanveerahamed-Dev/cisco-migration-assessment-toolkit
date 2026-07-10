# Universal architecture coverage

The engine assesses **any** customer's Cisco architecture, not one fixed topology, across the **two ways
the evidence arrives** — SSH `show`-text and controller JSON/REST. Every architecture class is a
coverage-honest detector: it fires only on a genuinely-broken **observed** state, stays silent when the
feature is absent or healthy, and never turns "not observed" into "healthy". This page is the operator +
developer reference for that capability.

## The two ingestion channels

| Channel | How evidence arrives | Parser style | Architectures |
|---|---|---|---|
| **SSH show-text** | captured `show` command output (offline files or live SSH) | tolerant regex (`parse.py`) | switch-native (FHRP, VXLAN-EVPN, CoPP, PIM, IPv6-FHS, NTP, port-security, storm-control, QoS-runtime, shadow-infra), SP/MPLS (LDP/L3VPN/L2VPN), SD-Access LISP, TrustSec/CTS, DMVPN, IPsec, BFD, IPv6 (DAD + OSPFv3/BGP routing), **firewall HA + resource capacity (ASA / Secure Firewall Threat Defense)** |
| **JSON controller-REST** | controller export (offline JSON files or live REST) | `json.loads` normalizers (`parse_aci_*`, `parse_sdwan_*`, `parse_ise_nodes`, `parse_fmc_*`) | Cisco ACI (APIC), Cisco Catalyst SD-WAN (vManage), **Cisco ISE (Identity Services Engine)**, **Cisco Secure Firewall Management Center (FMC)** |

The JSON channel is a **tiny delta** over the show-text one: the offline pipeline reads an export file as
text via the same `_load_cmd_output` path, and the parser does `json.loads` instead of regex. Everything
downstream — `build_*` → `snap_dict[<axis>]` → `_d_*` detectors → `design_blueprint` → deliverables →
dashboards — is reused unchanged.

## What is assessed (46 architecture-class detectors across 27 classes)

> Count reconciled to the in-code owner (`design_advisor._ARCH_COVERAGE_REGISTRY`: 46 probe-ids across
> 27 class axes; guarded by `tests/test_ssot_registry.py`). The enumeration below covers the classes
> through the ISE/FMC wave; the registry has since added **Arista, Juniper, FortiGate (SSH)** and
> **cloud (JSON)** — each with its own parser test file (`tests/test_arista.py`, `test_juniper.py`,
> `test_fortinet.py`, `test_cloud.py`).

Each detector fires on a single, unambiguous broken state; the cry-wolf trap is excluded by design:

- **ACI** — raised+unacknowledged critical/major `faultInst`; a `fabricNode` not active (decommissioned /
  inactive / disabled); `fabricHealthTotal.cur < 90`; a VRF (`fvCtx`) with `pcEnfPref=unenforced`
  (contract enforcement off → default-permit).
- **SD-WAN** — a control connection `state=down` (or `actual < expected`); a device the Manager reports
  `reachability=unreachable`; an edge with `ompPeersDown > 0` (overlay routing degraded, distinct from a
  control-connection loss).
- **SD-Access LISP** — a VRF with control-plane sessions configured but **zero** established (keys off the
  device's own summary counts, never a single Down peer — a lone Down session is normal).
- **TrustSec/CTS** — environment-data `Current state != COMPLETE` (the SGT→policy map is not downloaded).
- **DMVPN** — an NHRP/tunnel peer not `UP`. **IPsec** — a crypto session `Session status` starting `DOWN`
  (UP-ACTIVE / UP-IDLE / UP-NO-IKE are healthy). **BFD** — a session `Down` (AdminDown is excluded).
- **IPv6** — a global/link-local address `[DUPLICATE]` (DAD failure; TENTATIVE excluded); an OSPFv3 neighbor
  stuck (not FULL/2WAY — 2WAY DROTHER is healthy) or an IPv6 BGP peer not Established.
- **SP/MPLS** — an LDP session not `Oper`; a VPNv4 peer not `Established`; an L2VPN pseudowire `DOWN`.
- **Firewall HA (ASA / Secure Firewall Threat Defense)** — `show failover` reports failover **enabled** yet a
  unit `Failed` / the peer `Not Detected` / a unit `Disabled` (Active/Standby inline `This/Other host` state,
  or per-group `Group n State` in Active/Active) — the HA pair has no working standby (the config-present-but-
  operationally-broken false-health trap). A healthy `Active`+`Standby Ready` pair, every transient sync state
  (Negotiation / Cold Standby / Sync* / Bulk Sync / App Sync), and a standalone `Failover Off` box stay silent.
- **Firewall capacity (ASA / FTD)** — `show resource usage`: a data-plane resource (Conns / Xlates / Hosts)
  with `Denied > 0` (the box hit its Limit and dropped real connections/translations at peak) or `Peak ≥ 90%`
  of a numeric Limit (approaching exhaustion) — the migration sizing signal (size the replacement above the
  observed peak). The administrative rows (SSH/ASDM/HTTP failed-login & session-cap counters) and the `[rate]`
  rows (intentional rate-limiting) are excluded; an `N/A`/unlimited Limit or a low peak stays silent.
- **Cisco ISE (Identity Services Engine)** — **two read-only front doors**, both normalized by `parse_ise_nodes`:
  the **Open API** (`GET /api/v1/deployment/node`, HTTPS/443 — `roles[]`/`services[]` + `nodeStatus`
  reachability) and **ERS** (`GET /ers/config/node` → per-id detail, HTTPS/9060, closed by default — boolean
  personas `primaryPapNode`/`papNode`/`pxGridNode` + comma-string `nodeServiceTypes`, mapped to the same
  `roles[]`/`services[]`; ERS exposes **no reachability**, so node-not-connected is coverage-honestly silent on
  ERS-only evidence). Detectors: a node `nodeStatus` not `Connected` (transient in-progress/registering
  excluded, NOT a replication verdict); exactly one Policy Service node (`Session`) or a missing Secondary
  Admin / Monitoring in a **multi-node** deployment. The ≥2-node gate never cry-wolfs a Cisco-supported
  single-node standalone (single-PSN/PAN/MnT by design). ISE is the source of truth for the SGT/SGACL matrix
  the switch-side **TrustSec/CTS** detector consumes — a dead PSN degrades env-data/SGACL download too.
- **Cisco Secure Firewall Management Center (FMC)** — for an FMC-managed FTD fleet the controller is the source
  of truth. `.../devicehapairs/ftddevicehapairs`: an FTD HA pair node `Failed`/`Not Detected` or split
  (`Disabled` = operator-suspended, excluded); `.../devices/devicerecords`: `isConnected==false` or
  `healthStatus=='red'` (`green`/`yellow` and the no-data `black`/`blue` excluded); `.../deployment/deployabledevices`
  non-empty (staged undeployed config — reconcile before cutover); `.../integration/fmchastatuses`
  `Degraded`/`Split Brain`/not-`Synced` (the manager's own HA); and `.../info/serverversion` OLDER than a
  managed FTD's `sw_version` (Cisco mandates FMC ≥ every managed device — version-compared, not date-based). A
  standalone FTD / standalone FMC stays silent.

The full architecture→detector map is the authoritative `_ARCH_COVERAGE_REGISTRY` in `design_advisor.py`.

## Architecture-coverage SSOT

`compute_architecture_coverage(snap)` publishes `snap['architecture_coverage']` — for every architecture
class: was it **observed** (axis present), which hosts, its channel (ssh/json), and its status:

- `finding` — observed **and** a detector fired,
- `clean` — observed, nothing wrong,
- `not-observed` — no evidence of this architecture (**coverage-honest: NOT "healthy"**).

One source of truth: the explorer ✎Design view (`drawArchCoverage`) and the AssessHub Design panel
(`GET /api/snapshots/{id}/architecture_coverage`) both read it — neither re-derives coverage.

## Migration planning

- **Switch fabric** — `target_state.wave_plan` groups switches by L2 coupling into parallelizable waves.
- **ACI fabric** — `target_state.aci_move_groups` groups the ACI logical census **by tenant** (the ACI
  migration boundary; EPGs the finest unit; biggest tenant leads), flagging any unenforced-VRF tenant as a
  segmentation gap. Rendered in both the explorer and the webapp Design view.

## Collecting the controller fabrics (live, read-only)

Controller fabrics expose state only via REST. `cisco_toolkit/rest_collect.py` is the **opt-in, read-only**
live front door; it writes the same JSON export files the offline pipeline reads, so collection and analysis
stay decoupled.

```bash
# ACI / APIC  (writes moquery_-c_*.txt into the controller's device dir)
python -m cisco_toolkit.rest_collect apic --url https://<apic> --user <ro-user> --password <pw> \
    --out-dir <collection-dir>/<apic-host>

# Catalyst SD-WAN / vManage  (writes dataservice_*.txt)
python -m cisco_toolkit.rest_collect vmanage --url https://<manager>:8443 --user <ro-user> --password <pw> \
    --out-dir <collection-dir>/<vmanage-host>

# Cisco ISE / Identity Services Engine  (HTTP Basic auth; collects BOTH the Open API /api/v1/deployment/node
#   on 443 AND ERS /ers/config/node on 9060 -> consolidated; use a read-only account, ERS 'External RESTful
#   Services Operator' = GET-only. ERS is closed by default; if disabled it is skipped fail-soft.)
python -m cisco_toolkit.rest_collect ise --url https://<ise-pan> --user <ro-user> --password <pw> \
    --out-dir <collection-dir>/<ise-host>

# Cisco Secure Firewall Management Center / FMC  (generatetoken -> domain-scoped GETs; writes api_fmc_config_*.txt)
python -m cisco_toolkit.rest_collect fmc --url https://<fmc> --user <ro-user> --password <pw> \
    --out-dir <collection-dir>/<fmc-host>
```

Then add the controller as a device in `devices.json` and run the normal offline analysis
(`cisco-assess --no-collect --collection-dir <collection-dir> …`) — `build_aci` / `build_sdwan` / `build_ise`
/ `build_fmc` and the detectors pick the JSON up automatically.

### Safety doctrine (read before pointing it at a fabric)

- **GET-only.** The only POST is the login; every fabric query is a GET — it cannot change fabric state.
- **Read-only is credential-enforced, not command-enforced.** On a controller the same token that GETs can
  POST, so unlike the SSH `show`-only collector there is no protocol-level read-only floor. Use a **dedicated
  AAA account bound to a read-only RBAC role.**
- The password is used **once** for login and is **never** written to the snapshot, the collection dir, or any
  log (test-locked). Authentication is **refused over non-HTTPS** (a cleartext password leak).
- **Opt-in only** — nothing here runs on import or inside `cisco-assess`; a human invokes it with explicit
  engagement authorization, mirroring the SSH collector's "no live collection unless explicitly asked".
- TLS verifies by default; `--insecure` is only for a lab/sandbox self-signed cert (logged).

## Coverage-honesty (the prime doctrine)

A detector that cries wolf is worse than no detector. Every detector here fires only on an observed,
genuinely-broken state; benign/intentional/transient states are excluded (IPsec UP-IDLE, BFD AdminDown, IPv6
TENTATIVE, OSPFv3 2WAY-DROTHER, a lone LISP Down peer, a transient firewall sync state, a standalone ISE
deployment). Proven on the canonical AJ customer snapshot (verified at the 40-detector baseline; classes
added since carry their own per-vendor parser test files): the detectors fire on synthetic fixtures yet
produce **zero** decisions on the real AJ fleet (which captured none of these axes). A fuzz/robustness gate (`tests/test_universal_arch_robustness.py`) guarantees no parser raises
on hostile input and the detectors survive malformed evidence without spuriously firing.
