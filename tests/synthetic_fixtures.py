"""
Synthetic offline-collection fixtures for the regression/unit test suite.

These are HAND-AUTHORED, fully synthetic Cisco `show` outputs (no real network
data) for three switches that together exercise the scenarios the audit called
out:

  * core1 (IOS)   - distribution: SVIs with HSRP (Vlan10/20 redundant), a
                    SOLE-GATEWAY SVI with no FHRP (Vlan30), a healthy 2-member
                    port-channel to core2, and a DOWN OSPF neighbor.
  * core2 (NX-OS) - core: HSRP peer for Vlan10/20, the other end of the
                    port-channel.
  * access1 (IOS) - access: a SINGLE fiber trunk uplink to core1 (no
                    port-channel => single-homed), access ports with endpoints,
                    and one err-disabled port.

`write_collection(root)` writes each command to a file using the EXACT filename
transform the main script's offline loader (`--no-collect`) expects, so the
fixtures drive the real pipeline unchanged.
"""
from __future__ import annotations
import os
from typing import Dict, Tuple


def cmd_filename(cmd: str) -> str:
    """Mirror the main script's offline filename transform EXACTLY."""
    return cmd.replace(" ", "_").replace("|", "_").replace("^", "").replace("/", "_") + ".txt"


# --------------------------------------------------------------------------- #
# core1 - IOS distribution switch
# --------------------------------------------------------------------------- #
_CORE1 = {
    "show interface status": """\
Port      Name               Status       Vlan       Duplex  Speed Type
Gi1/0/1   to-core2-a         connected    trunk        full  1000  10/100/1000BaseTX
Gi1/0/2   to-core2-b         connected    trunk        full  1000  10/100/1000BaseTX
Gi1/0/24  to-access1         connected    trunk        full  1000  1000BaseLX SFP
Gi1/0/5   srv-app01          connected    10           full  1000  10/100/1000BaseTX
Gi1/0/9   quarantine         err-disabled 10           auto  auto  10/100/1000BaseTX
Po1       to-core2           connected    trunk        full  2000
""",
    "show interfaces switchport": """\
Name: Gi1/0/24
Switchport: Enabled
Administrative Mode: trunk
Operational Mode: trunk
Administrative Trunking Encapsulation: dot1q
Negotiation of Trunking: On
Access Mode VLAN: 1 (default)
Trunking Native Mode VLAN: 1 (default)
Trunking VLANs Enabled: 10,20,30

Name: Gi1/0/5
Switchport: Enabled
Administrative Mode: static access
Operational Mode: static access
Access Mode VLAN: 10 (data)
Trunking Native Mode VLAN: 1 (default)

Name: Gi1/0/9
Switchport: Enabled
Administrative Mode: static access
Operational Mode: down
Access Mode VLAN: 10 (data)
Trunking Native Mode VLAN: 1 (default)

Name: Po1
Switchport: Enabled
Administrative Mode: trunk
Operational Mode: trunk
Access Mode VLAN: 1 (default)
Trunking Native Mode VLAN: 1 (default)
Trunking VLANs Enabled: 10,20,30
""",
    "show interfaces trunk": """\
Port        Mode             Encapsulation  Status        Native vlan
Gi1/0/24    on               802.1q         trunking      1
Po1         on               802.1q         trunking      1

Port        Vlans allowed on trunk
Gi1/0/24    10,20,30
Po1         10,20,30
""",
    "show running-config | section ^interface": """\
interface GigabitEthernet1/0/1
 description to-core2-a
 switchport mode trunk
 channel-group 1 mode active
interface GigabitEthernet1/0/2
 description to-core2-b
 switchport mode trunk
 channel-group 1 mode active
interface GigabitEthernet1/0/24
 description to-access1
 switchport trunk encapsulation dot1q
 switchport mode trunk
interface GigabitEthernet1/0/5
 description srv-app01
 switchport access vlan 10
 spanning-tree portfast
interface GigabitEthernet1/0/9
 description quarantine
 switchport access vlan 10
interface Port-channel1
 description to-core2
 switchport mode trunk
 mtu 9216
interface Vlan10
 description USERS
 ip address 10.0.10.2 255.255.255.0
 ip helper-address 10.0.40.10
 ip helper-address 10.0.40.11
 standby 10 ip 10.0.10.1
 standby 10 priority 110
interface Vlan20
 description VOICE
 ip address 10.0.20.2 255.255.255.0
 ip access-group VOICE_FILTER in
 standby 20 ip 10.0.20.1
interface Vlan30
 description SERVERS
 vrf forwarding TENANT_RED
 ip address 10.0.30.1 255.255.255.0
 ip access-group PROTECT_SERVERS out
""",
    "show running-config": """\
!
service password-encryption
aaa new-model
enable secret 9 $9$FAKEsecretHASHonly
username admin privilege 15 secret 9 $9$FAKEadminHASHonly
username legacy password 7 070C285F4D06
snmp-server community public RO
ntp server 10.0.0.10
logging host 10.0.0.20
ip http server
no ip http secure-server
line vty 0 4
 transport input telnet ssh
 exec-timeout 0 0
!
object-group network MGMT_HOSTS
 host 10.0.99.10
 10.0.40.0 255.255.255.0
ip access-list extended VOICE_FILTER
 permit udp 10.0.20.0 0.0.0.255 any range 16384 32767
 permit udp 10.0.20.0 0.0.0.255 any eq 5060
 deny   ip any any
ip access-list extended PROTECT_SERVERS
 permit tcp 10.0.10.0 0.0.0.255 10.0.30.0 0.0.0.255 eq 443
 permit tcp 10.0.10.0 0.0.0.255 10.0.30.0 0.0.0.255 eq 22
 permit icmp any 10.0.30.0 0.0.0.255 echo-reply
 deny   ip any any
ip access-list extended MGMT_IN
 permit tcp object-group MGMT_HOSTS any eq 22
 deny   ip any any
ip access-list extended INET_RETURN
 permit tcp any any established
 permit tcp 10.0.10.0 0.0.0.255 any eq 443 time-range BUSINESS_HOURS
 deny   ip any any
!
interface GigabitEthernet1/0/5
 ip access-group PROTECT_SERVERS in
 ip access-group VOICE_FILTER out
interface GigabitEthernet1/0/6
 ip access-group MGMT_IN in
interface Vlan10
 ip nat inside
interface GigabitEthernet1/0/24
 ip nat outside
ip nat pool MIGRATE_POOL 203.0.113.10 203.0.113.20 netmask 255.255.255.0
ip nat inside source static 10.0.30.9 203.0.113.9
ip nat inside source static tcp 10.0.30.9 443 203.0.113.9 8443
ip nat inside source list 7 pool MIGRATE_POOL overload
!
router ospf 1
 redistribute bgp 65001 subnets
 redistribute connected
router bgp 65001
 redistribute ospf 1 route-map OSPF_TO_BGP
!
""",
    "show etherchannel summary": """\
Flags:  D - down        P - bundled in port-channel
        I - stand-alone s - suspended
Number of channel-groups in use: 1
Number of aggregators:           1

Group  Port-channel  Protocol    Ports
------+-------------+-----------+-----------------------------------------------
1      Po1(SU)         LACP      Gi1/0/1(P)    Gi1/0/2(P)
""",
    "show spanning-tree": """\
VLAN0010
  Spanning tree enabled protocol rstp
  Root ID    Priority    24586
             Address     aaaa.0001.0001
             This bridge is the root
  Bridge ID  Priority    24586  (priority 24576 sys-id-ext 10)
             Address     aaaa.0001.0001
Interface        Role Sts Cost      Prio.Nbr Type
---------------- ---- --- --------- -------- ----
Gi1/0/24         Desg FWD 4         128.24   P2p
Po1              Desg FWD 3         128.65   P2p

VLAN0030
  Spanning tree enabled protocol rstp
  Root ID    Priority    32798
             Address     cccc.0003.0003
             Cost        4
  Bridge ID  Priority    32798  (priority 32768 sys-id-ext 30)
             Address     aaaa.0001.0001
Interface        Role Sts Cost      Prio.Nbr Type
---------------- ---- --- --------- -------- ----
Gi1/0/24         Desg FWD 4         128.24   P2p
Po1              Root FWD 3         128.65   P2p
""",
    "show cdp neighbors detail": """\
-------------------------
Device ID: core2.lab
Entry address(es):
  IP address: 10.0.99.2
Platform: cisco N9K-C93180YC-EX,  Capabilities: Router Switch
Interface: Port-channel1,  Port ID (outgoing port): port-channel1
Holdtime : 145 sec
-------------------------
Device ID: access1.lab
Entry address(es):
  IP address: 10.0.99.3
Platform: cisco WS-C2960X-48,  Capabilities: Switch
Interface: GigabitEthernet1/0/24,  Port ID (outgoing port): GigabitEthernet0/1
Holdtime : 150 sec
""",
    "show mac address-table": """\
          Mac Address Table
-------------------------------------------
Vlan    Mac Address       Type        Ports
----    -----------       --------    -----
  10    0011.2233.4455    DYNAMIC     Gi1/0/5
  10    0011.2233.4466    DYNAMIC     Gi1/0/5
""",
    "show vlan brief": """\
VLAN Name                             Status    Ports
---- -------------------------------- --------- -------------------------------
10   USERS                            active    Gi1/0/5, Gi1/0/9
20   VOICE                            active
30   SERVERS                          active
""",
    "show standby brief": """\
                     P indicates configured to preempt.
                     |
Interface   Grp  Pri P State    Active          Standby         Virtual IP
Vl10        10   110 P Active   local           10.0.10.3       10.0.10.1
Vl20        20   100   Standby  10.0.20.3       local           10.0.20.1
""",
    # FHRP DETAIL (universality): the active Vl10 gateway has preempt but NO interface tracking -- the
    # classic gap _d_fhrp_resilience now catches. [HISTORY-REDACTED] ran zero FHRP, so this fixture is the first to prove
    # the engine ASSESSES first-hop redundancy end-to-end.
    "show standby all": """\
Vlan10 - Group 10
  State is Active
  Virtual IP address is 10.0.10.1
  Active virtual MAC address is 0000.0c07.ac0a
  Hello time 3 sec, hold time 10 sec
  Preemption enabled
  Active router is local
  Standby router is 10.0.10.3, priority 100 (expires in 9.000 sec)
  Priority 110 (configured 110)
Vlan20 - Group 20
  State is Standby
  Virtual IP address is 10.0.20.1
  Active virtual MAC address is 0000.0c07.ac14
  Preemption disabled
  Standby router is local
  Active router is 10.0.20.3, priority 110
  Priority 100 (configured 100)
""",
    # PIM-SM control plane: core1 RUNS sparse-mode (a live PIM neighbor toward core2) but 'show ip pim rp
    # mapping' learned NO RP -> ASM (*,G) shared trees can't form -> _d_pim_rp_health FIRES (running +
    # collected + 0 RP + not SSM-only). The header is present so the axis is unambiguously COLLECTED.
    "show ip pim neighbor": """\
PIM Neighbor Table
Mode: B - Bidir Capable, DR - Designated Router, N - Default DR Priority,
      P - Proxy Capable, S - State Refresh Capable, G - GenID Capable
Neighbor          Interface                Uptime/Expires    Ver   DR
Address                                                            Prio/Mode
10.0.255.2        GigabitEthernet1/0/1     00:42:17/00:01:31 v2    1 / DR S P G
""",
    "show ip pim rp mapping": """\
PIM Group-to-RP Mappings

""",
    # NTP clock-sync STATE: core1 has 'ntp server' configured (config-only CIS no-ntp PASSES) yet the
    # operational clock is UNSYNCHRONIZED at stratum 16 -> _d_ntp_sync catches what the config check cannot.
    "show ntp status": """\
Clock is unsynchronized, stratum 16, no reference clock
nominal freq is 250.0000 Hz, actual freq is 250.0000 Hz, precision is 2**18
reference time is 00000000.00000000 (00:00:00.000 UTC Mon Jan 1 1900)
clock offset is 0.0000 msec, root delay is 0.00 msec
root dispersion is 15.91 msec, peer dispersion is 0.00 msec
""",
    # QoS RUNTIME: core1's egress PRIORITY (LLQ) class is congestion-dropping real-time traffic, and a data
    # class is shedding >1% of its load -> _d_qos_runtime_drops fires HIGH. class-default is clean (no cry-wolf).
    "show policy-map interface": """\
GigabitEthernet1/0/24

  Service-policy output: WAN-EDGE-OUT

    Class-map: VOICE (match-any)
      24817400 packets, 4765747200 bytes
      Match: dscp ef (46)
      Queueing
      priority level 1
      queue limit 512 packets
      (queue depth/total drops/no-buffer drops) 511/1840521/0
      (pkts output/bytes output) 24817400/4765747200

    Class-map: BULK-DATA (match-any)
      8400000 packets, 6048000000 bytes
      Match: dscp af11 (10)
      Queueing
      queue limit 2000 packets
      (queue depth/total drops/no-buffer drops) 1998/512000/0
      (pkts output/bytes output) 8400000/6048000000
      bandwidth remaining 30%

    Class-map: class-default (match-any)
      150000 packets, 18000000 bytes
      Queueing
      queue limit 416 packets
      (queue depth/total drops/no-buffer drops) 0/0/0
      (pkts output/bytes output) 150000/18000000
""",
    "show ip route": """\
Codes: C - connected, L - local, O - OSPF, B - BGP, S - static
Gateway of last resort is 10.0.10.254 to network 0.0.0.0

S*       0.0.0.0/0 [1/0] via 10.0.10.254
      10.0.0.0/8 is variably subnetted, 8 subnets, 3 masks
S        10.0.0.0/16 [1/0] via 10.0.30.254
C        10.0.10.0/24 is directly connected, Vlan10
L        10.0.10.2/32 is directly connected, Vlan10
C        10.0.20.0/24 is directly connected, Vlan20
L        10.0.20.2/32 is directly connected, Vlan20
C        10.0.30.0/24 is directly connected, Vlan30
L        10.0.30.1/32 is directly connected, Vlan30
S      192.168.99.0/24 [1/0] via 10.0.10.254
""",
    "show ip ospf neighbor": """\
Neighbor ID     Pri   State           Dead Time   Address         Interface
10.0.99.2         1   FULL/DR         00:00:35    10.0.99.2       Port-channel1
10.0.99.9         1   EXSTART/DROTHER 00:00:31    10.0.40.9       Vlan40
""",
    "show version": """\
Cisco IOS Software, Catalyst L3 Switch Software (CAT3K_CAA-UNIVERSALK9-M), Version 16.12.4
cisco WS-C3850-24T (MIPS) processor with 1024K bytes of memory.
System serial number        : FCW1234A001
Model number                : WS-C3850-24T
""",
    "show interfaces": """\
GigabitEthernet1/0/24 is up, line protocol is up (connected)
  MTU 1500 bytes, BW 1000000 Kbit/sec, DLY 10 usec
  Full-duplex, 1000Mb/s, media type is 1000BaseLX SFP
  Last input 00:00:01, output 00:00:00, output hang never
     0 input errors, 0 CRC, 0 frame, 0 overrun, 0 ignored
     Total output drops: 0
GigabitEthernet1/0/9 is down, line protocol is down (err-disabled)
  MTU 1500 bytes, BW 1000000 Kbit/sec, DLY 10 usec
  Auto-duplex, Auto-speed, media type is 10/100/1000BaseTX
  Last input never, output never, output hang never
     142 input errors, 17 CRC, 0 frame, 0 overrun, 0 ignored
     Total output drops: 0
""",
    "show ip interface brief": """\
Interface              IP-Address      OK? Method Status                Protocol
Vlan10                 10.0.10.2       YES NVRAM  up                    up
Vlan20                 10.0.20.2       YES NVRAM  up                    up
Vlan30                 10.0.30.1       YES NVRAM  up                    up
GigabitEthernet0/0     10.0.99.1       YES NVRAM  up                    up
""",
    # NEW-V3.23.164 (syslog intelligence): a MAC flap + the err-disable that explains the
    # quarantined Gi1/0/9, a flapping Gi1/0/9 (3 DOWN transitions -- V3.23.170 counts downs
    # only, since LINK+LINEPROTO pairs double-count one physical cycle), the down OSPF
    # neighbor's ADJCHG, and a config-change audit trail. core2 has NO log fixture on
    # purpose (exercises the declared not-collected path; NX-OS log handling is pinned
    # by unit tests in test_syslog_intelligence.py).
    "show logging": """\
Syslog logging: enabled (0 messages dropped, 0 messages rate-limited, 0 flushes, 0 overruns)
    Console logging: level debugging, 14 messages logged
    Buffer logging: level debugging, 14 messages logged
Log Buffer (8192 bytes):

*Jun  1 09:12:01.123: %SYS-5-CONFIG_I: Configured from console by svc-audit on vty0 (10.0.99.50)
*Jun  2 03:14:09.001: %SW_MATM-4-MACFLAP_NOTIF: Host 0011.22aa.0001 in vlan 10 is flapping between port Gi1/0/5 and port Gi1/0/9
*Jun  2 03:14:11.530: %SW_MATM-4-MACFLAP_NOTIF: Host 0011.22aa.0001 in vlan 10 is flapping between port Gi1/0/5 and port Gi1/0/9
*Jun  2 03:15:02.118: %PM-4-ERR_DISABLE: bpduguard error detected on Gi1/0/9, putting Gi1/0/9 in err-disable state
*Jun  2 03:15:03.220: %LINK-3-UPDOWN: Interface GigabitEthernet1/0/9, changed state to down
*Jun  2 03:16:10.002: %LINK-3-UPDOWN: Interface GigabitEthernet1/0/9, changed state to up
*Jun  2 03:16:55.481: %LINK-3-UPDOWN: Interface GigabitEthernet1/0/9, changed state to down
*Jun  2 03:17:30.110: %LINK-3-UPDOWN: Interface GigabitEthernet1/0/9, changed state to up
*Jun  2 03:17:31.220: %LINEPROTO-5-UPDOWN: Line protocol on Interface GigabitEthernet1/0/9, changed state to up
*Jun  2 03:18:02.957: %LINEPROTO-5-UPDOWN: Line protocol on Interface GigabitEthernet1/0/9, changed state to down
*Jun  2 03:18:40.481: %LINK-3-UPDOWN: Interface GigabitEthernet1/0/9, changed state to down
*Jun  2 03:19:12.034: %LINK-3-UPDOWN: Interface GigabitEthernet1/0/9, changed state to up
*Jun  3 11:02:44.901: %OSPF-5-ADJCHG: Process 1, Nbr 10.0.99.2 on Vlan20 from FULL to DOWN, Neighbor Down: Dead timer expired
*Jun  4 18:30:00.005: %SYS-5-CONFIG_I: Configured from console by svc-audit on vty0 (10.0.99.50)
""",
    # NEW-V3.23.167 (platform health): IOS capacity facts. The 5-min CPU sits in the
    # ELEVATED band (>= 60%) so the golden pins one Medium capacity finding.
    "show processes cpu": """\
CPU utilization for five seconds: 71%/12%; one minute: 66%; five minutes: 63%
 PID Runtime(ms)     Invoked      uSecs   5Sec   1Min   5Min TTY Process
   1         152        2776         54  0.00%  0.00%  0.00%   0 Chunk Manager
""",
    "show processes memory": """\
Processor Pool Total:  690885376 Used:  168148848 Free:  522736528
      I/O Pool Total:   16777216 Used:    6299568 Free:   10477648

 PID  TTY  Allocated      Freed    Holding    Getbufs    Retbufs Process
   0    0  295427864   95758288  185940776          0          0 *Init*
""",
    # SP/MPLS universality: core1 acts as an MPLS PE with a broken LDP session, a non-Established VPNv4
    # peer, and a DOWN pseudowire.  Each fires one of the three MPLS detectors end-to-end.
    # _d_mpls_ldp_health FIRES: core1 <-> 10.0.255.9 LDP session is Nonexistent (no label bindings).
    # _d_mpls_l3vpn_health FIRES: core1 <-> 10.0.255.9 VPNv4 BGP peer is Idle (no VPN routes).
    # _d_mpls_l2vpn_health FIRES: VC 300 (core1 <-> 10.0.255.9) is DOWN (customer L2 circuit broken).
    # The healthy peers (Oper LDP, Established VPNv4, UP VC 200) confirm coverage-honest silence.
    "show mpls ldp neighbor": """\
Peer LDP Ident: 10.0.255.2:0; Local LDP Ident 10.0.255.1:0
\tTCP connection: 10.0.255.2.646 - 10.0.255.1.11008
\tState: Oper; Msgs sent/rcvd: 842/839; Downstream
\tUp time: 4d05h
\tLDP discovery sources:
\t  GigabitEthernet1/0/1, Src IP addr: 10.0.255.2
\tAddresses bound to peer LDP Ident:
\t  10.0.255.2
Peer LDP Ident: 10.0.255.9:0; Local LDP Ident 10.0.255.1:0
\tTCP connection: (none)
\tState: Nonexistent; Msgs sent/rcvd: 0/0; Downstream
\tUp time: never
""",
    "show bgp vpnv4 unicast summary": """\
BGP router identifier 10.0.255.1, local AS number 65000
BGP table version is 14, main routing table version 14
Neighbor        V           AS MsgRcvd MsgSent   TblVer  InQ OutQ Up/Down  State/PfxRcd
10.0.255.2      4        65000     842     839       14    0    0 4d05h           6
10.0.255.9      4        65000       0       0        1    0    0 never    Idle
""",
    "show mpls l2transport vc": """\
Local intf     Local circuit              Dest address    VC ID    Status
-------------  -------------------------  --------------  -------  ----------
Gi1/0/2        Ethernet                   10.0.255.2      200      UP
Gi1/0/3        Ethernet VLAN 300          10.0.255.9      300      DOWN
""",
    # Cisco SD-Access LISP fabric control-plane (universality): core1 is an IOS-XE fabric node. VRF 'red' has
    # 2 reliable-transport sessions to the control-plane nodes (map-server/map-resolver, port 4342) but ZERO
    # established (both peers Down) -> _d_lisp_fabric_session_down FIRES (red overlay partitioned: cannot register
    # or resolve EID-to-RLOC). The healthy companion VRF 'default' (2 sessions, 2 established, both peers Up) in
    # the SAME output proves coverage-honest silence -- a node with established>=1 is NOT flagged, so the single
    # firing comes only from the all-down VRF, not from any individual Down row.
    "show lisp session": """\
Sessions for VRF default, total: 2, established: 2
Peer                           State      Up/Down        In/Out    Users
10.0.255.2:4342                Up         1d04h          27/9      14
10.0.255.3:4342                Up         1d03h          19/9      14
Sessions for VRF red, total: 2, established: 0
Peer                           State      Up/Down        In/Out    Users
10.0.255.2:4342                Down       never          0/0       0
10.0.255.3:4342                Down       never          0/0       0
""",
    # Cisco TrustSec / CTS universality: core1 (IOS-XE) is a TrustSec node whose environment-data download
    # never completed -> _d_cts_environment_data_health FIRES (Current state = WAITING_RESPONSE, not
    # COMPLETE; SGT/SGACL map absent -> group-based segmentation blind). The healthy COMPLETE companion +
    # the absent-CTS case are proved in test_d_cts_environment_data_health_fires_on_non_complete_only and in
    # access1 (which carries no 'show cts environment-data' at all -> snap['cts'] omits it -> silent).
    "show cts environment-data": """\
CTS Environment Data
====================
Current state = WAITING_RESPONSE
Last status = Failed
Environment Data is empty
State Machine is running
Retry_timer (60 secs) is running
""",
    # DMVPN WAN-overlay universality (mGRE/NHRP): core1 acts as a DMVPN hub. Tunnel1 peer 10.0.1.3 (NBMA
    # 37.37.37.3) is stuck in NHRP state and 10.0.1.4 (NBMA 47.47.47.4) is stuck in IKE -> _d_dmvpn_tunnel_health
    # FIRES (broken spoke tunnels: no overlay forwarding to those sites). The healthy peers (10.0.1.2 UP) prove
    # coverage-honest silence -- an all-UP hub never over-fires.
    "show dmvpn": """\
Legend: Attrb --> S - Static, D - Dynamic, I - Incomplete
        N - NATed, L - Local, X - No Socket
        # Ent --> Number of NHRP entries with same NBMA peer
        NHS Status: E --> Expecting Replies, R --> Responding, W --> Waiting
        UpDn Time --> Up or Down Time for a Tunnel
==========================================================================

Interface: Tunnel1, IPv4 NHRP Details
Type:Hub, NHRP Peers:3,

 # Ent  Peer NBMA Addr Peer Tunnel Add State  UpDn Tm Attrb
 ----- --------------- --------------- ----- -------- -----
     1 27.27.27.2             10.0.1.2    UP 00:28:32     D
     1 37.37.37.3             10.0.1.3  NHRP 00:00:04     D
     1 47.47.47.4             10.0.1.4   IKE 00:00:09     D
""",
    # IPsec encrypted-WAN universality: core1 is an IOS site-to-site IPsec hub with two crypto sessions.
    # _d_crypto_session_health FIRES: Tunnel1 -> 10.0.255.9 is DOWN-NEGOTIATING (no established IKE/IPsec SA,
    # the spoke behind it is cut off). The healthy companion Tunnel0 -> 10.0.255.2 is UP-ACTIVE and must NOT
    # fire (proves coverage-honest silence on an established tunnel).
    "show crypto session": """\
Crypto session current status

Interface: Tunnel0
Session status: UP-ACTIVE
Peer: 10.0.255.2 port 500
  IKEv2 SA: local 10.0.255.1/500 remote 10.0.255.2/500 Active
  IPSEC FLOW: permit ip 10.0.10.0/255.255.255.0 10.0.20.0/255.255.255.0
        Active SAs: 2, origin: crypto map
Interface: Tunnel1
Session status: DOWN-NEGOTIATING
Peer: 10.0.255.9 port 500
  IKEv2 SA: local 10.0.255.1/500 remote 10.0.255.9/500 Inactive
  IPSEC FLOW: permit ip 10.0.10.0/255.255.255.0 10.0.30.0/255.255.255.0
        Active SAs: 0, origin: crypto map
""",
    # BFD fast-failover (universality): core1 runs BFD with one session DOWN and one UP -> _d_bfd_session_health
    # fires on the Down session only. The Down session (10.0.255.9 on Gi1/0/3) means sub-second failover for its
    # client protocol is broken; the Up session (10.0.255.2 on Gi1/0/1) is the healthy companion that proves the
    # detector does NOT over-fire. Note the 'RH/RS' column is also literally Up/Down -- the parser must read the
    # later 'State' column by position, not the first Up/Down token, or it would misread the healthy row.
    "show bfd neighbors": """\
OurAddr         NeighAddr       LD/RD                 RH/RS           Holdown(mult)     State       Int
10.0.255.1      10.0.255.2      1090519041/1090519040 Up              583(3)            Up          Gi1/0/1
10.0.255.1      10.0.255.9      1090519042/0          Down            N/A(3)            Down        Gi1/0/3
""",
    # IPv6 addressing / neighbor-discovery readiness (universality): core1 is a dual-stack distribution
    # switch. Vlan30's GLOBAL IPv6 address is in the DUPLICATE state ([DUPLICATE]) -- DAD (RFC 4862) found the
    # address already in use, so IOS disabled it -> _d_ipv6_dad_duplicate FIRES on Vlan30 only. The HEALTHY
    # companions (Vlan10 with a clean global address, and Gi1/0/24 also clean) prove the detector does NOT
    # over-fire on a normal dual-stack interface; the TENTATIVE entry on Gi1/0/1 proves a transient DAD state
    # is correctly IGNORED. Grounded verbatim in the Cisco IPv6 command-reference sample output.
    "show ipv6 interface": """\
Vlan10 is up, line protocol is up
  IPv6 is enabled, link-local address is FE80::200:FF:FE00:10
  Global unicast address(es): 2001:DB8:10::1, subnet is 2001:DB8:10::/64
  Joined group address(es): FF02::1 FF02::2 FF02::1:FF00:1
  MTU is 1500 bytes
  ND DAD is enabled, number of DAD attempts: 1
  Hosts use stateless autoconfig for addresses.
Vlan30 is up, line protocol is up
  IPv6 is enabled, link-local address is FE80::200:FF:FE00:30
  Global unicast address(es): 2001:DB8:30::1, subnet is 2001:DB8:30::/64 [DUPLICATE]
  Joined group address(es): FF02::1 FF02::2 FF02::1:FF00:1
  MTU is 1500 bytes
  ND DAD is enabled, number of DAD attempts: 1
  Hosts use stateless autoconfig for addresses.
GigabitEthernet1/0/24 is up, line protocol is up
  IPv6 is enabled, link-local address is FE80::200:FF:FE00:24
  Global unicast address(es): 2001:DB8:FFFE::24, subnet is 2001:DB8:FFFE::/64
  MTU is 1500 bytes
  ND DAD is enabled, number of DAD attempts: 1
GigabitEthernet1/0/1 is up, line protocol is up
  IPv6 is enabled, link-local address is FE80::200:FF:FE00:01
  Global unicast address(es): 2001:DB8:FFFD::1, subnet is 2001:DB8:FFFD::/64 [TENTATIVE]
  MTU is 1500 bytes
  ND DAD is enabled, number of DAD attempts: 1
""",
    # Cisco Catalyst SD-WAN (universality, vManage JSON-ingestion channel): core1 stands in as the vManage
    # Manager query host for an offline /dataservice export. control/connections has a DOWN vsmart connection
    # (actual 0 of expected 2) -> _d_sdwan_control_connection_down FIRES; the UP vbond connection (1/1) proves
    # the detector stays silent on a healthy connection. /device reports BR99-cedge UNREACHABLE ->
    # _d_sdwan_device_unreachable FIRES; the reachable DC1-cedge stays silent. (vManage wraps rows in
    # {"data":[...]}, distinct from ACI's imdata envelope.) Schema grounded in the Catalyst SD-WAN Manager API.
    "dataservice/device/control/connections": """\
{
  "data": [
    {"system-ip": "10.10.1.13", "host-name": "BR13-cedge", "peer-type": "vsmart", "state": "down", "local-color": "mpls", "remote-color": "default", "controlProtocol": "dtls", "expected-connections": 2, "actual-connections": 0, "uptime": "0:00:00:00"},
    {"system-ip": "10.10.1.13", "host-name": "BR13-cedge", "peer-type": "vbond", "state": "up", "local-color": "biz-internet", "controlProtocol": "dtls", "expected-connections": 1, "actual-connections": 1, "uptime": "12:04:33:10"}
  ]
}
""",
    "dataservice/device": """\
{
  "data": [
    {"system-ip": "10.10.1.1", "host-name": "DC1-cedge", "reachability": "reachable", "device-model": "vedge-C8000V", "version": "17.09.03a", "device-type": "vedge"},
    {"system-ip": "10.10.1.99", "host-name": "BR99-cedge", "reachability": "unreachable", "device-model": "vedge-C8000V", "version": "17.09.03a", "device-type": "vedge"}
  ]
}
""",
    # Cisco Catalyst SD-WAN OMP (deeper modeling): /dataservice/device/counters reports per-edge OMP peer
    # counts. BR13-cedge has ompPeersDown=1 (overlay routing degraded -- missing some TLOCs/prefixes even
    # though its control connection is up) -> _d_sdwan_omp_peer_down FIRES; DC1-cedge (ompPeersDown=0) is the
    # healthy companion that proves no over-firing. OMP runs over the control connections, so this is a
    # DISTINCT signal from sdwan-control-connection-down.
    "dataservice/device/counters": """\
{
  "data": [
    {"system-ip": "10.10.1.13", "host-name": "BR13-cedge", "ompPeersUp": 1, "ompPeersDown": 1, "vsmartControlConnections": 1, "bfdSessionsUp": 4, "bfdSessionsDown": 0},
    {"system-ip": "10.10.1.1", "host-name": "DC1-cedge", "ompPeersUp": 2, "ompPeersDown": 0, "vsmartControlConnections": 2, "bfdSessionsUp": 8, "bfdSessionsDown": 0}
  ]
}
""",
}

# --------------------------------------------------------------------------- #
# core2 - NX-OS core switch
# --------------------------------------------------------------------------- #
_CORE2 = {
    # VXLAN-EVPN overlay (universality): core2 is a VTEP with one peer DOWN -> _d_nve_peer_health fires.
    # The engine's own target fabric was blind until parse_nve_peers / build_overlay.
    "show nve peers": """\
Interface Peer-IP          State LearnType Uptime   Router-Mac
--------- ---------------  ----- --------- -------- -----------------
nve1      10.255.0.1       Up    CP        1d05h    5e00.0005.0007
nve1      10.255.0.2       Down  CP        00:00:00 n/a
""",
    # BGP-EVPN control plane (universality): one RR session Idle -> _d_evpn_rr_health fires (overlay route
    # exchange dark even though an NVE data-plane peer is Up).
    "show bgp l2vpn evpn summary": """\
BGP summary information for VRF default, address family L2VPN EVPN
BGP router identifier 10.255.0.7, local AS number 65001
Neighbor        V    AS MsgRcvd MsgSent   TblVer  InQ OutQ Up/Down  State/PfxRcd
10.255.0.254    4 65001    5000    5000      120    0    0 1d05h    240
10.255.0.253    4 65001       0       0        0    0    0 00:00:00 Idle
""",
    # VXLAN VNI bindings (universality): L3VNI 50000 Down -> _d_nve_vni_health fires (VRF stranded).
    "show nve vni": """\
Interface VNI      Multicast-group   State Mode Type [BD/VRF]
nve1      10010    225.1.1.10        Up    CP   L2 [10]
nve1      50000    n/a               Down  CP   L3 [vrf-prod]
""",
    # CoPP drop state (universality): the 'critical' class is actively dropping (violated 4521 bytes) while
    # 'normal' is armed but clean (violated 0) -> _d_copp_drops fires on the dropping class only.
    "show policy-map interface control-plane": """\
Control Plane

  Service-policy input: copp-system-p-policy-strict

    class-map copp-system-p-class-critical (match-any)
      police cir 36000 kbps bc 250 ms
      module 1:
        conformed 177446058 bytes,
          5-min offered rate 3 bytes/sec
        violated 4521 bytes,
          5-min violate rate 12 bytes/sec
    class-map copp-system-p-class-normal (match-any)
      police cir 680 kbps bc 250 ms
      module 1:
        conformed 88231005 bytes,
        violated 0 bytes,
""",
    "show interface status": """\
--------------------------------------------------------------------------------
Port          Name               Status    Vlan      Duplex  Speed   Type
--------------------------------------------------------------------------------
Eth1/1        to-core1-a         connected trunk     full    1000    10g
Eth1/2        to-core1-b         connected trunk     full    1000    10g
Po1           to-core1           connected trunk     full    2000    --
""",
    "show interface switchport": """\
Name: port-channel1
  Switchport: Enabled
  Operational Mode: trunk
  Access Mode VLAN: 1 (default)
  Trunking Native Mode VLAN: 1 (default)
  Trunking VLANs Allowed: 10,20,30
""",
    "show interface trunk": """\
--------------------------------------------------------------------------------
Port          Native  Status        Port
              Vlan                  Channel
--------------------------------------------------------------------------------
Po1           1       trunking      --

--------------------------------------------------------------------------------
Port          Vlans Allowed on Trunk
--------------------------------------------------------------------------------
Po1           10,20,30
""",
    "show running-config interface": """\
interface Ethernet1/1
  description to-core1-a
  switchport mode trunk
  channel-group 1 mode active
interface Ethernet1/2
  description to-core1-b
  switchport mode trunk
  channel-group 1 mode active
interface port-channel1
  description to-core1
  switchport mode trunk
interface Vlan10
  description USERS
  ip address 10.0.10.3/24
  hsrp 10
    ip 10.0.10.1
interface Vlan20
  description VOICE
  ip address 10.0.20.3/24
  hsrp 20
    ip 10.0.20.1
    priority 110
""",
    "show port-channel summary": """\
Flags:  D - Down        P - Up in port-channel (members)
        I - Individual  s - Suspended
--------------------------------------------------------------------------------
Group Port-       Type     Protocol  Member Ports
      Channel
--------------------------------------------------------------------------------
1     Po1(SU)     Eth      LACP      Eth1/1(P)    Eth1/2(P)
""",
    "show spanning-tree": """\
VLAN0010
  Spanning tree enabled protocol rstp
Interface        Role Sts Cost      Prio.Nbr Type
---------------- ---- --- --------- -------- ----
Po1              Desg FWD 1         128.4096 P2p

VLAN0020
  Spanning tree enabled protocol rstp
Interface        Role Sts Cost      Prio.Nbr Type
---------------- ---- --- --------- -------- ----
Po1              Desg FWD 1         128.4096 P2p
""",
    # core1.lab is an assessed device (in scan); wan-edge-rtr1.lab is an INFRA router (Capabilities: Router)
    # NOT in the inventory -> undocumented 'shadow' infrastructure -> _d_shadow_infra fires. The CDP-speaking
    # IP phone (Host Phone) and access point (Trans-Bridge) are EDGE devices and must be IGNORED (no cry-wolf).
    "show cdp neighbors detail": """\
----------------------------------------
Device ID: core1.lab
  IP address: 10.0.99.1
Platform: cisco WS-C3850-24T,  Capabilities: Router Switch
Interface: port-channel1,  Port ID (outgoing port): Port-channel1
----------------------------------------
Device ID: wan-edge-rtr1.lab
  IP address: 10.0.250.1
Platform: cisco ASR1001-X,  Capabilities: Router
Interface: Ethernet1/47,  Port ID (outgoing port): GigabitEthernet0/0/1
----------------------------------------
Device ID: SEP00112233AABB
  IP address: 10.0.40.20
Platform: Cisco IP Phone 8845,  Capabilities: Host Phone
Interface: Ethernet1/20,  Port ID (outgoing port): Port 1
----------------------------------------
Device ID: AP-floor3-01
  IP address: 10.0.50.30
Platform: cisco AIR-AP2802I-B-K9,  Capabilities: Trans-Bridge
Interface: Ethernet1/30,  Port ID (outgoing port): GigabitEthernet0
""",
    # NTP clock-sync STATE (NX-OS): a '*'-selected peer at stratum 2 -> core2 is SYNCHRONIZED -> _d_ntp_sync
    # stays SILENT for core2 (proves the detector does not over-fire on a healthy clock).
    "show ntp peer-status": """\
Total peers : 2
* - selected for sync, + - peer mode(active), - - peer mode(passive), = - polled in client mode
remote               local                st  poll reach delay   vrf
-------------------------------------------------------------------------------
*10.255.0.254        10.255.0.7           2   16   377   0.00107 default
=127.127.1.0         10.255.0.7           8   16   377   0.00000 default
""",
    "show mac address-table": """\
Legend:
        * - primary entry
   VLAN     MAC Address      Type      age     Secure NTFY Ports
---------+-----------------+--------+---------+------+----+------------------
*  10     0011.2233.4455    dynamic   0         F     F   Po1
""",
    "show vlan brief": """\
VLAN Name                             Status    Ports
---- -------------------------------- --------- -------------------------------
10   USERS                            active    Po1
20   VOICE                            active    Po1
""",
    "show hsrp brief": """\
                     P indicates configured to preempt.
                     |
Interface   Grp  Pri P State    Active          Standby         Virtual IP
Vlan10      10   100   Standby  10.0.10.2       local           10.0.10.1
Vlan20      20   110 P Active   local           10.0.20.2       10.0.20.1
""",
    "show ip route": """\
IP Route Table for VRF "default"
C    10.0.10.0/24 is directly connected, Vlan10
L    10.0.10.3/32 is directly connected, Vlan10
C    10.0.20.0/24 is directly connected, Vlan20
L    10.0.20.3/32 is directly connected, Vlan20
""",
    "show version": """\
Cisco Nexus Operating System (NX-OS) Software
  cisco Nexus9000 C93180YC-EX chassis
  Device name: core2
  Processor Board ID FDO12345ABC
""",
    "show interface": """\
Ethernet1/1 is up
  Hardware: 1000/10000 Ethernet, address: 0022.3344.5566
  MTU 1500 bytes, BW 10000000 Kbit
  Full-duplex, 10 Gb/s, media type is 10g
    0 input error 0 CRC 0 short frame
    0 output discard
""",
    "show ip interface brief": """\
IP Interface Status for VRF "default"
Interface            IP Address      Interface Status
Vlan10               10.0.10.3       protocol-up/link-up/admin-up
Vlan20               10.0.20.3       protocol-up/link-up/admin-up
mgmt0                10.0.99.2       protocol-up/link-up/admin-up
""",
    # NEW-V3.23.167 (platform health): NX-OS capacity facts via 'show system resources'
    # (CPU idle + system memory + load). access1 gets NO capacity fixtures on purpose
    # (exercises the declared not-collected path).
    "show system resources": """\
Load average:   1 minute: 0.28   5 minutes: 0.31   15 minutes: 0.32
Processes   :   720 total, 1 running
CPU states  :   3.5% user,   4.1% kernel,   92.4% idle
Memory usage:   16400932K total,   7322120K used,   9078812K free
""",
    # Cisco ACI (universality, JSON-ingestion channel): core2 stands in as the APIC query host for an offline
    # APIC export (moquery -o json). faultInst has TWO raised+unacked critical faults (F1394 fabric port down,
    # F0321 cluster degraded) -> _d_aci_critical_faults FIRES on 2; the minor fault (F1234) and the ACKED major
    # (F3083) prove the severity+ack filter stays silent. fabricNode has a decommissioned ghost (leaf-102-OLD)
    # -> _d_aci_node_not_active FIRES on 1 (the two active nodes stay silent). fabricHealthTotal cur=82 (<90)
    # -> _d_aci_fabric_health_degraded FIRES. Schema grounded in the APIC REST/faults guides (docs/arch-wave).
    "moquery -c faultInst": """\
{
  "totalCount": "4",
  "imdata": [
    {"faultInst": {"attributes": {"code": "F1394", "severity": "critical", "lc": "raised", "ack": "no", "domain": "infra", "cause": "interface-physical-down", "dn": "topology/pod-1/node-101/sys/phys-[eth1/49]/phys/fault-F1394", "descr": "Port is down, reason:sfp-missing, used by:Fabric"}}},
    {"faultInst": {"attributes": {"code": "F0321", "severity": "critical", "lc": "raised", "ack": "no", "domain": "infra", "cause": "cluster-health-degraded", "dn": "topology/pod-1/node-1/av/fault-F0321", "descr": "APIC cluster is degraded: leadership diverged"}}},
    {"faultInst": {"attributes": {"code": "F1234", "severity": "minor", "lc": "raised", "ack": "no", "domain": "tenant", "cause": "config-drift", "dn": "topology/pod-1/node-102/fault-F1234", "descr": "Minor config drift (must stay silent)"}}},
    {"faultInst": {"attributes": {"code": "F3083", "severity": "major", "lc": "raised", "ack": "yes", "domain": "infra", "cause": "known-accepted", "dn": "topology/pod-1/node-204/fault-F3083", "descr": "Acknowledged major fault (must stay silent)"}}}
  ]
}
""",
    "moquery -c fabricNode": """\
{
  "totalCount": "3",
  "imdata": [
    {"fabricNode": {"attributes": {"dn": "topology/pod-1/node-101", "id": "101", "name": "leaf-101", "role": "leaf", "model": "N9K-C93180YC-FX", "serial": "FDO12345ABC", "version": "n9000-16.0(5h)", "fabricSt": "active", "adSt": "on"}}},
    {"fabricNode": {"attributes": {"dn": "topology/pod-1/node-204", "id": "204", "name": "spine-204", "role": "spine", "model": "N9K-C9336C-FX2", "serial": "FDO99999XYZ", "version": "n9000-16.0(5h)", "fabricSt": "active", "adSt": "on"}}},
    {"fabricNode": {"attributes": {"dn": "topology/pod-1/node-102", "id": "102", "name": "leaf-102-OLD", "role": "leaf", "model": "N9K-C93180YC-EX", "serial": "FDO55555OLD", "version": "n9000-15.2(7g)", "fabricSt": "decommissioned", "adSt": "off"}}}
  ]
}
""",
    "moquery -c fabricHealthTotal": """\
{
  "totalCount": "1",
  "imdata": [
    {"fabricHealthTotal": {"attributes": {"dn": "topology/HDfabricOverallHealth5min-0", "cur": "82", "twScore": "82", "maxSev": "critical"}}}
  ]
}
""",
    # Cisco ACI logical inventory (move-group scoping): fvCtx = the VRFs/routing contexts. legacy-vrf has
    # pcEnfPref=unenforced (contract enforcement OFF -> default-permit between all its EPGs) -> the segmentation
    # posture detector _d_aci_vrf_unenforced FIRES; the enforced prod-vrf is the healthy companion (silent).
    "moquery -c fvCtx": """\
{
  "totalCount": "2",
  "imdata": [
    {"fvCtx": {"attributes": {"name": "prod-vrf", "dn": "uni/tn-PROD/ctx-prod-vrf", "pcEnfPref": "enforced", "pcEnfDir": "ingress"}}},
    {"fvCtx": {"attributes": {"name": "legacy-vrf", "dn": "uni/tn-LEGACY/ctx-legacy-vrf", "pcEnfPref": "unenforced", "pcEnfDir": "ingress"}}}
  ]
}
""",
    # Cisco ACI logical CENSUS (move-group-scoping inventory -- pure facts, no detector): the tenants, bridge
    # domains and EPGs are the migration move-group units. Published into snap['aci'] for the deliverables /
    # any future wave-planner; not a broken-state, so it never fires a finding.
    "moquery -c fvTenant": """\
{
  "totalCount": "3",
  "imdata": [
    {"fvTenant": {"attributes": {"name": "PROD", "dn": "uni/tn-PROD"}}},
    {"fvTenant": {"attributes": {"name": "LEGACY", "dn": "uni/tn-LEGACY"}}},
    {"fvTenant": {"attributes": {"name": "common", "dn": "uni/tn-common"}}}
  ]
}
""",
    "moquery -c fvBD": """\
{
  "totalCount": "2",
  "imdata": [
    {"fvBD": {"attributes": {"name": "prod-bd", "dn": "uni/tn-PROD/BD-prod-bd", "unicastRoute": "yes", "arpFlood": "no"}}},
    {"fvBD": {"attributes": {"name": "legacy-bd", "dn": "uni/tn-LEGACY/BD-legacy-bd", "unicastRoute": "no", "arpFlood": "yes"}}}
  ]
}
""",
    "moquery -c fvAEPg": """\
{
  "totalCount": "3",
  "imdata": [
    {"fvAEPg": {"attributes": {"name": "web-epg", "dn": "uni/tn-PROD/ap-app/epg-web-epg"}}},
    {"fvAEPg": {"attributes": {"name": "db-epg", "dn": "uni/tn-PROD/ap-app/epg-db-epg"}}},
    {"fvAEPg": {"attributes": {"name": "legacy-epg", "dn": "uni/tn-LEGACY/ap-legacy/epg-legacy-epg"}}}
  ]
}
""",
}

# --------------------------------------------------------------------------- #
# access1 - IOS access switch (single fiber uplink, no port-channel)
# --------------------------------------------------------------------------- #
_ACCESS1 = {
    "show interface status": """\
Port      Name               Status       Vlan       Duplex  Speed Type
Gi0/1     uplink-to-core1    connected    trunk        full  1000  1000BaseLX SFP
Gi0/2     ap-floor1          connected    10           full  100   10/100/1000BaseTX
Gi0/3     phone-201          connected    10           full  100   10/100/1000BaseTX
Gi0/10    srv-backup         connected    30           full  1000  10/100/1000BaseTX
""",
    "show interfaces switchport": """\
Name: Gi0/1
Switchport: Enabled
Administrative Mode: trunk
Operational Mode: trunk
Access Mode VLAN: 1 (default)
Trunking Native Mode VLAN: 1 (default)
Trunking VLANs Enabled: 10,20,30

Name: Gi0/2
Switchport: Enabled
Administrative Mode: static access
Operational Mode: static access
Access Mode VLAN: 10 (USERS)

Name: Gi0/3
Switchport: Enabled
Administrative Mode: static access
Operational Mode: static access
Access Mode VLAN: 10 (USERS)

Name: Gi0/10
Switchport: Enabled
Administrative Mode: static access
Operational Mode: static access
Access Mode VLAN: 30 (SERVERS)
""",
    "show interfaces trunk": """\
Port        Mode             Encapsulation  Status        Native vlan
Gi0/1       on               802.1q         trunking      1

Port        Vlans allowed on trunk
Gi0/1       10,20,30
""",
    "show running-config | section ^interface": """\
interface GigabitEthernet0/1
 description uplink-to-core1
 switchport trunk encapsulation dot1q
 switchport mode trunk
interface GigabitEthernet0/2
 description ap-floor1
 switchport access vlan 10
 spanning-tree portfast
interface GigabitEthernet0/3
 description phone-201
 switchport access vlan 10
interface GigabitEthernet0/10
 description srv-backup
 switchport access vlan 30
""",
    # IPv6 first-hop security: access1 is OBSERVABLY dual-stack (an IPv6 SVI on Vlan10) with host-facing
    # access ports (Gi0/2/3 vlan 10, Gi0/10 vlan 30) but NO RA-Guard -> _d_ipv6_fhs FIRES (rogue-RA gateway
    # hijack, RFC 6104). build_ipv6_fhs reads the FULL run-config for the dual-stack signal; the FHS
    # show-commands return a defined-but-UNATTACHED policy (which does NOT protect). core1/core2 are IPv4-only
    # / no full run-config -> {} (silent), so EXACTLY ONE switch fires.
    "show running-config": """\
!
hostname access1
!
ipv6 unicast-routing
!
interface GigabitEthernet0/1
 description uplink-to-core1
 switchport trunk encapsulation dot1q
 switchport mode trunk
interface GigabitEthernet0/2
 description ap-floor1
 switchport access vlan 10
 switchport mode access
 spanning-tree portfast
interface GigabitEthernet0/3
 description phone-201
 switchport access vlan 10
 switchport mode access
interface GigabitEthernet0/10
 description srv-backup
 switchport access vlan 30
 switchport mode access
interface Vlan10
 description USERS
 ip address 10.0.10.4 255.255.255.0
 ipv6 address 2001:DB8:10::4/64
interface Vlan30
 description SERVERS
 ip address 10.0.30.4 255.255.255.0
!
line vty 0 4
 transport input ssh
!
""",
    "show ipv6 nd raguard policy": """\
RA guard configured policies:

Policy default configuration:
  device-role host
""",
    "show ipv6 dhcp guard policy": """\
DHCP guard configured policies:

Dhcp guard policy: default
  Device Role: dhcp client
""",
    # ACCESS-EDGE port-security DETAIL: Gi0/3 (phone port) is ERR-DISABLED by a shutdown-mode violation ->
    # Port Status 'Secure-shutdown' -> _d_port_security_errdisable FIRES, naming the offending MAC. Gi0/2 is a
    # clean Secure-up port; Gi0/10 is RESTRICT mode with a nonzero violation COUNT but stays Secure-up -> must
    # NOT fire (the detector keys on the shutdown STATE, not the counter).
    "show port-security interface": """\
Port: GigabitEthernet0/2
Port Security              : Enabled
Port Status                : Secure-up
Violation Mode             : Shutdown
Aging Time                 : 0 mins
Aging Type                 : Absolute
SecureStatic Address Aging : Disabled
Maximum MAC Addresses      : 2
Total MAC Addresses        : 1
Configured MAC Addresses   : 0
Sticky MAC Addresses       : 1
Last Source Address:Vlan   : aabb.ccdd.ee01:10
Security Violation Count   : 0

Port: GigabitEthernet0/3
Port Security              : Enabled
Port Status                : Secure-shutdown
Violation Mode             : Shutdown
Aging Time                 : 0 mins
Aging Type                 : Absolute
SecureStatic Address Aging : Disabled
Maximum MAC Addresses      : 1
Total MAC Addresses        : 1
Configured MAC Addresses   : 0
Sticky MAC Addresses       : 1
Last Source Address:Vlan   : 0011.22aa.0099:10
Security Violation Count   : 3

Port: GigabitEthernet0/10
Port Security              : Enabled
Port Status                : Secure-up
Violation Mode             : Restrict
Aging Time                 : 0 mins
Aging Type                 : Absolute
SecureStatic Address Aging : Disabled
Maximum MAC Addresses      : 1
Total MAC Addresses        : 1
Configured MAC Addresses   : 0
Sticky MAC Addresses       : 1
Last Source Address:Vlan   : aabb.ccdd.ee10:30
Security Violation Count   : 17
""",
    # Storm-control action audit: Gi0/2 has a configured broadcast/multicast threshold but action 'None' -- a
    # storm is dropped SILENTLY -> _d_storm_control_action fires. Gi0/3 is correctly actioned (Shutdown/Trap)
    # and Gi0/1 has no storm-control at all (absent) -> both stay silent (coverage-honest).
    "show storm-control": """\
Key: U - Unicast, B - Broadcast, M - Multicast
Interface Filter State   Upper       Lower       Current    Action    Type
--------- ------------- ----------- ----------- ---------- --------- ----
Gi0/2     Forwarding    5.00%       5.00%       0.12%      None      B
Gi0/2     Forwarding    5.00%       5.00%       0.00%      None      M
Gi0/3     Forwarding    2.00%       2.00%       0.05%      Shutdown  B
Gi0/3     Forwarding    2.00%       2.00%       0.00%      Trap      M
""",
    # NTP clock-sync STATE (IOS): access1's clock IS synchronized (stratum 3) -> _d_ntp_sync stays SILENT for
    # access1 (proves the detector fires only on the genuinely-unsynchronized core1).
    "show ntp status": """\
Clock is synchronized, stratum 3, reference is 10.0.10.2
nominal freq is 250.0000 Hz, actual freq is 250.0000 Hz, precision is 2**18
reference time is E1A2B3C4.00000000 (12:00:00.000 UTC Mon Jun 1 2026)
clock offset is 0.5000 msec, root delay is 1.20 msec
""",
    "show spanning-tree": """\
VLAN0010
  Spanning tree enabled protocol rstp
  Root ID    Priority    24586
             Address     aaaa.0001.0001
             Cost        4
  Bridge ID  Priority    32778  (priority 32768 sys-id-ext 10)
             Address     cccc.0003.0003
Interface        Role Sts Cost      Prio.Nbr Type
---------------- ---- --- --------- -------- ----
Gi0/1            Root FWD 4         128.1    P2p

VLAN0030
  Spanning tree enabled protocol rstp
  Root ID    Priority    32798
             Address     cccc.0003.0003
             This bridge is the root
  Bridge ID  Priority    32798  (priority 32768 sys-id-ext 30)
             Address     cccc.0003.0003
Interface        Role Sts Cost      Prio.Nbr Type
---------------- ---- --- --------- -------- ----
Gi0/1            Desg FWD 4         128.1    P2p
""",
    "show cdp neighbors detail": """\
-------------------------
Device ID: core1.lab
Entry address(es):
  IP address: 10.0.99.1
Platform: cisco WS-C3850-24T,  Capabilities: Router Switch
Interface: GigabitEthernet0/1,  Port ID (outgoing port): GigabitEthernet1/0/24
Holdtime : 160 sec
-------------------------
Device ID: AP-floor1
Entry address(es):
  IP address: 10.0.10.50
Platform: cisco AIR-AP2802I,  Capabilities: Trans-Bridge
Interface: GigabitEthernet0/2,  Port ID (outgoing port): GigabitEthernet0
Holdtime : 130 sec
""",
    "show mac address-table": """\
          Mac Address Table
-------------------------------------------
Vlan    Mac Address       Type        Ports
----    -----------       --------    -----
  10    aabb.ccdd.ee01    DYNAMIC     Gi0/2
  10    aabb.ccdd.ee02    DYNAMIC     Gi0/3
  30    aabb.ccdd.ee10    DYNAMIC     Gi0/10
""",
    "show vlan brief": """\
VLAN Name                             Status    Ports
---- -------------------------------- --------- -------------------------------
10   USERS                            active    Gi0/2, Gi0/3
20   VOICE                            active
30   SERVERS                          active    Gi0/10
""",
    "show version": """\
Cisco IOS Software, C2960X Software (C2960X-UNIVERSALK9-M), Version 15.2(7)E3
cisco WS-C2960X-48FPD-L (APM86XXX) processor (revision A0)
System serial number            : FOC2233B002
Model number                    : WS-C2960X-48FPD-L
""",
    "show interfaces": """\
GigabitEthernet0/1 is up, line protocol is up (connected)
  MTU 1500 bytes, BW 1000000 Kbit/sec, DLY 10 usec
  Full-duplex, 1000Mb/s, media type is 1000BaseLX SFP
  Last input 00:00:00, output 00:00:00, output hang never
     0 input errors, 0 CRC, 0 frame, 0 overrun, 0 ignored
     Total output drops: 0
""",
    "show ip interface brief": """\
Interface              IP-Address      OK? Method Status                Protocol
Vlan1                  unassigned      YES NVRAM  administratively down  down
GigabitEthernet0/0     10.0.99.3       YES NVRAM  up                    up
""",
    # NEW-V3.23.164 (syslog intelligence): a CDP duplex mismatch on an access port and a
    # burst of failed logins (>= the login-fail threshold) -> two access-layer detections.
    "show logging": """\
Syslog logging: enabled (0 messages dropped, 0 messages rate-limited, 0 flushes, 0 overruns)
    Buffer logging: level debugging, 8 messages logged
Log Buffer (4096 bytes):

*May 28 10:01:01.000: %CDP-4-DUPLEX_MISMATCH: duplex mismatch discovered on GigabitEthernet0/5 (not half duplex), with print-floor2 GigabitEthernet0/1 (half duplex).
*May 30 22:13:41.404: %SEC_LOGIN-4-LOGIN_FAILED: Login failed [user: admin] [Source: 10.0.99.77] [localport: 22] [Reason: Login Authentication Failed]
*May 30 22:13:48.612: %SEC_LOGIN-4-LOGIN_FAILED: Login failed [user: admin] [Source: 10.0.99.77] [localport: 22] [Reason: Login Authentication Failed]
*May 30 22:13:55.020: %SEC_LOGIN-4-LOGIN_FAILED: Login failed [user: admin] [Source: 10.0.99.77] [localport: 22] [Reason: Login Authentication Failed]
*May 30 22:14:02.330: %SEC_LOGIN-4-LOGIN_FAILED: Login failed [user: root] [Source: 10.0.99.77] [localport: 22] [Reason: Login Authentication Failed]
*May 30 22:14:09.551: %SEC_LOGIN-4-LOGIN_FAILED: Login failed [user: root] [Source: 10.0.99.77] [localport: 22] [Reason: Login Authentication Failed]
*May 30 22:14:16.808: %SEC_LOGIN-4-LOGIN_FAILED: Login failed [user: root] [Source: 10.0.99.77] [localport: 22] [Reason: Login Authentication Failed]
*Jun  1 08:00:09.121: %SYS-5-CONFIG_I: Configured from console by svc-audit on vty0 (10.0.99.50)
""",
# IPv6 routing plane (dual-stack reachability): access1 is already dual-stack (ipv6 unicast-routing + IPv6 SVIs
# in its run-config). It runs OSPFv3 and IPv6 BGP. _d_ipv6_routing_adjacency FIRES on TWO observed stuck
# adjacencies: OSPFv3 neighbor 10.0.0.9 is EXSTART (MTU-mismatch stuck -> no IPv6 LSDB sync) and IPv6 BGP peer
# 2001:DB8:0:9::9 is Active (never Established -> no IPv6 routes). The healthy companions prove coverage-honest
# silence: 10.0.0.1 FULL/DR and 10.0.0.7 2WAY/DROTHER (2WAY is the INTENTIONAL DROTHER<->DROTHER steady state,
# must NOT fire) and IPv6 BGP peer 2001:DB8:0:1::1 with PfxRcd 12 (Established). 'show ipv6 route summary' is the
# routing-active GATE (census only -- never a firing signal). core1/core2 emit none of these -> {} (silent), so
# EXACTLY ONE switch fires.
"show ipv6 route summary": """\
IPv6 Routing Table - default - 8 entries
Route Source    Networks    Subnets     Overhead    Memory (bytes)
connected       4           0           384         576
local           4           0           384         576
static          0           0           0           0
ospf 1          1           0           96          144
bgp 65001       1           0           96          144
Total           10          0           960         1440
""",
"show ospfv3 neighbor": """\
            OSPFv3 1 address-family ipv6 (router-id 10.0.0.4)

Neighbor ID     Pri   State           Dead Time   Interface ID    Interface
10.0.0.1          1   FULL/DR         00:00:37    16              Vlan10
10.0.0.7          1   2WAY/DROTHER    00:00:35    18              Vlan10
10.0.0.9          0   EXSTART/  -     00:00:33    20              GigabitEthernet0/1
""",
"show bgp ipv6 unicast summary": """\
BGP router identifier 10.0.0.4, local AS number 65001
BGP table version is 15, main routing table version 15
Neighbor                  V         AS  MsgRcvd  MsgSent  TblVer  InQ OutQ Up/Down  State/PfxRcd
2001:DB8:0:1::1           4      65001     3421     3418      15    0    0 1d02h          12
2001:DB8:0:9::9           4      65009        0        0       0    0    0 never    Active
""",
}

# hostname -> (platform, {command: output})
COLLECTIONS: Dict[str, Tuple[str, Dict[str, str]]] = {
    "core1": ("ios", _CORE1),
    "core2": ("nxos", _CORE2),
    "access1": ("ios", _ACCESS1),
}

# devices.json content for an end-to-end main() run (explicit platform + password
# so no autodetect/getpass is ever triggered in a non-interactive test).
DEVICES = [
    {"hostname": h, "ip": f"10.0.99.{i+1}", "username": "svc-audit",
     "password": "x", "platform": plat}
    for i, (h, (plat, _out)) in enumerate(COLLECTIONS.items())
]


def write_collection(root: str) -> str:
    """Write every fixture command to <root>/<hostname>/<transformed>.txt.

    Returns `root`. Mirrors the layout the main script's --no-collect path reads.
    """
    for hostname, (_platform, outputs) in COLLECTIONS.items():
        dev_dir = os.path.join(root, hostname)
        os.makedirs(dev_dir, exist_ok=True)
        for cmd, text in outputs.items():
            with open(os.path.join(dev_dir, cmd_filename(cmd)), "w", encoding="utf-8") as f:
                f.write(text)
    return root
