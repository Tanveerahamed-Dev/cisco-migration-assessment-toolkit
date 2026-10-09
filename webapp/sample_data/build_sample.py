"""Generate a richer, engine-computed demo snapshot for AssessHub.

The bundled `tests/golden/snapshot.json` is only 3 devices — fine for tests, thin for a demo. This
script builds a believable **2-core + many-access** campus by CLONING the proven synthetic fixtures
(`tests/synthetic_fixtures.py`, imported read-only — never modified, so the golden contract is safe),
varying each access switch (which core it homes to, native-VLAN hygiene, platform/EoL tier), then runs
the **real** offline pipeline (`COLLECT_PARSE … --no-collect`) so every health score, punch-list item,
keystone, topology link, and lifecycle band is genuinely computed by the engine — not faked.

Output: webapp/sample_data/sample_fleet.snapshot.json

Run:  python webapp/sample_data/build_sample.py [--check] [--out PATH]
"""

from __future__ import annotations

import contextlib
import copy
import json
import os
import shutil
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(os.path.dirname(_HERE))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "tests"))

import synthetic_fixtures as fx          # noqa: E402  (read-only template source)
import COLLECT_PARSE_V3_23_0 as cp       # noqa: E402  (the real pipeline entry point)

OUT = os.path.join(_HERE, "sample_fleet.snapshot.json")
# Stable evidence timestamp for the demo fixture. The real pipeline recovers this from the
# collection-directory stamp, which makes lifecycle bands and every derived design/executive section
# deterministic instead of silently exempting them from --check.
_SAMPLE_COLLECTION_STAMP = "20260807_000000"
# The demo's statement of registry health ("is the retained EoL / OUI / port evidence fresh?") is judged at
# the demo's OWN evidence date -- the same seam (registry_integrity.datetime) and the same rule as the golden
# harness (tests/test_pipeline_golden.py, _GOLDEN_REGISTRY_CLOCK). Judged against the wall clock, a
# regeneration after the retained registries' freshness window would flip every authority to stale and
# cascade into assessment_integrity: the demo would change with the calendar, not with the engine.
_SAMPLE_REGISTRY_CLOCK = (f"{_SAMPLE_COLLECTION_STAMP[0:4]}-{_SAMPLE_COLLECTION_STAMP[4:6]}-"
                          f"{_SAMPLE_COLLECTION_STAMP[6:8]}T00:00:00+00:00")
# That pin is also the demo's collection INSTANT: main() has the engine read the stamp in the pinned clock's own
# zone (_collection_zone), so the published collected_at is exactly _SAMPLE_REGISTRY_CLOCK on every host. Read
# in the regenerating host's local zone instead, it took that host's UTC offset (+03:00 on one workstation,
# +00:00 on a hosted runner) and the demo's bytes changed with the machine, not with the engine.


@contextlib.contextmanager
def _registry_clock(iso: str):
    """Pin the one clock every registry freshness read goes through for one in-process pipeline run. The
    registries' per-process caches are cleared on BOTH sides, so no verdict computed under another clock is
    reused inside the run, and none computed under the pin outlives it."""
    from cisco_toolkit import eoldb, ouidb, portdb
    from cisco_toolkit import registry_integrity as ri

    caches = (eoldb._runtime_source_proof, ouidb._registry, portdb._registry)
    real = ri.datetime
    pinned = real.fromisoformat(iso)

    class _RegistryClock(real):
        @classmethod
        def now(cls, tz=None):
            return pinned if tz is None else pinned.astimezone(tz)  # exactly the golden harness's pin

    for cache in caches:
        cache.cache_clear()
    ri.datetime = _RegistryClock
    try:
        yield pinned
    finally:
        ri.datetime = real
        for cache in caches:
            cache.cache_clear()


@contextlib.contextmanager
def _collection_zone(tz):
    """Declare the zone of the demo's collection-directory stamp for one in-process pipeline run: the engine
    states collected_at in `tz` (COLLECT_PARSE `_COLLECTION_TZ`) instead of the regenerating host's local
    zone, and the engine's own field default is restored afterwards."""
    real = cp._COLLECTION_TZ
    cp._COLLECTION_TZ = tz
    try:
        yield tz
    finally:
        cp._COLLECTION_TZ = real

# (model line for `show version`, roughly how the EoL KB bands it) — gives lifecycle variety.
_PLATFORMS = [
    ("Cisco IOS Software, C2960X Software (C2960X-UNIVERSALK9-M), Version 15.2(7)E3\n"
     "cisco WS-C2960X-48FPD-L (APM86XXX) processor (revision A0)\n"
     "System serial number            : {sn}\nModel number                    : WS-C2960X-48FPD-L\n"),
    ("Cisco IOS Software, C3560 Software (C3560-IPSERVICESK9-M), Version 12.2(55)SE\n"
     "cisco WS-C3560-48TS (PowerPC405) processor\n"
     "System serial number            : {sn}\nModel number                    : WS-C3560-48TS\n"),
    ("Cisco IOS-XE Software, Catalyst L3 Switch Software (CAT9K_IOSXE), Version 17.09.04\n"
     "cisco C9300-48P (X86) processor\n"
     "System serial number            : {sn}\nModel number                    : C9300-48P\n"),
]


def _clone_access(name: str, idx: int, core: str, core_ip: str, core_port: str,
                  core_platform: str, native: str, plat_i: int,
                  carry_vlan30: bool = True, errdisable: bool = False) -> dict:
    """Clone the access1 template, re-homing its uplink to `core` and varying its health profile.

    The engine's score is driven by a few conditions we can toggle here to spread the bands:
      * carrying VLAN 30 (the sole-gateway, no-FHRP VLAN) over a single fiber -> CL-01 Critical (-18);
      * an err-disabled port -> an L1 fault deduction (and an L1-on-gateway cross-layer if applicable);
      * a non-1 trunk native VLAN -> a native-VLAN mismatch finding.
    Dropping VLAN 30 lifts a switch toward Fair/Good; stacking the faults pushes it to Critical.
    """
    d = copy.deepcopy(fx._ACCESS1)
    sn = f"FOC{2300 + idx}A{idx:03d}"
    d["show version"] = _PLATFORMS[plat_i].format(sn=sn)

    # Re-point the uplink CDP entry at the assigned core (device id, ip, platform, remote port).
    cdp = d["show cdp neighbors detail"]
    cdp = cdp.replace("Device ID: core1.lab", f"Device ID: {core}.lab", 1)
    cdp = cdp.replace("IP address: 10.0.99.1", f"IP address: {core_ip}", 1)
    cdp = cdp.replace("Platform: cisco WS-C3850-24T,", f"Platform: cisco {core_platform},", 1)
    cdp = cdp.replace("Port ID (outgoing port): GigabitEthernet1/0/24",
                      f"Port ID (outgoing port): {core_port}", 1)
    d["show cdp neighbors detail"] = cdp

    if native != "1":
        d["show interfaces trunk"] = d["show interfaces trunk"].replace(
            "trunking      1", f"trunking      {native}")

    if not carry_vlan30:
        # Drop the server VLAN entirely: trunk no longer carries 30, the server access port moves to
        # VOICE(20), and 30 disappears from the bridge -> no single-fiber-to-sole-gateway exposure.
        d["show interfaces trunk"] = d["show interfaces trunk"].replace("Gi0/1       10,20,30", "Gi0/1       10,20")
        d["show interfaces switchport"] = (d["show interfaces switchport"]
            .replace("Trunking VLANs Enabled: 10,20,30", "Trunking VLANs Enabled: 10,20")
            .replace("Access Mode VLAN: 30 (SERVERS)", "Access Mode VLAN: 20 (VOICE)"))
        d["show interface status"] = d["show interface status"].replace(
            "Gi0/10    srv-backup         connected    30", "Gi0/10    srv-backup         connected    20")
        d["show running-config | section ^interface"] = d["show running-config | section ^interface"].replace(
            " switchport access vlan 30", " switchport access vlan 20")
        d["show vlan brief"] = d["show vlan brief"].replace(
            "30   SERVERS                          active    Gi0/10", "30   SERVERS                          active")
        d["show mac address-table"] = d["show mac address-table"].replace(
            "  30    aabb.ccdd.ee10    DYNAMIC     Gi0/10\n", "")

    if errdisable:
        # Two err-disabled ports — a heavier L1 fault footprint to push a single-fiber switch to Critical.
        d["show interface status"] = d["show interface status"].rstrip("\n") + (
            "\nGi0/11    faulty-uplink      err-disabled 10           auto  auto  10/100/1000BaseTX"
            "\nGi0/12    flapping-port      err-disabled 10           auto  auto  10/100/1000BaseTX\n")
        for port, errs, crc in (("0/11", 203, 31), ("0/12", 451, 77)):
            d["show interfaces"] = d["show interfaces"].rstrip("\n") + (
                f"\nGigabitEthernet{port} is down, line protocol is down (err-disabled)\n"
                "  MTU 1500 bytes, BW 1000000 Kbit/sec, DLY 10 usec\n"
                "  Auto-duplex, Auto-speed, media type is 10/100/1000BaseTX\n"
                "  Last input never, output never, output hang never\n"
                f"     {errs} input errors, {crc} CRC, 0 frame, 0 overrun, 0 ignored\n"
                "     Total output drops: 0\n")
    return d


# --------------------------------------------------------------------------- #
# Redundant pod — a properly-built dual-homed pod so the demo also populates the Good/Excellent bands.
# A cross-linked distribution PAIR (HSRP on every pod VLAN) with access switches dual-homed to BOTH
# dist switches: no switch is a sole L2 transit and every gateway is redundant, so the engine has
# nothing to deduct beyond a leaf's own attached endpoints. This is the redundancy the single-homed
# star deliberately lacks (see the access archetypes above) — exactly what lifts a switch past Fair.
# --------------------------------------------------------------------------- #
def _sw_trunk(port: str, vlans: str = "40,41", native: str = "1") -> str:
    return (f"Name: {port}\nSwitchport: Enabled\nAdministrative Mode: trunk\n"
            f"Operational Mode: trunk\nAccess Mode VLAN: 1 (default)\n"
            f"Trunking Native Mode VLAN: {native} (default)\nTrunking VLANs Enabled: {vlans}\n\n")


def _sw_access(port: str, vlan: int, vname: str) -> str:
    return (f"Name: {port}\nSwitchport: Enabled\nAdministrative Mode: static access\n"
            f"Operational Mode: static access\nAccess Mode VLAN: {vlan} ({vname})\n"
            f"Trunking Native Mode VLAN: 1 (default)\n\n")


def _pod_dist(name: str, peer: str, peer_ip: str, svi_octet: int, hsrp_pri: int, hsrp_state: str,
              peer_svi_octet: int, up_core: str, up_core_ip: str, up_core_plat: str,
              up_local: str, up_remote: str) -> dict:
    """One distribution switch of the redundant pair: Po1 cross-link to its peer, an uplink to a core,
    two downlinks to the dual-homed pod-access switches, and HSRP SVIs for VLAN 40/41."""
    return {
        "show version": (f"Cisco IOS-XE Software, Catalyst L3 Switch Software (CAT9K_IOSXE), Version 17.09.04\n"
                         f"cisco C9300-48P (X86) processor\nSystem serial number        : FCW244{svi_octet}D0{svi_octet:02d}\n"
                         f"Model number                : C9300-48P\n"),
        "show interface status": (
            "Port      Name               Status       Vlan       Duplex  Speed Type\n"
            f"Gi1/0/1   to-{peer}-a         connected    trunk        full  1000  10/100/1000BaseTX\n"
            f"Gi1/0/2   to-{peer}-b         connected    trunk        full  1000  10/100/1000BaseTX\n"
            f"Gi1/0/3   to-{up_core}           connected    trunk        full  1000  1000BaseLX SFP\n"
            "Gi1/0/10  to-podacc1         connected    trunk        full  1000  10/100/1000BaseTX\n"
            "Gi1/0/11  to-podacc2         connected    trunk        full  1000  10/100/1000BaseTX\n"
            f"Po1       to-{peer}           connected    trunk        full  2000\n"),
        "show etherchannel summary": (
            "Flags:  D - down        P - bundled in port-channel\n        I - stand-alone s - suspended\n"
            "Number of channel-groups in use: 1\nNumber of aggregators:           1\n\n"
            "Group  Port-channel  Protocol    Ports\n"
            "------+-------------+-----------+-----------------------------------------------\n"
            "1      Po1(SU)         LACP      Gi1/0/1(P)    Gi1/0/2(P)\n"),
        "show interfaces switchport": (_sw_trunk("Gi1/0/3") + _sw_trunk("Gi1/0/10")
                                       + _sw_trunk("Gi1/0/11") + _sw_trunk("Po1")),
        "show interfaces trunk": (
            "Port        Mode             Encapsulation  Status        Native vlan\n"
            "Gi1/0/3     on               802.1q         trunking      1\n"
            "Gi1/0/10    on               802.1q         trunking      1\n"
            "Gi1/0/11    on               802.1q         trunking      1\n"
            "Po1         on               802.1q         trunking      1\n\n"
            "Port        Vlans allowed on trunk\n"
            "Gi1/0/3     40,41\nGi1/0/10    40,41\nGi1/0/11    40,41\nPo1         40,41\n"),
        "show running-config | section ^interface": (
            "interface GigabitEthernet1/0/1\n description to-peer-a\n switchport mode trunk\n channel-group 1 mode active\n"
            "interface GigabitEthernet1/0/2\n description to-peer-b\n switchport mode trunk\n channel-group 1 mode active\n"
            f"interface GigabitEthernet1/0/3\n description to-{up_core}\n switchport trunk encapsulation dot1q\n switchport mode trunk\n"
            "interface GigabitEthernet1/0/10\n description to-podacc1\n switchport mode trunk\n"
            "interface GigabitEthernet1/0/11\n description to-podacc2\n switchport mode trunk\n"
            "interface Port-channel1\n description to-peer\n switchport mode trunk\n mtu 9216\n"
            f"interface Vlan40\n description POD-USERS\n ip address 10.0.40.{svi_octet} 255.255.255.0\n"
            f" standby 40 ip 10.0.40.1\n standby 40 priority {hsrp_pri}\n standby 40 preempt\n"
            f"interface Vlan41\n description POD-VOICE\n ip address 10.0.41.{svi_octet} 255.255.255.0\n"
            f" standby 41 ip 10.0.41.1\n standby 41 priority {hsrp_pri}\n standby 41 preempt\n"),
        "show standby brief": (
            "                     P indicates configured to preempt.\n                     |\n"
            "Interface   Grp  Pri P State    Active          Standby         Virtual IP\n"
            f"Vl40        40   {hsrp_pri} P {hsrp_state:8} 10.0.40.{peer_svi_octet if hsrp_state.startswith('Stand') else svi_octet}"
            f"        10.0.40.{peer_svi_octet}       10.0.40.1\n"
            f"Vl41        41   {hsrp_pri} P {hsrp_state:8} 10.0.41.{peer_svi_octet if hsrp_state.startswith('Stand') else svi_octet}"
            f"        10.0.41.{peer_svi_octet}       10.0.41.1\n"),
        "show vlan brief": (
            "VLAN Name                             Status    Ports\n"
            "---- -------------------------------- --------- -------------------------------\n"
            "40   POD-USERS                        active\n41   POD-VOICE                        active\n"),
        "show ip interface brief": (
            "Interface              IP-Address      OK? Method Status                Protocol\n"
            f"Vlan40                 10.0.40.{svi_octet}       YES NVRAM  up                    up\n"
            f"Vlan41                 10.0.41.{svi_octet}       YES NVRAM  up                    up\n"),
        "show cdp neighbors detail": (
            f"-------------------------\nDevice ID: {peer}.lab\nEntry address(es):\n  IP address: {peer_ip}\n"
            "Platform: cisco C9300-48P,  Capabilities: Router Switch\n"
            "Interface: Port-channel1,  Port ID (outgoing port): Port-channel1\nHoldtime : 160 sec\n"
            f"-------------------------\nDevice ID: {up_core}.lab\nEntry address(es):\n  IP address: {up_core_ip}\n"
            f"Platform: cisco {up_core_plat},  Capabilities: Router Switch\n"
            f"Interface: {up_local},  Port ID (outgoing port): {up_remote}\nHoldtime : 150 sec\n"
            f"-------------------------\nDevice ID: podacc1.lab\nEntry address(es):\n  IP address: 10.0.99.52\n"
            "Platform: cisco C9300-24T,  Capabilities: Switch\n"
            f"Interface: GigabitEthernet1/0/10,  Port ID (outgoing port): GigabitEthernet0/{1 if name == 'dist1' else 2}\nHoldtime : 150 sec\n"
            f"-------------------------\nDevice ID: podacc2.lab\nEntry address(es):\n  IP address: 10.0.99.53\n"
            "Platform: cisco C9300-24T,  Capabilities: Switch\n"
            f"Interface: GigabitEthernet1/0/11,  Port ID (outgoing port): GigabitEthernet0/{1 if name == 'dist1' else 2}\nHoldtime : 150 sec\n"),
    }


def _pod_access(name: str, dist_remote: str, u1_mac: str, u2_mac: str) -> dict:
    """A pod-access switch dual-homed to BOTH dist switches (Gi0/1->dist1, Gi0/2->dist2), with its
    user/voice endpoints in the HSRP-redundant pod VLANs. `dist_remote` is the dist downlink port."""
    return {
        "show version": (f"Cisco IOS-XE Software, Catalyst L3 Switch Software (CAT9K_IOSXE), Version 17.06.05\n"
                         f"cisco C9300-24T (X86) processor\nSystem serial number        : FCW2455{u1_mac[-2:]}\n"
                         f"Model number                : C9300-24T\n"),
        "show interface status": (
            "Port      Name               Status       Vlan       Duplex  Speed Type\n"
            "Gi0/1     uplink-to-dist1    connected    trunk        full  1000  1000BaseLX SFP\n"
            "Gi0/2     uplink-to-dist2    connected    trunk        full  1000  1000BaseLX SFP\n"
            "Gi0/3     pod-user-pc        connected    40           full  1000  10/100/1000BaseTX\n"
            "Gi0/4     pod-phone          connected    41           full  100   10/100/1000BaseTX\n"),
        "show interfaces switchport": (_sw_trunk("Gi0/1") + _sw_trunk("Gi0/2")
                                       + _sw_access("Gi0/3", 40, "POD-USERS") + _sw_access("Gi0/4", 41, "POD-VOICE")),
        "show interfaces trunk": (
            "Port        Mode             Encapsulation  Status        Native vlan\n"
            "Gi0/1       on               802.1q         trunking      1\nGi0/2       on               802.1q         trunking      1\n\n"
            "Port        Vlans allowed on trunk\nGi0/1       40,41\nGi0/2       40,41\n"),
        "show running-config | section ^interface": (
            "interface GigabitEthernet0/1\n description uplink-to-dist1\n switchport trunk encapsulation dot1q\n switchport mode trunk\n"
            "interface GigabitEthernet0/2\n description uplink-to-dist2\n switchport trunk encapsulation dot1q\n switchport mode trunk\n"
            "interface GigabitEthernet0/3\n description pod-user-pc\n switchport access vlan 40\n spanning-tree portfast\n"
            "interface GigabitEthernet0/4\n description pod-phone\n switchport access vlan 41\n spanning-tree portfast\n"),
        "show vlan brief": (
            "VLAN Name                             Status    Ports\n"
            "---- -------------------------------- --------- -------------------------------\n"
            "40   POD-USERS                        active    Gi0/3\n41   POD-VOICE                        active    Gi0/4\n"),
        "show ip interface brief": (
            "Interface              IP-Address      OK? Method Status                Protocol\n"
            "Vlan1                  unassigned      YES NVRAM  administratively down  down\n"),
        "show mac address-table": (
            "          Mac Address Table\n-------------------------------------------\n"
            "Vlan    Mac Address       Type        Ports\n----    -----------       --------    -----\n"
            f"  40    {u1_mac}    DYNAMIC     Gi0/3\n  41    {u2_mac}    DYNAMIC     Gi0/4\n"),
        "show cdp neighbors detail": (
            f"-------------------------\nDevice ID: dist1.lab\nEntry address(es):\n  IP address: 10.0.99.50\n"
            "Platform: cisco C9300-48P,  Capabilities: Router Switch\n"
            f"Interface: GigabitEthernet0/1,  Port ID (outgoing port): {dist_remote}\nHoldtime : 150 sec\n"
            f"-------------------------\nDevice ID: dist2.lab\nEntry address(es):\n  IP address: 10.0.99.51\n"
            "Platform: cisco C9300-48P,  Capabilities: Router Switch\n"
            f"Interface: GigabitEthernet0/2,  Port ID (outgoing port): {dist_remote}\nHoldtime : 150 sec\n"),
    }


def build_pod() -> tuple:
    """Return (pod_collections, core1_reciprocal_cdp, core2_reciprocal_cdp)."""
    pod = {
        "dist1": ("ios", _pod_dist("dist1", "dist2", "10.0.99.51", 2, 110, "Active", 3,
                                   "core1", "10.0.99.1", "WS-C3850-24T", "GigabitEthernet1/0/3", "GigabitEthernet1/0/40")),
        "dist2": ("ios", _pod_dist("dist2", "dist1", "10.0.99.50", 3, 100, "Standby", 2,
                                   "core2", "10.0.99.2", "N9K-C93180YC-EX", "GigabitEthernet1/0/3", "Ethernet1/20")),
        "podacc1": ("ios", _pod_access("podacc1", "GigabitEthernet1/0/10", "1111.2222.4001", "1111.2222.4101")),
        "podacc2": ("ios", _pod_access("podacc2", "GigabitEthernet1/0/11", "1111.2222.4002", "1111.2222.4102")),
    }
    core1_recip = ("-------------------------\nDevice ID: dist1.lab\nEntry address(es):\n  IP address: 10.0.99.50\n"
                   "Platform: cisco C9300-48P,  Capabilities: Router Switch\n"
                   "Interface: GigabitEthernet1/0/40,  Port ID (outgoing port): GigabitEthernet1/0/3\nHoldtime : 150 sec\n")
    core2_recip = ("----------------------------------------\nDevice ID: dist2.lab\n  IP address: 10.0.99.51\n"
                   "Platform: cisco C9300-48P,  Capabilities: Router Switch\n"
                   "Interface: Ethernet1/20,  Port ID (outgoing port): GigabitEthernet1/0/3\n")
    return pod, core1_recip, core2_recip


# Designed archetype mix (count, profile) so the fleet spans the full health-band spectrum rather than
# a monotonous block. Counts are tuned empirically against the engine's scoring.
_ARCHETYPES = (
    [dict(carry_vlan30=True, errdisable=False, native="1")] * 5     # single-fiber to the sole gateway -> Poor
    + [dict(carry_vlan30=False, errdisable=False, native="1")] * 6  # no VLAN-30 exposure              -> Fair
    + [dict(carry_vlan30=True, errdisable=True, native="99")] * 5   # stacked L1 faults + sole gateway -> Critical
)


def build_collections() -> dict:
    """hostname -> (platform, {command: output}) for a 2-core + many-access fleet with mixed health."""
    cols: dict = {
        "core1": ("ios", copy.deepcopy(fx._CORE1)),
        "core2": ("nxos", copy.deepcopy(fx._CORE2)),
        "access1": ("ios", copy.deepcopy(fx._ACCESS1)),
    }

    core1_cdp_extra, core2_cdp_extra = [], []
    for off, spec in enumerate(_ARCHETYPES):
        i = off + 2
        name = f"access{i}"
        ip = f"10.0.99.{i + 10}"
        homes_core1 = (i % 2 == 0)
        plat_i = i % len(_PLATFORMS)                      # rotate platform / EoL tier

        if homes_core1:
            core_port = f"GigabitEthernet1/0/{i + 24}"
            cols[name] = ("ios", _clone_access(name, i, "core1", "10.0.99.1", core_port,
                                               "WS-C3850-24T", spec["native"], plat_i,
                                               carry_vlan30=spec["carry_vlan30"], errdisable=spec["errdisable"]))
            core1_cdp_extra.append(
                f"-------------------------\nDevice ID: {name}.lab\n"
                f"Entry address(es):\n  IP address: {ip}\n"
                f"Platform: cisco WS-C2960X-48,  Capabilities: Switch\n"
                f"Interface: {core_port},  Port ID (outgoing port): GigabitEthernet0/1\n"
                f"Holdtime : 150 sec\n")
        else:
            core_port = f"Ethernet1/{i}"
            cols[name] = ("ios", _clone_access(name, i, "core2", "10.0.99.2", core_port,
                                               "N9K-C93180YC-EX", spec["native"], plat_i,
                                               carry_vlan30=spec["carry_vlan30"], errdisable=spec["errdisable"]))
            core2_cdp_extra.append(
                f"----------------------------------------\nDevice ID: {name}.lab\n"
                f"  IP address: {ip}\n"
                f"Platform: cisco WS-C2960X-48,  Capabilities: Switch\n"
                f"Interface: {core_port},  Port ID (outgoing port): GigabitEthernet0/1\n")

    # Add the redundant pod (dist pair + dual-homed access) and uplink it to both cores.
    pod, core1_pod_cdp, core2_pod_cdp = build_pod()
    cols.update(pod)
    core1_cdp_extra.append(core1_pod_cdp)
    core2_cdp_extra.append(core2_pod_cdp)

    # Splice the new spokes into the cores' CDP neighbour tables so the topology forms a 2-hub star.
    cols["core1"][1]["show cdp neighbors detail"] += "".join(core1_cdp_extra)
    cols["core2"][1]["show cdp neighbors detail"] += "".join(core2_cdp_extra)
    return _add_forwarding_substrate(cols)


# --------------------------------------------------------------------------- #
# Forwarding substrate — the routed evidence a multi-hop path decision needs.
#
# Without it only core1/core2 have a routing table, no collected route points at an address another
# collected host owns, and the dist pair has no running-config: every trace stops after one hop.
# The substrate turns the EXISTING dist1 Gi1/0/3 <-> core1 Gi1/0/40 cable into a routed /30 transit
# (10.0.140.0/30, OSPF point-to-point), gives dist1/dist2 their routing tables, OSPF adjacencies and a
# hardened running-config, and collects EIGRP/BGP on the dist pair as the output of switches that do
# not run them. It deliberately does NOT fabricate EIGRP/BGP adjacencies:
#   * `show ip eigrp neighbors` with no EIGRP AS configured prints nothing — a neighbor table captured
#     and empty (protocol_assessability -> captured_empty);
#   * `show ip bgp summary` with no `router bgp` prints IOS's no-process banner, `% BGP not active`
#     — NOT empty output (2026-09-27 refuter X3: the earlier empty capture was shaped to the consumer,
#     not taken from what a device emits). The engine reads that exact banner as its own `not_running`
#     assessability state (cisco_toolkit/analyze.py; cluster R1), positive evidence of no BGP process.
# core1 keeps its configured `router bgp 65001` as one Established upstream peer that has sent no
# prefixes — its table holds no BGP route, and the two captures agree. The peer is the upstream core1
# already defaults to (10.0.10.254 on Vlan10): a directly connected single-hop eBGP session, so the
# route under it is CONNECTED and survives the engine's route scoping (scope_routes keeps every
# connected route). An earlier multihop peer behind a static /32 was reached, on the snapshot Atlas
# Scope reads, only by the default route: scoping dropped the /32 (2026-09-27 verifier, E2R2-V2).
#
# The routes each table holds are the ones the configuration beside it would originate: core1 puts
# the Gi1/0/40 transit and Vlan10 (the inter-core home, below) in area 0 and brings its other connected
# VLANs into OSPF with its existing `redistribute connected`, so dist1/dist2 hold Vlan10 intra-area (`O`)
# and the voice/server VLANs as `O E2`; the dists' `O*E2` default exists because core1 now carries
# `default-information originate` (it has a static default). The new dist running-configs end with `end`,
# as a real IOS dump does, so the engine's capture-integrity guard reads them as whole.
#
# core1's own running-config keeps the fixtures' no-`end` convention (owner decision, phase 2.75), so
# the guard reads it as INCOMPLETE -- and beside it the substrate collects a configured, Established eBGP
# peer. The engine's BGP configured-peer baseline therefore cannot verify that peer against a
# configuration it cannot trust, and reads INDETERMINATE with one not-verified core1 row. That is the
# coverage-honest verdict for this collection, not a defect to be hidden by editing the capture; it is
# pinned, with its reason derived from the producers, in tests/test_sample_fleet_substrate.py.
#
# core1's FULL/DR OSPF neighbour core2 (router ID 10.0.99.2) used to sit on the L2 trunk
# Port-channel1 -- an adjacency that cannot form there, and whose link core1's table did not hold (the
# fixture's B1 seed). It now runs over Vlan10, an SVI BOTH cores already have (core1 10.0.10.2, core2
# 10.0.10.3, one /24) on a VLAN Po1 already carries: owner decision, phase 2.75 (verifier R2V-4),
# replacing an earlier dedicated transit VLAN that changed the move groups. Of the two SVIs the cores
# share, Vlan10 is the one an adjacency can hold FULL on: core1's Vlan20 carries the inbound
# VOICE_FILTER, whose closing `deny ip any any` drops OSPF hellos, and the fixture's own core1 log
# records exactly that Vlan20 adjacency going down on its dead timer. Each core only gains the OSPF
# enable on its existing Vlan10 stanza; HSRP, the trunk allow-lists and every other L2 capture are
# untouched. core2 -- which collects no neighbour table, so its OSPF stays not_collected -- holds what
# core1 originates into OSPF, learned over Vlan10. core2's `show ip route` keeps the fixture's own line
# convention (IOS-style code lines under the NX-OS header) so its existing entries are unchanged.
#
# Every CDP capture and every L2 capture of the cores is left byte-identical, including the deliberately
# disputed core1 Gi1/0/40 that both access16 and dist1 claim; so the cable map, move groups, wave
# sequencing and failure impact are unchanged (the cores were already one move group through VLAN
# 10/20). Only deep copies are edited: tests/synthetic_fixtures.py (the golden's source) is not.
# --------------------------------------------------------------------------- #
_ROUTE_CODES = ("Codes: L - local, C - connected, S - static, R - RIP, M - mobile, B - BGP\n"
                "       D - EIGRP, EX - EIGRP external, O - OSPF, IA - OSPF inter area\n"
                "       E1 - OSPF external type 1, E2 - OSPF external type 2\n")
_OSPF_NEIGHBOR_HDR = "Neighbor ID     Pri   State           Dead Time   Address         Interface\n"
# `show ip eigrp neighbors` on a switch with no EIGRP AS configured: the capture exists and holds
# nothing (protocol_assessability -> captured_empty).
_NO_EIGRP_AS = ""
# `show ip bgp summary` on IOS/IOS-XE with no `router bgp`: the no-process banner.
_NO_BGP_PROCESS = "% BGP not active\n"
# The inter-core OSPF home: the SVI both cores already have (see the block above).
_INTER_CORE_SVI = "Vlan10"
_CORE1_SVI_ADDR, _CORE2_SVI_ADDR = "10.0.10.2", "10.0.10.3"


def _replace_once(text: str, old: str, new: str) -> str:
    """Replace exactly one occurrence; a missing anchor is a build error, never a silent no-op."""
    if text.count(old) != 1:
        raise ValueError(f"substrate anchor must occur exactly once, found {text.count(old)}: {old!r}")
    return text.replace(old, new, 1)


def _dist_running_config(hostname: str, router_id: str, networks: tuple, passive: tuple = ()) -> str:
    return ("!\n"
            f"hostname {hostname}\n"
            "service password-encryption\n"
            "aaa new-model\n"
            "ip ssh version 2\n"
            "no ip http server\n"
            "no ip http secure-server\n"
            "ntp server 10.0.0.10\n"
            "logging host 10.0.0.20\n"
            "banner login ^C\n"
            "Authorized access only. Activity on this device is logged.\n"
            "^C\n"
            "ip access-list extended VTY_ACCESS\n"
            " permit tcp 10.0.99.0 0.0.0.255 any eq 22\n"
            " deny   ip any any\n"
            "!\n"
            "router ospf 1\n"
            f" router-id {router_id}\n"
            + "".join(f" passive-interface {p}\n" for p in passive)
            + "".join(f" network {n} area 0\n" for n in networks)
            + "!\n"
            "line vty 0 4\n"
            " access-class VTY_ACCESS in\n"
            " exec-timeout 10 0\n"
            " transport input ssh\n"
            "!\n"
            "end\n")


def _add_forwarding_substrate(cols: dict) -> dict:
    """Return a copy of `cols` with the routed core1<->dist1<->dist2 substrate (see the block above).
    The argument is never mutated."""
    cols = copy.deepcopy(cols)

    # ---- core1: Gi1/0/40 (the port dist1 already cables to) becomes the routed transit.
    c1 = cols["core1"][1]
    c1["show running-config | section ^interface"] += (
        "interface GigabitEthernet1/0/40\n description to-dist1\n no switchport\n"
        " ip address 10.0.140.1 255.255.255.252\n ip ospf network point-to-point\n ip ospf 1 area 0\n")
    c1["show ip route"] = _replace_once(
        c1["show ip route"],
        "      10.0.0.0/8 is variably subnetted, 8 subnets, 3 masks\n",
        "      10.0.0.0/8 is variably subnetted, 11 subnets, 4 masks\n")
    c1["show ip route"] = _replace_once(
        c1["show ip route"],
        "L        10.0.30.1/32 is directly connected, Vlan30\n",
        "L        10.0.30.1/32 is directly connected, Vlan30\n"
        "O        10.0.40.0/24 [110/2] via 10.0.140.2, 00:12:04, GigabitEthernet1/0/40\n"
        "O        10.0.41.0/24 [110/2] via 10.0.140.2, 00:12:04, GigabitEthernet1/0/40\n"
        "C        10.0.140.0/30 is directly connected, GigabitEthernet1/0/40\n"
        "L        10.0.140.1/32 is directly connected, GigabitEthernet1/0/40\n")
    c1["show ip ospf neighbor"] += (
        "10.0.99.50        0   FULL/  -        00:00:38    10.0.140.2      GigabitEthernet1/0/40\n")
    c1["show ip interface brief"] += (
        "GigabitEthernet1/0/40  10.0.140.1      YES NVRAM  up                    up\n")
    # core1 has a static default, and the dists' O*E2 default says core1 originates it into OSPF.
    c1["show running-config"] = _replace_once(
        c1["show running-config"],
        "router ospf 1\n redistribute bgp 65001 subnets\n redistribute connected\n",
        "router ospf 1\n redistribute bgp 65001 subnets\n redistribute connected\n default-information originate\n")
    # The configured `router bgp 65001` gets its one upstream peer: Established, no prefixes received
    # (core1 advertises the campus and keeps its static default), so the table rightly holds no B route.
    # The peer is the upstream core1 already defaults to, on its connected Vlan10 subnet (single hop).
    c1["show running-config"] = _replace_once(
        c1["show running-config"],
        "router bgp 65001\n",
        "router bgp 65001\n neighbor 10.0.10.254 remote-as 64500\n")
    c1["show ip bgp summary"] = (
        "BGP router identifier 10.0.99.1, local AS number 65001\n"
        "BGP table version is 7, main routing table version 7\n\n"
        "Neighbor        V           AS MsgRcvd MsgSent   TblVer  InQ OutQ Up/Down  State/PfxRcd\n"
        "10.0.10.254     4        64500     120     118        7    0    0 01:02:03        0\n")
    c1["show ip eigrp neighbors"] = _NO_EIGRP_AS       # no `router eigrp` in core1's configuration

    # ---- core1 <-> core2: the inter-core OSPF session moves off the L2 trunk Po1 onto Vlan10, an SVI both
    # cores already have on a VLAN Po1 already carries. Same neighbour (router ID 10.0.99.2), same FULL/DR
    # state (core2's router ID is the higher one, so it is the segment's DR); its link address is core2's
    # own Vlan10 address. Each core's existing Vlan10 stanza gains only the OSPF enable.
    c1["show ip ospf neighbor"] = _replace_once(
        c1["show ip ospf neighbor"],
        "10.0.99.2         1   FULL/DR         00:00:35    10.0.99.2       Port-channel1\n",
        f"10.0.99.2         1   FULL/DR         00:00:35    {_CORE2_SVI_ADDR}       {_INTER_CORE_SVI}\n")
    c1["show running-config | section ^interface"] = _replace_once(
        c1["show running-config | section ^interface"],
        f"interface {_INTER_CORE_SVI}\n description USERS\n ip address {_CORE1_SVI_ADDR} 255.255.255.0\n"
        " ip helper-address 10.0.40.10\n ip helper-address 10.0.40.11\n"
        " standby 10 ip 10.0.10.1\n standby 10 priority 110\n",
        f"interface {_INTER_CORE_SVI}\n description USERS\n ip address {_CORE1_SVI_ADDR} 255.255.255.0\n"
        " ip helper-address 10.0.40.10\n ip helper-address 10.0.40.11\n"
        " standby 10 ip 10.0.10.1\n standby 10 priority 110\n ip ospf 1 area 0\n")

    c2 = cols["core2"][1]
    c2["show running-config interface"] = _replace_once(
        c2["show running-config interface"],
        f"interface {_INTER_CORE_SVI}\n  description USERS\n  ip address {_CORE2_SVI_ADDR}/24\n"
        "  hsrp 10\n    ip 10.0.10.1\n",
        f"interface {_INTER_CORE_SVI}\n  description USERS\n  ip address {_CORE2_SVI_ADDR}/24\n"
        "  ip router ospf 1 area 0.0.0.0\n  hsrp 10\n    ip 10.0.10.1\n")  # NX-OS prints it before the hsrp sub-mode
    # What core1 originates into OSPF, learned over Vlan10: its default and redistributed server VLAN
    # (external type 2), the pod it learns from dist1 and the dist1 transit (intra-area). core2's own
    # connected Vlan10/20 beat core1's copies (administrative distance).
    c2["show ip route"] += (
        f"O*E2 0.0.0.0/0 [110/1] via {_CORE1_SVI_ADDR}, 00:12:04, {_INTER_CORE_SVI}\n"
        f"O E2 10.0.30.0/24 [110/20] via {_CORE1_SVI_ADDR}, 00:12:04, {_INTER_CORE_SVI}\n"
        f"O    10.0.40.0/24 [110/3] via {_CORE1_SVI_ADDR}, 00:12:04, {_INTER_CORE_SVI}\n"
        f"O    10.0.41.0/24 [110/3] via {_CORE1_SVI_ADDR}, 00:12:04, {_INTER_CORE_SVI}\n"
        f"O    10.0.140.0/30 [110/2] via {_CORE1_SVI_ADDR}, 00:12:04, {_INTER_CORE_SVI}\n")

    # ---- dist1: Gi1/0/3 goes from trunk to routed; OSPF to core1 (transit) and dist2 (Vlan40).
    d1 = cols["dist1"][1]
    d1["show interface status"] = _replace_once(
        d1["show interface status"],
        "Gi1/0/3   to-core1           connected    trunk        full  1000  1000BaseLX SFP\n",
        "Gi1/0/3   to-core1           connected    routed       full  1000  1000BaseLX SFP\n")
    d1["show interfaces switchport"] = _replace_once(
        d1["show interfaces switchport"], _sw_trunk("Gi1/0/3"), "Name: Gi1/0/3\nSwitchport: Disabled\n\n")
    d1["show interfaces trunk"] = _replace_once(
        d1["show interfaces trunk"], "Gi1/0/3     on               802.1q         trunking      1\n", "")
    d1["show interfaces trunk"] = _replace_once(d1["show interfaces trunk"], "Gi1/0/3     40,41\n", "")
    d1["show running-config | section ^interface"] = _replace_once(
        d1["show running-config | section ^interface"],
        "interface GigabitEthernet1/0/3\n description to-core1\n switchport trunk encapsulation dot1q\n"
        " switchport mode trunk\n",
        "interface GigabitEthernet1/0/3\n description to-core1\n no switchport\n"
        " ip address 10.0.140.2 255.255.255.252\n ip ospf network point-to-point\n")
    d1["show ip interface brief"] += (
        "GigabitEthernet1/0/3   10.0.140.2      YES NVRAM  up                    up\n")
    d1["show ip route"] = (
        _ROUTE_CODES
        + "Gateway of last resort is 10.0.140.1 to network 0.0.0.0\n\n"
        "O*E2  0.0.0.0/0 [110/1] via 10.0.140.1, 00:12:04, GigabitEthernet1/0/3\n"
        "      10.0.0.0/8 is variably subnetted, 9 subnets, 3 masks\n"
        "O        10.0.10.0/24 [110/2] via 10.0.140.1, 00:12:04, GigabitEthernet1/0/3\n"
        "O E2     10.0.20.0/24 [110/20] via 10.0.140.1, 00:12:04, GigabitEthernet1/0/3\n"
        "O E2     10.0.30.0/24 [110/20] via 10.0.140.1, 00:12:04, GigabitEthernet1/0/3\n"
        "C        10.0.40.0/24 is directly connected, Vlan40\n"
        "L        10.0.40.2/32 is directly connected, Vlan40\n"
        "C        10.0.41.0/24 is directly connected, Vlan41\n"
        "L        10.0.41.2/32 is directly connected, Vlan41\n"
        "C        10.0.140.0/30 is directly connected, GigabitEthernet1/0/3\n"
        "L        10.0.140.2/32 is directly connected, GigabitEthernet1/0/3\n")
    d1["show ip ospf neighbor"] = (
        _OSPF_NEIGHBOR_HDR
        + "10.0.99.1         0   FULL/  -        00:00:38    10.0.140.1      GigabitEthernet1/0/3\n"
        "10.0.99.51        1   FULL/BDR        00:00:35    10.0.40.3       Vlan40\n")
    d1["show ip eigrp neighbors"] = _NO_EIGRP_AS
    d1["show ip bgp summary"] = _NO_BGP_PROCESS
    d1["show running-config"] = _dist_running_config(
        "dist1", "10.0.99.50", ("10.0.40.0 0.0.1.255", "10.0.140.0 0.0.0.3"), passive=("Vlan41",))

    # ---- dist2: its uplink to core2 stays an L2 trunk; it routes toward the core via dist1 on Vlan40,
    # so the HSRP-standby ingress for a pod source is modelled the same way as the active one.
    d2 = cols["dist2"][1]
    d2["show ip route"] = (
        _ROUTE_CODES
        + "Gateway of last resort is 10.0.40.2 to network 0.0.0.0\n\n"
        "O*E2  0.0.0.0/0 [110/1] via 10.0.40.2, 00:12:04, Vlan40\n"
        "      10.0.0.0/8 is variably subnetted, 8 subnets, 3 masks\n"
        "O        10.0.10.0/24 [110/3] via 10.0.40.2, 00:12:04, Vlan40\n"
        "O E2     10.0.20.0/24 [110/20] via 10.0.40.2, 00:12:04, Vlan40\n"
        "O E2     10.0.30.0/24 [110/20] via 10.0.40.2, 00:12:04, Vlan40\n"
        "C        10.0.40.0/24 is directly connected, Vlan40\n"
        "L        10.0.40.3/32 is directly connected, Vlan40\n"
        "C        10.0.41.0/24 is directly connected, Vlan41\n"
        "L        10.0.41.3/32 is directly connected, Vlan41\n"
        "O        10.0.140.0/30 [110/2] via 10.0.40.2, 00:12:04, Vlan40\n")
    d2["show ip ospf neighbor"] = (
        _OSPF_NEIGHBOR_HDR
        + "10.0.99.50        1   FULL/DR         00:00:35    10.0.40.2       Vlan40\n")
    d2["show ip eigrp neighbors"] = _NO_EIGRP_AS
    d2["show ip bgp summary"] = _NO_BGP_PROCESS
    d2["show running-config"] = _dist_running_config(
        "dist2", "10.0.99.51", ("10.0.40.0 0.0.1.255",), passive=("Vlan41",))
    return cols


def _write_collection(root: str, cols: dict) -> None:
    """Write every capture as its exact UTF-8 text with LF line endings on EVERY platform. The engine reads
    each capture's raw bytes (cisco_toolkit/input_custody.read_bytes) and its strict protocol owners hash
    them into the snapshot's source receipts, so a text-mode open() that translated "\\n" to the host's
    os.linesep (CRLF on Windows) made those receipts -- and the demo's bytes -- depend on the regenerating
    machine. This is the same LF rule tests/synthetic_fixtures.write_collection applies to the golden."""
    for hostname, (_plat, outputs) in cols.items():
        d = os.path.join(root, hostname)
        os.makedirs(d, exist_ok=True)
        for cmd, text in outputs.items():
            with open(os.path.join(d, fx.cmd_filename(cmd)), "w", encoding="utf-8", newline="\n") as f:
                f.write(text)


# --------------------------------------------------------------------------- #
# W59 PR-1: the demo's SSH session records. Built by the REAL producer (cisco_toolkit.ssh_session.build_record /
# render_record, the bytes the collector writes) from observation snapshots shaped exactly like the sink's, so
# the sample exercises the engine's sealed-sidecar path end to end. One library for the whole run -- the shipped
# Atlas as of W59 PR-1 (paramiko 4.0.0 / netmiko 4.7.0, whose stock tables still permit SHA-1) -- so the three
# records are mutually consistent:
#   access4  (12.2 C3560): offers only SHA-1-class kex/host key -> negotiated SHA-1 WITHOUT opt-in (legacy_sha1)
#   core1:                 offers curve25519 / rsa-sha2-512      -> modern
#   edge1:                 a FOLDER WITH ONLY THE RECORD (no captures): offers only the RFC 8731 name
#                          curve25519-sha256 + a PQ hybrid, which paramiko 4.0.0 does not implement -> refused
#                          (refused_unsupported_modern: a collector gap, not a device weakness)
# SHA-1 algorithm names come from the vocabulary owner, never restated here.
# --------------------------------------------------------------------------- #
_SSH_EXTRA_DEVICE = {"hostname": "edge1", "ip": "10.0.99.240", "platform": "ios"}


def _paramiko4_client_tables(S) -> dict:
    """paramiko 4.0.0's stock client preference lists (transport.py), SHA-1 entries from the vocabulary."""
    g14_sha1, gex_sha1 = S.LEGACY_SHA1_TIER_KEX
    g1_sha1 = next(n for n in sorted(S.SHA1_KEX_NAMES) if n not in S.LEGACY_SHA1_TIER_KEX)
    rsa_sha1 = S.LEGACY_SHA1_TIER_HOST_KEYS[0]
    kex = ["curve25519-sha256@libssh.org", "ecdh-sha2-nistp256", "ecdh-sha2-nistp384", "ecdh-sha2-nistp521",
           "diffie-hellman-group16-sha512", "diffie-hellman-group-exchange-sha256",
           "diffie-hellman-group14-sha256", gex_sha1, g14_sha1, g1_sha1]
    plain_keys = ["ssh-ed25519", "ecdsa-sha2-nistp256", "ecdsa-sha2-nistp384", "ecdsa-sha2-nistp521",
                  "rsa-sha2-512", "rsa-sha2-256", rsa_sha1]
    host_key = plain_keys + [f"{k}-cert-v01@openssh.com" for k in plain_keys]
    cipher = ["aes128-ctr", "aes192-ctr", "aes256-ctr", "aes128-cbc", "aes192-cbc", "aes256-cbc", "3des-cbc",
              "aes128-gcm@openssh.com", "aes256-gcm@openssh.com"]
    sha1_mac, sha1_96 = sorted(n for n in S.SHA1_MACS if "etm" not in n)
    md5_mac, md5_96 = sorted(n for n in S.MD5_MACS if "etm" not in n)
    mac = ["hmac-sha2-256", "hmac-sha2-512", "hmac-sha2-256-etm@openssh.com", "hmac-sha2-512-etm@openssh.com",
           sha1_mac, md5_mac, sha1_96, md5_96]
    return {"kex": kex, "host_key": host_key, "cipher": cipher, "mac": mac}


def _ssh_session_records() -> dict:
    """hostname -> exact sidecar bytes."""
    from cisco_toolkit import ssh_session as S

    lib = S.library_block(paramiko_version="4.0.0", netmiko_version="4.7.0", transport_class="ObservedTransport",
                          default_permits_sha1=True)
    client = _paramiko4_client_tables(S)
    g14_sha1 = S.LEGACY_SHA1_TIER_KEX[0]
    rsa_sha1 = S.LEGACY_SHA1_TIER_HOST_KEYS[0]
    sha1_mac = sorted(n for n in S.SHA1_MACS if "etm" not in n)[0]
    legacy_server = {"kex": [g14_sha1], "host_key": [rsa_sha1], "cipher_c2s": ["aes128-cbc", "aes256-ctr"],
                     "cipher_s2c": ["aes128-cbc", "aes256-ctr"], "mac_c2s": [sha1_mac], "mac_s2c": [sha1_mac]}
    legacy_obs = {"kexinit": True, "newkeys": True, "server": legacy_server, "client": client,
                  "negotiated": {"kex": g14_sha1, "kex_hash_bytes": 20, "dh_group_bits": 2048,
                                 "host_key_algorithm": rsa_sha1, "cipher_c2s": "aes256-ctr",
                                 "cipher_s2c": "aes256-ctr", "mac_c2s": sha1_mac, "mac_s2c": sha1_mac,
                                 "strict_kex": False, "server_software": "SSH-1.99-Cisco-1.25"},
                  "engine_name_agrees": True, "group_size_agrees": True, "dropped": 0}
    modern_server = {"kex": ["curve25519-sha256", "curve25519-sha256@libssh.org", "ecdh-sha2-nistp256",
                             "diffie-hellman-group14-sha256", "kex-strict-s-v00@openssh.com"],
                     "host_key": ["rsa-sha2-512", "rsa-sha2-256"], "cipher_c2s": ["aes256-gcm@openssh.com",
                                                                               "aes256-ctr"],
                     "cipher_s2c": ["aes256-gcm@openssh.com", "aes256-ctr"], "mac_c2s": ["hmac-sha2-256"],
                     "mac_s2c": ["hmac-sha2-256"]}
    modern_obs = {"kexinit": True, "newkeys": True, "server": modern_server, "client": client,
                  "negotiated": {"kex": "curve25519-sha256@libssh.org", "kex_hash_bytes": 32, "dh_group_bits": None,
                                 "host_key_algorithm": "rsa-sha2-512", "cipher_c2s": "aes256-ctr",
                                 "cipher_s2c": "aes256-ctr", "mac_c2s": "hmac-sha2-256", "mac_s2c": "hmac-sha2-256",
                                 "strict_kex": True, "server_software": "SSH-2.0-Cisco-1.25"},
                  "engine_name_agrees": None, "group_size_agrees": None, "dropped": 0}
    gap_server = {"kex": ["mlkem768x25519-sha256", "curve25519-sha256", "kex-strict-s-v00@openssh.com"],
                  "host_key": ["ssh-ed25519", "rsa-sha2-512"], "cipher_c2s": ["aes256-gcm@openssh.com"],
                  "cipher_s2c": ["aes256-gcm@openssh.com"], "mac_c2s": ["hmac-sha2-256-etm@openssh.com"],
                  "mac_s2c": ["hmac-sha2-256-etm@openssh.com"]}
    gap_obs = {"kexinit": True, "newkeys": False, "server": gap_server, "client": client, "negotiated": None,
               "engine_name_agrees": None, "group_size_agrees": None, "dropped": 0}

    class _IncompatiblePeer(Exception):
        """Stand-in carrying paramiko's exception class NAME (the classifier matches by name)."""

    _IncompatiblePeer.__name__ = "IncompatiblePeer"
    observation = S.SessionObservation()
    observation.server, observation.client, observation.kexinit_seen = gap_server, client, True
    refusal = S.classify_failure(_IncompatiblePeer("Incompatible ssh peer (no acceptable kex algorithm)"),
                                 observation)
    default_consent = S.consent_for({}, None)
    records = {
        "access4": S.build_record(outcome="established", consent=default_consent, library=lib, attempts=1,
                                  observation=legacy_obs),
        "core1": S.build_record(outcome="established", consent=default_consent, library=lib, attempts=1,
                                observation=modern_obs),
        _SSH_EXTRA_DEVICE["hostname"]: S.build_record(
            outcome="negotiation_refused", consent=default_consent, library=lib, attempts=1,
            observation=gap_obs, refusal=refusal, failure_class="NetmikoTimeoutException"),
    }
    out = {}
    for host, record in records.items():
        errors = S.validate_record(record)
        if errors:
            raise SystemExit(f"demo SSH session record for {host} fails its schema: {errors}")
        out[host] = S.render_record(record)
    return out


def _write_ssh_session_records(root: str) -> None:
    """The sidecars, exact LF bytes (render_record is canonical ASCII + LF), beside each device's captures."""
    from cisco_toolkit import ssh_session as S

    for host, data in _ssh_session_records().items():
        d = os.path.join(root, host)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, S.SIDECAR_FILENAME), "wb") as f:
            f.write(data)


def _make_template(path: str) -> None:
    from openpyxl import Workbook
    wb = Workbook()
    wb.active.title = "Interface Data"
    wb.active.append(["Hostname", "Port", "Status"])
    wb.save(path)


# The synthetic collection timestamp above freezes all date-relative lifecycle/design derivations.
# Exclude only the genuine run wall-clock; dropping whole semantic sections made --check approve stale
# customer-facing wording in exactly those sections.
_VOLATILE_TOP = ("generated_at",)


def _strip_volatile(snap: dict) -> dict:
    out = {k: v for k, v in (snap or {}).items() if k not in _VOLATILE_TOP}
    if isinstance(out.get("attestation"), dict):
        out["attestation"] = {k: v for k, v in out["attestation"].items() if k != "generated_at"}
    # data_authorities is NOT volatile: main() judges registry health at the demo's evidence date
    # (_registry_clock), so every registry field -- source_age_days included -- is a pure function of the
    # pin and a drift in it is real staleness, exactly as in the golden harness.
    return out


def _freshness_drift(fresh: dict, committed_path: str):
    """Top-level sections whose committed demo copy differs from a fresh engine build (volatile
    sections excluded). Returns a sorted list of section names; empty = the demo is fresh."""
    try:
        with open(committed_path, encoding="utf-8") as f:
            committed = json.load(f)
    except FileNotFoundError:
        return ["<no committed sample_fleet.snapshot.json at all>"]
    a, b = _strip_volatile(fresh), _strip_volatile(committed)
    return sorted(set(k for k in set(a) | set(b) if a.get(k) != b.get(k)))


def _parse_args(argv: list) -> tuple:
    """(check, out_path) from the command line. `--out PATH` writes (or, with --check, compares
    against) PATH instead of the tracked fixture, so the fleet can be regenerated into scratch."""
    import argparse
    ap = argparse.ArgumentParser(prog="build_sample.py", description="Regenerate the engine-computed demo fleet.")
    ap.add_argument("--check", action="store_true",
                    help="rebuild in a temp dir and diff against the output path instead of writing it")
    ap.add_argument("--out", default=OUT, metavar="PATH",
                    help="snapshot path to write / check (default: the tracked sample_fleet.snapshot.json)")
    ns = ap.parse_args(argv)
    return ns.check, ns.out


def _write_snapshot(path: str, snap: dict) -> None:
    """Pretty (indent=2) JSON with LF line endings on EVERY platform: text-mode open() on Windows would
    otherwise write CRLF, and the tracked blob (and Atlas Scope's digest binding of it) is LF."""
    with open(path, "w", encoding="utf-8", newline="\n") as _out:
        json.dump(snap, _out, indent=2)


def main(argv: list = None) -> None:
    # --check: rebuild the demo in a temp dir and DIFF it against the committed fixture instead of
    # overwriting it — the full-fidelity freshness tool (runs the real pipeline, ~minutes; the cheap
    # per-section locks that run in the default test gate live in tests/test_sample_fleet.py).
    # Exit 0 = fresh, exit 2 = stale (regenerate by rerunning WITHOUT --check).
    check, out_path = _parse_args(sys.argv[1:] if argv is None else argv)
    cols = build_collections()
    devices = [{"hostname": h, "ip": f"10.0.99.{i + 1}", "username": "demo",
                "password": "x", "platform": plat}
               for i, (h, (plat, _o)) in enumerate(cols.items())]
    # W59 PR-1: the device whose folder holds only its SSH session record (attempted, not collected).
    devices.append({**_SSH_EXTRA_DEVICE, "username": "demo", "password": "x"})

    work = tempfile.mkdtemp(prefix="assesshub_sample_")
    try:
        collection = os.path.join(work, f"collection_{_SAMPLE_COLLECTION_STAMP}")
        _write_collection(collection, cols)
        _write_ssh_session_records(collection)
        dev_file = os.path.join(work, "devices.json")
        # The engine binds this input's bytes too (its devices_file custody record). Compact json.dump emits
        # no newline today, so LF is declared for the same host-independence rule, not to change any byte.
        with open(dev_file, "w", encoding="utf-8", newline="\n") as f:
            json.dump(devices, f)
        template = os.path.join(work, "template.xlsx")
        _make_template(template)
        out_xlsx = os.path.join(work, "out.xlsx")

        cwd = os.getcwd()
        # Synthetic cwd: the PPDIOO document gates resolve docs/engagement-state.json relative to
        # it, so they would find nothing here and warn-and-proceed. Safe ONLY because --no-design
        # --no-mop below means no gated deliverable is generated at all; if either is ever dropped,
        # pass --gate-root <the real engagement root> too (cisco_toolkit/gate_state.py).
        os.chdir(work)
        argv = sys.argv[:]
        sys.argv = ["cisco-assess", "--no-collect", "--collection-dir", collection,
                    "--devices-file", dev_file, "--template", template,
                    "--output", out_xlsx, "--workers", "1", "--no-html", "--no-docx",
                    "--no-pptx", "--no-design", "--no-mop"]
        try:
            with _registry_clock(_SAMPLE_REGISTRY_CLOCK) as evidence, _collection_zone(evidence.tzinfo):
                cp.main()
        finally:
            sys.argv = argv
            os.chdir(cwd)

        snap_path = os.path.splitext(out_xlsx)[0] + ".snapshot.json"
        # Re-dump PRETTY (indent=2), not a raw copy of the engine's compact on-disk snapshot: the committed
        # sample is a human-reviewable, git-diffable demo fixture, so a one-line compact blob would make every
        # regeneration an unreadable 1-line diff. (The engine's real *.snapshot.json stays compact; this is
        # only the demo copy webapp/ ships.)
        snap = json.loads(open(snap_path, encoding="utf-8").read())
        if check:
            drift = _freshness_drift(snap, out_path)
            if drift:
                print("STALE sample_fleet.snapshot.json — section(s) drifted from the current engine:")
                for s in drift:
                    print(f"  - {s}")
                print("regenerate: python webapp/sample_data/build_sample.py")
                # The fleet's bytes are also the bound source of Atlas Scope's tracked projection: its four
                # compiled documents carry the fleet's Git blob and digest, and its golden tier is pinned to
                # that digest. A regenerated fleet leaves them stale until they are re-bound.
                print("then re-bind Atlas Scope: cd atlas-scope, run `node tools/compile-all.mjs`, and set "
                      "GOLDEN_SHA in atlas-scope/src/test-support/golden-sample.ts to the new sourceSha256 "
                      "(re-derive any golden expectation whose section changed)")
                raise SystemExit(2)
            print("sample_fleet.snapshot.json is FRESH — matches the current engine output "
                  "(only genuine wall-clock leaves excluded)")
            return
        _write_snapshot(out_path, snap)
        bands: dict = {}
        for r in snap.get("health_scores", []):
            bands[r.get("band", "?")] = bands.get(r.get("band", "?"), 0) + 1
        print(f"wrote {out_path}")
        print(f"  devices={len(snap.get('devices', {}))}  "
              f"links={len(snap.get('topology_links') or snap.get('link_centrality') or [])}  "
              f"punchlist={len(snap.get('punchlist', []))}  bands={bands}")
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
