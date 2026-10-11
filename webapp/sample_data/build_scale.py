"""Deterministic synthetic campus captures; never reads a customer collection.

The 300 managed devices are distinct from 868 uncollected endpoint neighbours.
All 1,500 physical cables have unique ports; managed links have reciprocal CDP.
Reuse the demo's capture grammars and writers without changing its golden fleet.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import ipaddress
import json
from pathlib import Path

from webapp.sample_data import build_sample as sample

PROFILE = "synthetic-campus-300/1"
ROLE_COUNTS = {"access": 240, "distribution": 40, "core": 8, "wlc": 6, "firewall": 6}
MODELS = {"access": "C9300-48P", "distribution": "C9500-48Y4C", "core": "C9606R",
          "wlc": "C9800-L-C-K9", "firewall": "ASAv"}
VLAN_IDS = tuple(range(100, 300))
STAMP = "20260807_000000"


def layout():
    """One source of device, link and endpoint identity for every capture."""
    roles = {f"{role}{i:03d}": role for role, n in ROLE_COUNTS.items() for i in range(1, n + 1)}
    ports = defaultdict(int)
    links = []

    def cable(a, b):
        ports[a] += 1
        ports[b] += 1
        links.append({"a": a, "a_port": f"Gi1/0/{ports[a]}",
                      "b": b, "b_port": f"Gi1/0/{ports[b]}" if b in roles else "eth0"})

    for i in range(240):
        host = f"access{i + 1:03d}"
        pair = i // 12
        for side in (1, 2):
            cable(host, f"distribution{2 * pair + side:03d}")
        # 148 four-endpoint switches plus 92 three-endpoint switches = 868.
        for j in range(4 if i < 148 else 3):
            cable(host, f"phone-{i + 1:03d}-{j + 1}")
    for i in range(40):
        for side in (0, 1):
            cable(f"distribution{i + 1:03d}", f"core{2 * ((i // 2) % 4) + side + 1:03d}")
    for i in range(20):
        cable(f"distribution{2 * i + 1:03d}", f"distribution{2 * i + 2:03d}")
    for a in range(1, 9):
        for b in range(a + 1, 9):
            cable(f"core{a:03d}", f"core{b:03d}")
    for role in ("wlc", "firewall"):
        for i in range(6):
            for side in (1, 2):
                cable(f"{role}{i + 1:03d}", f"distribution{2 * i + side:03d}")
    assert len(roles) == 300 and len(links) == 1500
    return roles, links


def _mac(value):
    text = f"{0x020000000000 + value:012x}"
    return ".".join(text[i:i + 4] for i in (0, 4, 8))


def addresses_for(roles, links):
    """Unique managed addresses and phone DHCP addresses in their access VLAN."""
    addresses = {h: f"10.255.{i // 250}.{i % 250 + 1}" for i, h in enumerate(roles)}
    ordinal = {h: i for i, h in enumerate(roles)}
    for link in links:
        if link["b"] in roles:
            continue
        idx = ordinal[link["a"]]
        port = int(link["a_port"].rsplit("/", 1)[1])
        vlan = VLAN_IDS[(idx // 12) * 10 + (port - 1) % 10]
        addresses[link["b"]] = f"10.{vlan // 256}.{vlan % 256}.{100 + (idx % 12) * 4 + port - 3}"
    if len(addresses) != 1168 or len(set(addresses.values())) != len(addresses):
        raise AssertionError("Synthetic management/endpoint address identities overlap")
    return addresses


def captures(host, role, idx, neighbours, roles, addresses):
    """Substantial valid records, rather than padding one small fixture with comments."""
    pod = idx // 12 if role == "access" else (idx - 240) // 2 if role == "distribution" else idx - 288 if role == "wlc" else idx % 20
    vlans = VLAN_IDS if role == "core" else VLAN_IDS[pod * 10:(pod + 1) * 10]
    model = MODELS[role]
    if role == "firewall":
        version = f"Cisco Adaptive Security Appliance Software Version 9.20(2)\nHardware: {model}, 32768 MB RAM\n"
    else:
        version = sample._PLATFORMS[2].format(sn=f"SYN{idx:08d}").replace("C9300-48P", model)
    outputs = {"show version": version, "show inventory":
               f'NAME: "Chassis", DESCR: "Synthetic {role}"\nPID: {model}, VID: V01, SN: SYN{idx:08d}\n'}
    # Use the sample's canonical switchport grammar. 48 access / 64 distribution /
    # 96 core ports; WLC and firewall use their smaller interface inventories.
    port_count = {"access": 48, "distribution": 64, "core": 96, "wlc": 8, "firewall": 8}[role]
    peers = {local: (peer, remote) for local, peer, remote in neighbours}
    status = ["Port      Name               Status       Vlan       Duplex  Speed Type"]
    details, switches, config, brief, cdp, trunks = [], [], [], [], [], []
    ordinal = {name: i for i, name in enumerate(roles)}
    routed_peers = []
    for p in range(1, port_count + 1):
        port = f"Gi1/0/{p}"
        long_port = f"GigabitEthernet1/0/{p}"
        peer, remote = peers.get(port, (None, None))
        routed = role in ("core", "firewall") or roles.get(peer) in ("core", "firewall")
        trunk = peer in roles and not routed
        vlan = vlans[(p - 1) % len(vlans)]
        live = peer is not None
        status.append(f"{port:<10}{('to-' + peer)[:18] if peer else 'spare':<19} "
                      f"{'connected' if live else 'notconnect':<12} "
                      f"{'routed' if routed else 'trunk' if trunk else vlan!s:<12} full 1000 1000BaseLX SFP")
        details.append(f"{long_port} is {'up' if live else 'down'}, line protocol is {'up' if live else 'down'}\n"
                       f"  Hardware is Gigabit Ethernet, address is {_mac(idx * 256 + p)}\n"
                       "  MTU 1500 bytes, BW 1000000 Kbit/sec, DLY 10 usec\n"
                       "  Full-duplex, 1000Mb/s, media type is 1000BaseLX SFP\n"
                       "  5 minute input rate 800000 bits/sec, 500 packets/sec\n"
                       "  5 minute output rate 400000 bits/sec, 300 packets/sec\n"
                       "     120000 packets input, 96000000 bytes, 0 no buffer\n"
                       "     0 input errors, 0 CRC, 0 frame, 0 overrun, 0 ignored\n"
                       "     80000 packets output, 64000000 bytes, 0 underruns\n"
                       "     Total output drops: 0\n")
        cfg = f"interface {long_port}\n description {('to-' + peer) if peer else 'spare'}\n"
        address = "unassigned"
        if routed:
            cfg += " no switchport\n"
            if peer in roles:
                a, b = sorted((host, peer))
                network = int(ipaddress.IPv4Address("10.240.0.0")) + (ordinal[a] * 300 + ordinal[b]) * 4
                address = str(ipaddress.IPv4Address(network + (1 if host == a else 2)))
                cfg += f" ip address {address} 255.255.255.252\n"
                routed_peers.append((long_port, str(ipaddress.IPv4Address(network + (2 if host == a else 1)))))
        elif trunk:
            switches.append(sample._sw_trunk(port, ",".join(map(str, vlans))))
            trunks.append(port)
            cfg += " switchport mode trunk\n switchport trunk allowed vlan " + ",".join(map(str, vlans)) + "\n"
        else:
            switches.append(sample._sw_access(port, vlan, f"SYN-VLAN-{vlan}"))
            cfg += f" switchport mode access\n switchport access vlan {vlan}\n spanning-tree portfast\n"
        config.append(cfg)
        brief.append(f"{long_port:<26}{address:<17} YES NVRAM {'up' if live else 'down'} {'up' if live else 'down'}")
        if peer:
            peer_model = MODELS[roles[peer]] if peer in roles else "cisco IP Phone 8841"
            advertised = f"{peer}.lab" if peer in roles else peer
            cdp.append(f"-------------------------\nDevice ID: {advertised}\nEntry address(es):\n"
                       f"  IP address: {addresses.get(peer, '192.0.2.1')}\n"
                       f"Platform: {peer_model},  Capabilities: {'Router Switch' if peer in roles else 'Phone'}\n"
                       f"Interface: {long_port},  Port ID (outgoing port): {remote}\nHoldtime : 150 sec\n")
    svis = vlans if role == "distribution" else vlans[:1] if role in ("access", "wlc") else ()
    for vlan in svis:
        octet = 2 + (idx - 240) % 2 if role == "distribution" else 10 + idx % 200
        address = f"10.{vlan // 256}.{vlan % 256}.{octet}"
        brief.append(f"Vlan{vlan:<19}{address:<17} YES NVRAM up up")
        cfg = f"interface Vlan{vlan}\n ip address {address} 255.255.255.0\n"
        if role == "distribution":
            cfg += f" standby {vlan} ip 10.{vlan // 256}.{vlan % 256}.1\n standby {vlan} priority {110 if idx % 2 == 0 else 100}\n standby {vlan} preempt\n"
        config.append(cfg)
    outputs.update({
        "show interface status": "\n".join(status) + "\n",
        "show interfaces": "\n".join(details),
        "show interfaces switchport": "".join(switches),
        "show running-config | section ^interface": "!\n".join(config),
        "show running-config": f"hostname {host}\n" + "!\n".join(config) + "end\n",
        "show ip interface brief": "Interface IP-Address OK? Method Status Protocol\n" + "\n".join(brief) + "\n",
        "show cdp neighbors detail": "".join(cdp),
        "show vlan brief": "VLAN Name                             Status    Ports\n"
                           "---- -------------------------------- --------- -------------------------------\n" +
                           "".join(f"{v:<5}SYN-VLAN-{v:<24} active\n" for v in vlans),
        "show interfaces trunk": "Port        Mode             Encapsulation  Status        Native vlan\n" +
             "".join(f"{p:<12}on               802.1q         trunking      1\n" for p in trunks) +
             "\nPort        Vlans allowed on trunk\n" +
             "".join(f"{p:<12}{','.join(map(str, vlans))}\n" for p in trunks),
    })
    # A shared VLAN/MAC identity across collectors is realistic learned remote
    # state: 600k observed rows do not invent 600k distinct physical endpoints.
    nmac = 2048 if role == "access" else 4096 if role == "distribution" else 512 if role == "wlc" else 0
    outputs["show mac address-table"] = "Vlan    Mac Address       Type        Ports\n----    -----------       --------    -----\n" + "".join(
        f" {vlans[j % len(vlans)]:4}    {_mac(vlans[j % len(vlans)] * 8192 + j // len(vlans))}    DYNAMIC     Gi1/0/{j % max(1, len(peers)) + 1}\n" for j in range(nmac))
    arp = []
    if role in ("core", "firewall"):
        arp = [f"Internet  {address}  5  {_mac(idx * 8192 + j)}  ARPA  {port}\n"
               for j, (port, address) in enumerate(routed_peers)]
    else:
        for j in range(250):
            vlan = vlans[j % len(vlans)] if role == "distribution" else vlans[0]
            octet = j // len(vlans) + 10 if role == "distribution" else j + 2
            arp.append(f"Internet  10.{vlan // 256}.{vlan % 256}.{octet}  5  {_mac(vlan * 8192 + j)}  ARPA  Vlan{vlan}\n")
    outputs["show ip arp"] = "Protocol  Address          Age (min)  Hardware Addr   Type   Interface\n" + "".join(arp)
    nroutes = 1000 if role in ("distribution", "core", "firewall") else 200
    route_port, next_hop = routed_peers[0] if routed_peers else (f"Vlan{vlans[0]}", f"10.{vlans[0] // 256}.{vlans[0] % 256}.1")
    outputs["show ip route"] = f"Gateway of last resort is {next_hop} to network 0.0.0.0\n" + "".join(
        f"S    172.{16 + j // 256}.{j % 256}.0/24 [1/0] via {next_hop}, {route_port}\n" for j in range(nroutes))
    outputs["show logging"] = "Syslog logging: enabled\n" + "".join(
        f"Aug  7 00:{j // 60 % 60:02}:{j % 60:02}.000: %LINK-3-UPDOWN: Interface GigabitEthernet1/0/{j % port_count + 1}, changed state to up\n"
        for j in range(1000))
    if role == "wlc":
        outputs["show wireless summary"] = "Number of APs: 120\nNumber of Clients: 1200\n"
        outputs["show ap summary"] = "AP Name                         Slots AP Model       Ethernet MAC\n" + "".join(
            f"SYN-AP-{idx:03}-{j:03}              2     C9120AXI        {_mac(idx * 8192 + j)}\n" for j in range(120))
    if role == "firewall":
        outputs["show failover"] = "Failover On\nThis host: Primary - Active\nOther host: Secondary - Standby Ready\n"
        outputs["show resource usage"] = "Resource Current Peak Limit Denied Context\nConns 12000 18000 250000 0 System\n"
        outputs["show conn"] = "12000 in use, 18000 most used\n" + "".join(
            f"TCP outside 198.51.100.{j % 250 + 1}:443 inside 192.0.2.{j % 250 + 1}:{20000 + j}, idle 0:00:05, bytes 4096, flags UIO\n"
            for j in range(1000))
    return outputs


def build(root: Path):
    roles, links = layout()
    addresses = addresses_for(roles, links)
    neighbours = defaultdict(list)
    for link in links:
        a, b = link["a"], link["b"]
        neighbours[a].append((link["a_port"], b, link["b_port"]))
        if b in roles:
            neighbours[b].append((link["b_port"], a, link["a_port"]))
    collection = root / f"collection_{STAMP}"
    census = []
    for i, (host, role) in enumerate(roles.items()):
        outputs = captures(host, role, i, neighbours[host], roles, addresses)
        sample._write_collection(str(collection), {host: ("ios", outputs)})
        census.append({"host": host, "role": role, "files": len(outputs),
                       "capture_bytes": sum(len(t.encode()) for t in outputs.values())})
    devices = [{"hostname": h, "ip": addresses[h], "username": "synthetic",
                "password": "offline-not-used", "platform": "ios"} for h in roles]
    (root / "devices.json").write_text(json.dumps(devices, separators=(",", ":")), encoding="utf-8")
    sample._make_template(str(root / "template.xlsx"))
    digest = hashlib.sha256()
    for path in sorted(collection.rglob("*.txt")):
        digest.update(path.relative_to(collection).as_posix().encode() + b"\0" + path.read_bytes() + b"\0")
    manifest = {"profile": PROFILE, "synthetic_only": True, "roles": dict(Counter(roles.values())),
                "managed_devices": len(roles), "vlan_ids": list(VLAN_IDS), "physical_cables": len(links),
                "uncollected_endpoints": 868, "captures_sha256": digest.hexdigest(),
                "devices": census, "links": links}
    (root / "fleet.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest
