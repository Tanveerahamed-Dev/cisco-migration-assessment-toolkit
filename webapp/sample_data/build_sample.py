"""Generate a richer, engine-computed demo snapshot for AssessHub.

The bundled `tests/golden/snapshot.json` is only 3 devices — fine for tests, thin for a demo. This
script builds a believable **2-core + many-access** campus by CLONING the proven synthetic fixtures
(`tests/synthetic_fixtures.py`, imported read-only — never modified, so the golden contract is safe),
varying each access switch (which core it homes to, native-VLAN hygiene, platform/EoL tier), then runs
the **real** offline pipeline (`COLLECT_PARSE … --no-collect`) so every health score, punch-list item,
keystone, topology link, and lifecycle band is genuinely computed by the engine — not faked.

Output: webapp/sample_data/sample_fleet.snapshot.json

Run:  python webapp/sample_data/build_sample.py
"""

from __future__ import annotations

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
    return cols


def _write_collection(root: str, cols: dict) -> None:
    for hostname, (_plat, outputs) in cols.items():
        d = os.path.join(root, hostname)
        os.makedirs(d, exist_ok=True)
        for cmd, text in outputs.items():
            with open(os.path.join(d, fx.cmd_filename(cmd)), "w", encoding="utf-8") as f:
                f.write(text)


def _make_template(path: str) -> None:
    from openpyxl import Workbook
    wb = Workbook()
    wb.active.title = "Interface Data"
    wb.active.append(["Hostname", "Port", "Status"])
    wb.save(path)


def main() -> None:
    cols = build_collections()
    devices = [{"hostname": h, "ip": f"10.0.99.{i + 1}", "username": "demo",
                "password": "x", "platform": plat}
               for i, (h, (plat, _o)) in enumerate(cols.items())]

    work = tempfile.mkdtemp(prefix="assesshub_sample_")
    try:
        collection = os.path.join(work, "collection")
        _write_collection(collection, cols)
        dev_file = os.path.join(work, "devices.json")
        with open(dev_file, "w", encoding="utf-8") as f:
            json.dump(devices, f)
        template = os.path.join(work, "template.xlsx")
        _make_template(template)
        out_xlsx = os.path.join(work, "out.xlsx")

        cwd = os.getcwd()
        os.chdir(work)
        argv = sys.argv[:]
        sys.argv = ["cisco-assess", "--no-collect", "--collection-dir", collection,
                    "--devices-file", dev_file, "--template", template,
                    "--output", out_xlsx, "--workers", "1", "--no-html", "--no-docx",
                    "--no-pptx", "--no-design", "--no-mop"]
        try:
            cp.main()
        finally:
            sys.argv = argv
            os.chdir(cwd)

        snap_path = os.path.splitext(out_xlsx)[0] + ".snapshot.json"
        shutil.copyfile(snap_path, OUT)
        snap = json.loads(open(OUT, encoding="utf-8").read())
        bands: dict = {}
        for r in snap.get("health_scores", []):
            bands[r.get("band", "?")] = bands.get(r.get("band", "?"), 0) + 1
        print(f"wrote {OUT}")
        print(f"  devices={len(snap.get('devices', {}))}  "
              f"links={len(snap.get('topology_links') or snap.get('link_centrality') or [])}  "
              f"punchlist={len(snap.get('punchlist', []))}  bands={bands}")
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
