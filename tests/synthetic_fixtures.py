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
    # classic gap _d_fhrp_resilience now catches. AJ ran zero FHRP, so this fixture is the first to prove
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
    "show cdp neighbors detail": """\
----------------------------------------
Device ID: core1.lab
  IP address: 10.0.99.1
Platform: cisco WS-C3850-24T,  Capabilities: Router Switch
Interface: port-channel1,  Port ID (outgoing port): Port-channel1
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
