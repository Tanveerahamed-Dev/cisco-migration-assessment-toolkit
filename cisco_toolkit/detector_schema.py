"""Per-detector DESCRIPTORS — make "not-observed != healthy" a SCHEMA PROPERTY (MASTER_PLAN 3.5 / J1).

Coverage-honesty is enforced at RUNTIME across the engine (the 3-state token
`cisco_toolkit.ssot.abstention_reason` -> "published" | "collected_but_empty" | "not_collected", and
every axis that declares an un-collected device NOT ASSESSABLE rather than passing). But until now that
was a *convention* proven only by reading each ``compute_*`` — nothing DECLARED, as data, that a given
detector must abstain when its evidence is absent. This module is that declaration.

It is a curated, DECLARATIVE registry — a list of descriptors as data, exactly like the repo's existing
``_DETECTORS`` / ``_PER_DEVICE_AXES`` / doctrine registries — one descriptor per MAJOR analysis
detector/axis. Each descriptor states, grounded in the REAL detector source (not a guess):

  * ``key``            — stable unique id for the detector.
  * ``title``          — one-line human name.
  * ``family``         — the axis family (L1 / L3 / STP / Security / Lifecycle / Syslog / QoS /
                         Software / Platform / Capacity / Segmentation / Hygiene).
  * ``checks``         — what condition the detector actually tests for.
  * ``healthy_value``  — the value/state that reads as healthy (matches the real logic).
  * ``threshold``      — the numeric/categorical boundary, or ``None`` when the check is boolean/categorical.
  * ``cited_fields``   — the dotted snapshot keys the detector READS (real keys, verified against the
                         producing ``compute_*`` and the published snapshot shape).
  * ``abstains_when``  — the COVERAGE-HONEST guard: the condition under which the detector abstains
                         ("not collected" / "no running-config", …) INSTEAD of passing. This is the
                         "not-observed != healthy" schema property. It is NEVER empty for a detector
                         whose evidence can be absent (``evidence_gated=True``).
  * ``evidence_gated`` — True iff the detector can only fire on collected evidence, so a missing
                         collection is a BLIND SPOT, never a clean pass. When True, ``abstains_when``
                         must be non-empty (enforced by ``tests/test_detector_schema.py``).
  * ``source_command`` — the ``show`` command whose output backs the check. Reuses
                         ``analyze._PUNCH_SOURCE_COMMAND`` where a family maps to it; otherwise the
                         command the producing ``compute_*`` documents it reads.

This module DESCRIBES detection; it does NOT re-run it. It never touches a device, never mutates the
snapshot, imports no network library, and is deterministic and pure. It carries no config-mode verbs:
every ``source_command`` is a read-only ``show`` query.

The 3-state abstention vocabulary is owned by :func:`cisco_toolkit.ssot.abstention_reason`; the
``abstains_when`` prose here NAMES the condition that maps to its ``not_collected`` state, it does not
re-implement the token.
"""
from __future__ import annotations

from typing import Any, Dict, List

from cisco_toolkit.textutils import (   # native-VLAN-1 unit/basis tokens -- one owner (leaf module)
    NATIVE1_CFG_BASIS, NATIVE1_CFG_UNIT, NATIVE1_OPS_BASIS)

SCHEMA = "detector_schema/1"

# Reuse the engine's punch-list source-command map so a descriptor's `source_command` is the SAME
# read-only show-command the finding cites — one owner, never a divergent copy. (analyze._PUNCH_SOURCE_COMMAND)
try:  # pragma: no cover - trivial import guard
    from cisco_toolkit.analyze import _PUNCH_SOURCE_COMMAND as _PUNCH
except Exception:  # pragma: no cover
    _PUNCH = {}


def _src(category: str, fallback: str) -> str:
    """The read-only show-command backing `category`, preferring the shared punch-list map so the two
    never drift; `fallback` is the command the producing compute_* documents when the category is not
    in that map (composite/meta categories are deliberately absent there)."""
    return _PUNCH.get(category) or fallback


# =============================================================================
# THE DECLARATIVE REGISTRY. Each entry is grounded in the cited detector source — read the compute_* /
# parse_* to confirm healthy_value + threshold + cited_fields before editing. A descriptor that
# misstates the code is worse than none.
# =============================================================================
_DETECTOR_DESCRIPTORS: List[Dict[str, Any]] = [
    # ---- L1 physical health (analyze/excel.write_physical_health_sheet; risk flags per port) ----------
    {
        "key": "l1-err-disabled",
        "title": "Err-disabled physical port",
        "family": "L1",
        "checks": "A physical port whose status matches an err-disable state (a protection mechanism "
                  "shut the port down).",
        "healthy_value": "no err-disabled port",
        "threshold": None,
        "cited_fields": ["physical_health[].status", "physical_health[].risk"],
        "abstains_when": "device not collected, or interface status/counters not captured for the port",
        "evidence_gated": True,
        "source_command": _src("L1", "show interface status"),
    },
    {
        "key": "l1-half-duplex-uplink",
        "title": "Half-duplex trunk / uplink",
        "family": "L1",
        "checks": "A trunk or uplink port negotiated to half-duplex (a duplex mismatch on an "
                  "inter-switch link).",
        "healthy_value": "full-duplex on every trunk/uplink",
        "threshold": "duplex == Half (on a trunk or uplink port)",
        "cited_fields": ["physical_health[].duplex", "physical_health[].risk"],
        "abstains_when": "device not collected, or the interface detail carrying duplex not captured",
        "evidence_gated": True,
        "source_command": _src("L1", "show interface status"),
    },
    {
        "key": "l1-single-fiber-uplink",
        "title": "Single-fiber (non-redundant) uplink",
        "family": "L1",
        "checks": "An uplink with only one physical fiber member — no link-level redundancy, so the "
                  "next fiber cut isolates the switch.",
        "healthy_value": "every uplink dual-homed / bundled",
        "threshold": None,
        "cited_fields": ["physical_health[].port", "physical_health[].risk"],
        "abstains_when": "device not collected, or the topology/interface evidence for the uplink absent",
        "evidence_gated": True,
        "source_command": _src("Link L1", "show interface status"),
    },
    {
        "key": "l1-error-rate-high",
        "title": "High interface error/drop rate",
        "family": "L1",
        "checks": "An operationally-up port carrying non-zero input errors, CRCs, output drops, output "
                  "errors or late collisions (a marginal cable/optic).",
        "healthy_value": "zero error/drop counters on up ports",
        "threshold": "any counter > 0 (input_errors / crc_errors / output_drops / output_errors / late_collisions)",
        "cited_fields": ["physical_health[].input_errors", "physical_health[].crc_errors",
                         "physical_health[].output_drops", "physical_health[].late_collisions"],
        "abstains_when": "device not collected, or interface counters not captured (counters absent != zero)",
        "evidence_gated": True,
        "source_command": _src("L1", "show interfaces"),
    },
    # ---- L3 forwarding (excel.write_l3_forwarding_sheet; per-gateway-SVI risk flags) -----------------
    {
        "key": "l3-single-gateway",
        "title": "Single-gateway VLAN (no redundant first hop)",
        "family": "L3",
        "checks": "A VLAN whose default gateway SVI exists on only one scanned switch — one box owns "
                  "the first hop, a single point of failure.",
        "healthy_value": ">= 2 gateways for the VLAN",
        "threshold": "gateway count <= 1 for the VLAN",
        "cited_fields": ["l3_forwarding[].vlan", "l3_forwarding[].svi_ip", "l3_forwarding[].risk"],
        "abstains_when": "no device carrying the VLAN's SVI was collected (an off-scan gateway is not evidence of absence)",
        "evidence_gated": True,
        "source_command": _src("L3", "show ip route"),
    },
    {
        "key": "l3-no-fhrp",
        "title": "Multi-gateway VLAN with no FHRP",
        "family": "L3",
        "checks": "A VLAN with >= 2 gateways where no end runs a first-hop-redundancy protocol — the "
                  "second gateway does not actually back up the first.",
        "healthy_value": "an FHRP (HSRP/VRRP/GLBP) present on the gateways",
        "threshold": None,
        "cited_fields": ["l3_forwarding[].fhrp", "l3_forwarding[].risk"],
        "abstains_when": "the VLAN's gateways were not collected, or FHRP behaviour not captured",
        "evidence_gated": True,
        "source_command": _src("FHRP", "show standby brief"),
    },
    {
        "key": "l3-tracked-object-down",
        "title": "Down tracked object on a gateway",
        "family": "L3",
        "checks": "A gateway switch with a tracked object in the DOWN state — the object the FHRP "
                  "priority/route depends on has failed.",
        "healthy_value": "all tracked objects up (or none tracked)",
        "threshold": "tracked-down count > 0",
        "cited_fields": ["l3_forwarding[].tracking", "l3_forwarding[].risk"],
        "abstains_when": "device not collected, or the tracking output not captured for the gateway",
        "evidence_gated": True,
        "source_command": "show track",
    },
    # ---- FHRP consistency (excel.compute_fhrp_consistency; per multi-gateway VLAN) -------------------
    {
        "key": "fhrp-fake-redundancy",
        "title": "Fake first-hop redundancy on a VLAN",
        "family": "L3",
        "checks": "A VLAN whose >= 2 gateways have inconsistent FHRP — missing on one end, mixed "
                  "protocols, different groups/virtual-IPs, or two active routers (split-brain).",
        "healthy_value": "one FHRP group, one virtual IP, one active router per VLAN",
        "threshold": None,
        "cited_fields": ["fhrp[].vid", "fhrp[].issues", "fhrp[].members"],
        "abstains_when": "the VLAN's gateway switches were not all collected (an unseen far-end gateway is not evidence of consistency)",
        "evidence_gated": True,
        "source_command": _src("FHRP", "show standby brief"),
    },
    # ---- STP root placement (analyze.stp_root_findings; PVST/RPVST only) -----------------------------
    {
        "key": "stp-accidental-root",
        "title": "Accidental STP root (default bridge priority)",
        "family": "STP",
        "checks": "A VLAN whose spanning-tree root runs the default bridge priority, so the root was "
                  "won on a MAC tiebreak, not engineered — it can move on a cutover.",
        "healthy_value": "a non-default (deliberately lowered) root priority",
        "threshold": "root_priority in {32768, 32768 + vlan-id}",
        "cited_fields": ["stp_roots.<host>.<vlan>.root_priority", "stp_roots.<host>.<vlan>.is_root"],
        "abstains_when": "the root switch for the VLAN was not collected, or spanning-tree output not captured (MST instances are out of scope)",
        "evidence_gated": True,
        "source_command": _src("STP", "show spanning-tree"),
    },
    {
        "key": "stp-root-gateway-misaligned",
        "title": "STP root not co-located with the L3 gateway",
        "family": "STP",
        "checks": "A VLAN whose spanning-tree root is a switch that does NOT host the VLAN's L3 gateway "
                  "SVI, so intra-VLAN traffic to the gateway hairpins through the root.",
        "healthy_value": "root bridge == a gateway-hosting switch",
        "threshold": None,
        "cited_fields": ["stp_roots.<host>.<vlan>.is_root", "l3_forwarding[].svi_ip"],
        "abstains_when": "the root switch or the VLAN's gateway switch was not collected",
        "evidence_gated": True,
        "source_command": _src("STP", "show spanning-tree"),
    },
    # ---- Security / CIS hardening (parse.parse_security -> snap['security'][host].findings) ----------
    {
        "key": "sec-no-aaa",
        "title": "No centralized AAA (CIS 1.4)",
        "family": "Security",
        "checks": "The running-config has no central AAA (TACACS+/RADIUS) — authentication is local / "
                  "line-based only.",
        "healthy_value": "status == pass (central AAA configured)",
        "threshold": None,
        "cited_fields": ["security.<host>.findings[].id", "security.<host>.findings[].status"],
        "abstains_when": "no running-config captured for the device (parse_security returns {} -> the CIS finding cannot be emitted)",
        "evidence_gated": True,
        "source_command": _src("Security", "show running-config"),
    },
    {
        "key": "sec-weak-enable",
        "title": "Reversible privileged-EXEC secret (CIS 1.2.1)",
        "family": "Security",
        "checks": "The device uses a reversible 'enable password' (Type-0/7) instead of a strong "
                  "'enable secret'.",
        "healthy_value": "status == pass (strong enable secret) or na (none present)",
        "threshold": None,
        "cited_fields": ["security.<host>.findings[].id", "security.<host>.findings[].status"],
        "abstains_when": "no running-config captured for the device",
        "evidence_gated": True,
        "source_command": _src("Security", "show running-config"),
    },
    {
        "key": "sec-insecure-snmp",
        "title": "SNMPv1/v2c community exposure (CIS 3.1)",
        "family": "Security",
        "checks": "A read or read-write SNMP v1/v2c community is present (cleartext, guessable) rather "
                  "than SNMPv3 auth+priv.",
        "healthy_value": "status == pass (no v1/v2c community; SNMPv3 only)",
        "threshold": None,
        "cited_fields": ["security.<host>.findings[].id", "security.<host>.findings[].status"],
        "abstains_when": "no running-config captured for the device",
        "evidence_gated": True,
        "source_command": _src("Security", "show running-config"),
    },
    {
        "key": "sec-telnet-enabled",
        "title": "Telnet VTY transport enabled (CIS 2.1)",
        "family": "Security",
        "checks": "A VTY line permits telnet (or the NX-OS telnet feature is on) — cleartext management "
                  "access.",
        "healthy_value": "status == pass (ssh-only transport)",
        "threshold": None,
        "cited_fields": ["security.<host>.findings[].id", "security.<host>.findings[].status"],
        "abstains_when": "no running-config captured for the device",
        "evidence_gated": True,
        "source_command": _src("Security", "show running-config"),
    },
    {
        "key": "sec-no-logging",
        "title": "No logging / audit trail (CIS 6.2)",
        "family": "Security",
        "checks": "The running-config configures no syslog host / buffered logging — no audit trail "
                  "across the migration.",
        "healthy_value": "status == pass (logging configured)",
        "threshold": None,
        "cited_fields": ["security.<host>.findings[].id", "security.<host>.findings[].status"],
        "abstains_when": "no running-config captured for the device (config absence never reads as configured logging — the bare NX-OS false-health class)",
        "evidence_gated": True,
        "source_command": _src("Security", "show running-config"),
    },
    # ---- Config hygiene (parse.parse_config_hygiene -> snap['config_hygiene']) -----------------------
    {
        "key": "hygiene-undefined-reference",
        "title": "Undefined ACL / route-map / object-group reference",
        "family": "Hygiene",
        "checks": "A referenced ACL/route-map/object-group/prefix-list that is never defined — it "
                  "silently does nothing, a migration-breaker.",
        "healthy_value": "no undefined references",
        "threshold": None,
        "cited_fields": ["config_hygiene.<host>.undefined[].kind", "config_hygiene.<host>.undefined[].name"],
        "abstains_when": "no running-config captured for the device (an un-captured config is not a clean config)",
        "evidence_gated": True,
        "source_command": _src("Config hygiene", "show running-config"),
    },
    # ---- Lifecycle / EoL (analyze.compute_lifecycle_risk -> snap['lifecycle_risk']) ------------------
    {
        "key": "lifecycle-past-ldos",
        "title": "Device past last-day-of-support (LDoS)",
        "family": "Lifecycle",
        "checks": "A device whose model's LDoS date is in the past relative to the assessment date — no "
                  "vendor support of any kind remains.",
        "healthy_value": "band == Active (LDoS in the future)",
        "threshold": "band == Past-LDoS (LDoS date <= asof)",
        "cited_fields": ["lifecycle_risk.per_device[].band", "lifecycle_risk.summary.n_past_ldos"],
        "abstains_when": "model not resolvable in the offline eoldb KB, or device model not collected (band == Unknown, never a silent Active)",
        "evidence_gated": True,
        "source_command": _src("Inventory", "show version"),
    },
    {
        "key": "lifecycle-past-eos",
        "title": "Device past end-of-sale but not yet LDoS",
        "family": "Lifecycle",
        "checks": "A device past its end-of-sale date but still within the support tail (a distinct, "
                  "smaller population than Past-LDoS).",
        "healthy_value": "band == Active",
        "threshold": "band == Past-EoS (EoS <= asof < LDoS)",
        "cited_fields": ["lifecycle_risk.per_device[].band", "lifecycle_risk.summary.n_past_eos"],
        "abstains_when": "model not resolvable in the eoldb KB, or device model not collected (band == Unknown)",
        "evidence_gated": True,
        "source_command": _src("Inventory", "show version"),
    },
    # ---- Syslog intelligence (analyze.compute_syslog_intelligence -> snap['syslog_intelligence']) ----
    {
        "key": "syslog-mac-flap",
        "title": "MAC-flap events in the log buffer",
        "family": "Syslog",
        "checks": "MAC-flap / MAC-move events in the buffered log (a bridging loop or a dual-homed "
                  "endpoint moving between ports).",
        "healthy_value": "no mac-flap detection",
        "threshold": None,
        "cited_fields": ["syslog_intelligence.detections[].kind", "syslog_intelligence.per_device[].collected"],
        "abstains_when": "the device's buffered log was not collected (per_device.collected == False); the buffer is a bounded window so counts are floors",
        "evidence_gated": True,
        "source_command": _src("Operational logs", "show logging"),
    },
    {
        "key": "syslog-errdisable",
        "title": "Err-disable events in the log buffer",
        "family": "Syslog",
        "checks": "Err-disable transitions in the buffered log (a port protection mechanism tripping).",
        "healthy_value": "no err-disable detection",
        "threshold": None,
        "cited_fields": ["syslog_intelligence.detections[].kind", "syslog_intelligence.per_device[].collected"],
        "abstains_when": "the device's buffered log was not collected (per_device.collected == False)",
        "evidence_gated": True,
        "source_command": _src("Operational logs", "show logging"),
    },
    {
        "key": "syslog-link-flap",
        "title": "Interface link-flap in the log buffer",
        "family": "Syslog",
        "checks": "An interface with repeated down transitions in the buffered log (a flapping link).",
        "healthy_value": "no interface at/over the link-flap floor",
        "threshold": ">= link-flap minimum down-transitions per interface (_SYSLOG_LINK_FLAP_MIN)",
        "cited_fields": ["syslog_intelligence.detections[].kind", "syslog_intelligence.detections[].count"],
        "abstains_when": "the device's buffered log was not collected (per_device.collected == False)",
        "evidence_gated": True,
        "source_command": _src("Operational logs", "show logging"),
    },
    # ---- QoS audit (analyze.compute_qos_audit -> snap['qos_audit']) ----------------------------------
    {
        "key": "qos-no-trust-boundary",
        "title": "QoS enabled with no trust boundary",
        "family": "QoS",
        "checks": "Global QoS is enabled but no port defines a trust boundary, so ingress CoS/DSCP is "
                  "remarked to 0 fleet-wide — QoS actively harms traffic in this state.",
        "healthy_value": "a defined trust boundary (or QoS not globally enabled)",
        "threshold": None,
        "cited_fields": ["qos_audit.per_device[].n_trust_if", "qos_audit.findings[].kind"],
        "abstains_when": "no full running-config captured (per_device.assessable == False -> device declared not-assessable, never scored healthy)",
        "evidence_gated": True,
        "source_command": _src("QoS", "show policy-map interface"),
    },
    {
        "key": "qos-voice-without-qos",
        "title": "Voice VLAN without an edge QoS policy",
        "family": "QoS",
        "checks": "A voice-VLAN access port carrying no trust statement, auto-QoS macro or "
                  "service-policy — phone markings are not honored at the edge.",
        "healthy_value": "voice ports carry a trust/auto-QoS/service-policy",
        "threshold": None,
        "cited_fields": ["qos_audit.per_device[].n_voice_if", "qos_audit.findings[].kind"],
        "abstains_when": "no full running-config captured (per_device.assessable == False)",
        "evidence_gated": True,
        "source_command": _src("QoS", "show policy-map interface"),
    },
    # ---- Software advisory surface (analyze.compute_software_risk -> snap['software_risk']) ----------
    {
        "key": "software-advisory-surface",
        "title": "Open attack surface for a landmark advisory",
        "family": "Software",
        "checks": "A configuration surface that is open (exposed web UI / SNMP v1-v2c / Smart Install / "
                  "telnet / SSHv1 / IKEv1 / small services) and maps to a landmark public advisory — "
                  "'surface open', never a per-release vulnerability verdict.",
        "healthy_value": "surface closed on every screened kind",
        "threshold": None,
        "cited_fields": ["software_risk.per_device[].surfaces", "software_risk.findings[].kind"],
        "abstains_when": "no running-config captured (per_device.config_assessable == False -> the surface layer is declared not-assessable, never 'closed')",
        "evidence_gated": True,
        "source_command": _src("Software exposure", "show version"),
    },
    {
        "key": "software-train-lifecycle",
        "title": "Software train in a replace/verify lifecycle band",
        "family": "Software",
        "checks": "A cautious software-TRAIN lifecycle band derived from the collected version/platform "
                  "(replace / verify-with-Cisco / current-era), verify-with-Cisco wording.",
        "healthy_value": "train_band == a current-era band",
        "threshold": None,
        "cited_fields": ["software_risk.per_device[].train_band", "software_risk.per_device[].sw_version"],
        "abstains_when": "software version not captured for the device (sw_version == '(not captured)' -> the train layer is not assessable)",
        "evidence_gated": True,
        "source_command": _src("Inventory", "show version"),
    },
    # ---- Platform / control-plane capacity (analyze.compute_platform_health -> snap['platform_health']) --
    {
        "key": "platform-cpu-hot",
        "title": "Control-plane CPU hot",
        "family": "Platform",
        "checks": "A 5-minute CPU average at/above the hot threshold — no headroom for a reconvergence "
                  "event or a config push (a single point-in-time sample).",
        "healthy_value": "band == OK (5-min CPU below the elevated threshold)",
        "threshold": "cpu_5min >= 80 (Hot); >= 60 (Elevated)",
        "cited_fields": ["platform_health.per_device[].cpu_5min", "platform_health.per_device[].band"],
        "abstains_when": "capacity commands not collected (per_device.collected == False -> band == Unknown, never a silent OK)",
        "evidence_gated": True,
        "source_command": "show processes cpu",
    },
    {
        "key": "platform-low-memory",
        "title": "Processor memory low",
        "family": "Platform",
        "checks": "Free processor memory at/below the critical percentage — MALLOCFAIL risk under the "
                  "table churn a migration adds.",
        "healthy_value": "band == OK (free memory above the low threshold)",
        "threshold": "mem_free_pct <= 10 (Hot); <= 20 (Elevated)",
        "cited_fields": ["platform_health.per_device[].mem_free_pct", "platform_health.per_device[].band"],
        "abstains_when": "capacity commands not collected (per_device.collected == False -> band == Unknown)",
        "evidence_gated": True,
        "source_command": "show processes memory",
    },
    # ---- Capacity headroom (analyze.compute_capacity / snap['capacity']) -----------------------------
    {
        "key": "capacity-port-headroom",
        "title": "Port utilization headroom",
        "family": "Capacity",
        "checks": "Per-device switched-port utilization (active vs total ports) — how much access "
                  "capacity remains before the migration adds endpoints.",
        "healthy_value": "free_ports available (port_util well below 100%)",
        "threshold": None,
        "cited_fields": ["capacity[].port_util", "capacity[].free_ports", "capacity[].total_ports"],
        "abstains_when": "device physical inventory not collected (no capacity row emitted for the device)",
        "evidence_gated": True,
        "source_command": _src("L1", "show interface status"),
    },
    {
        "key": "capacity-poe-headroom",
        "title": "PoE power-budget headroom",
        "family": "Capacity",
        "checks": "Per-device PoE budget draw vs capacity — whether adding powered endpoints (phones/"
                  "APs/cameras) would exceed the power budget.",
        "healthy_value": "poe_remaining_w > 0 (poe_util below 100%)",
        "threshold": None,
        "cited_fields": ["capacity[].poe_util", "capacity[].poe_remaining_w", "capacity[].poe_capacity_w"],
        "abstains_when": "PoE inventory not collected for the device (no PoE capacity row emitted)",
        "evidence_gated": True,
        "source_command": "show power inline",
    },
    # ---- L2 hygiene: native VLAN 1 on trunks (analyze.compute_operational_drift False-health) --------
    {
        "key": "l2-native-vlan-1",
        "title": "Native VLAN 1 on operationally-trunking ports",
        "family": "Hygiene",
        "checks": f"An operationally-trunking port ({NATIVE1_OPS_BASIS}) carrying the default VLAN 1 as "
                  "the native (untagged) VLAN — a hygiene and VLAN-hopping exposure. Every live-trunking "
                  "port counts, host-facing trunks included (no inter-switch scoping). (The design gap's "
                  f"{NATIVE1_CFG_UNIT} count — {NATIVE1_CFG_BASIS} — is a deliberately different measure.)",
        "healthy_value": "a dedicated, unused native VLAN on every 802.1Q trunk",
        "threshold": "operationally trunking (trunk_status 'trunking'/'trnk-bndl') and trunk native VLAN == 1",
        "cited_fields": ["operational_drift[].category", "operational_drift[].title", "operational_drift[].devices"],
        "abstains_when": "device not collected, or trunk/switchport detail not captured for the port",
        "evidence_gated": True,
        "source_command": _src("Trunk", "show interface trunk"),
    },
    {
        "key": "l2-native-vlan-mismatch",
        "title": "Native-VLAN mismatch across a trunk",
        "family": "Hygiene",
        "checks": "The two ends of an inter-switch trunk disagree on the native (untagged) VLAN — a "
                  "silent L2 leak between the two VLANs.",
        "healthy_value": "both ends agree on the native VLAN",
        "threshold": None,
        "cited_fields": ["trunk_native[].a_native", "trunk_native[].b_native"],
        "abstains_when": "either end of the trunk was not collected (an un-collected far end is not evidence of agreement)",
        "evidence_gated": True,
        "source_command": _src("Trunk", "show interface trunk"),
    },
    # ---- Segmentation / L3 isolation (analyze.compute_segmentation -> snap['segmentation']) ----------
    {
        "key": "segmentation-flat-l3",
        "title": "Flat L3 (no VRF and no gateway ACLs)",
        "family": "Segmentation",
        "checks": "Gateways exist but every one sits in the global VRF with no applied ACL — a flat L3 "
                  "with no isolation between application domains.",
        "healthy_value": "a non-global VRF or a gateway ACL present",
        "threshold": "n_gateways > 0 AND distinct non-global VRFs == 0 AND n_with_acl == 0",
        "cited_fields": ["segmentation.gateway_acl.n_gateways", "segmentation.gateway_acl.n_with_acl",
                         "segmentation.vrfs"],
        "abstains_when": "no gateway SVIs collected (no gateway evidence -> the flat-L3 verdict is not assessable)",
        "evidence_gated": True,
        "source_command": _src("L3", "show ip route"),
    },
]


def compute_detector_schema() -> Dict[str, Any]:
    """Build the per-detector descriptor schema — a DECLARATIVE registry projected to the published
    shape. Pure, deterministic, offline; describes the detectors, it never re-runs them.

    Returns::

        {schema: "detector_schema/1",
         detectors: [{key, title, family, checks, healthy_value, threshold, cited_fields,
                      abstains_when, evidence_gated, source_command}, ...],
         summary: {n_detectors, n_with_threshold, n_evidence_gated, families: {family: count}}}
    """
    from collections import Counter

    detectors: List[Dict[str, Any]] = []
    for d in _DETECTOR_DESCRIPTORS:
        detectors.append({
            "key": d["key"],
            "title": d["title"],
            "family": d["family"],
            "checks": d["checks"],
            "healthy_value": d["healthy_value"],
            "threshold": d["threshold"],
            "cited_fields": list(d["cited_fields"]),
            "abstains_when": d["abstains_when"],
            "evidence_gated": bool(d.get("evidence_gated", False)),
            "source_command": d["source_command"],
        })

    n_with_threshold = sum(1 for d in detectors if d["threshold"] is not None)
    n_evidence_gated = sum(1 for d in detectors if d["evidence_gated"])
    families = dict(sorted(Counter(d["family"] for d in detectors).items()))
    note = ("Each row DESCRIBES a live detector, grounded in its source; it does not re-run detection. "
            "'abstains_when' is the coverage-honest guard — the condition under which the detector "
            "ABSTAINS (maps to ssot.abstention_reason's 'not_collected') instead of passing, so a "
            "blind spot never reads as healthy. It is never empty for an evidence-gated detector.")
    return {
        "schema": SCHEMA,
        "detectors": detectors,
        "summary": {
            "n_detectors": len(detectors),
            "n_with_threshold": n_with_threshold,
            "n_evidence_gated": n_evidence_gated,
            "families": families,
            "note": note,
        },
    }
