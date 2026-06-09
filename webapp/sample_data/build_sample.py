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
