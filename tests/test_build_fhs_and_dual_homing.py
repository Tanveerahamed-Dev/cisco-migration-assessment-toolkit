"""[review 2026-07-28 #45 / #46 -- cisco_toolkit/build.py] Two builders that reported a protection /
redundancy the evidence does not support.

  * #45 ``build_ipv6_fhs`` walked the running-config with a ``cur_if`` that was set on ``interface <X>`` and
    NEVER cleared, while ``^ipv6 nd raguard\\b`` / ``^ipv6 dhcp guard\\b`` also match the GLOBAL policy
    stanza HEADERS ``ipv6 nd raguard policy <NAME>`` / ``ipv6 dhcp guard policy <NAME>``. A dual-stack box
    that DEFINES both policies and attaches NEITHER therefore reported ``ra_guard_present: True`` naming a
    real interface -- first-hop security "in place" on a switch wide open to rogue RA (RFC 6104) and rogue
    DHCPv6, with the downstream ``_d_ipv6_fhs`` detector silenced.
  * #46 ``detect_cross_device_dual_connections`` keyed on ``(hostname, port)`` without ever checking the two
    locations sit on DIFFERENT devices -- and ``build_interfaces`` step 7 actively MANUFACTURES that
    duplicate by copying ``end_host_mac`` between a port-channel and each of its physical members. A
    single-homed endpoint behind ONE switch's LAG was reported dual-homed: a false redundancy claim that
    HIDES a single point of failure during move-group planning.

Non-vacuity: against the pre-fix module the #45 case returns ``ra_guard_ifaces ['Vlan10']`` with both
``_present`` True, and the #46 case flags all three ports of the one switch ``dual_connection == 'Yes'``.
"""
import pytest

from cisco_toolkit import build

# ------------------------------------------------------------------------------------------------ #45

DEFINED_BUT_UNATTACHED = """version 16.12
hostname sw1
!
ipv6 unicast-routing
!
interface GigabitEthernet1/0/1
 description ACCESS PORT - nothing attached
 switchport mode access
 switchport access vlan 10
!
interface Vlan10
 ipv6 address 2001:DB8:10::1/64
!
ipv6 nd raguard policy HOST_POLICY
 device-role host
!
ipv6 dhcp guard policy CLIENT_POLICY
 device-role client
!
line vty 0 4
end
"""

ATTACHED_ON_THE_INTERFACE = """hostname sw2
!
ipv6 nd raguard policy HOST_POLICY
 device-role host
!
interface GigabitEthernet1/0/1
 switchport mode access
 ipv6 nd raguard attach-policy HOST_POLICY
 ipv6 dhcp guard attach-policy CLIENT_POLICY
!
interface Vlan10
 ipv6 address 2001:DB8:10::1/64
!
end
"""

ATTACHED_BARE = ATTACHED_ON_THE_INTERFACE.replace(
    " ipv6 nd raguard attach-policy HOST_POLICY", " ipv6 nd raguard").replace(
    " ipv6 dhcp guard attach-policy CLIENT_POLICY", " ipv6 dhcp guard")

ATTACHED_ON_THE_VLAN = """hostname sw3
!
ipv6 nd raguard policy HOST_POLICY
 device-role host
!
interface GigabitEthernet1/0/1
 switchport mode access
!
interface Vlan10
 ipv6 address 2001:DB8:10::1/64
!
vlan configuration 10
 ipv6 nd raguard attach-policy HOST_POLICY
 ipv6 dhcp guard attach-policy CLIENT_POLICY
!
end
"""


def _fhs(tmp_path, run_text, name="run.txt"):
    p = tmp_path / name
    p.write_text(run_text, encoding="utf-8")
    return build.build_ipv6_fhs({"show running-config": str(p)})


def test_defined_but_unattached_fhs_policies_are_not_reported_as_present(tmp_path):
    """The global stanza HEADER is a definition, not an attachment. Crediting it to the last interface seen
    turned a wide-open dual-stack switch into a protected one."""
    fhs = _fhs(tmp_path, DEFINED_BUT_UNATTACHED)
    assert fhs["dualstack"] is True, "the IPv6 SVI must still be observed -- the walk still works"
    assert fhs["ra_guard_ifaces"] == [] and fhs["dhcp_guard_ifaces"] == []
    assert fhs["ra_guard_present"] is False, "RA-Guard is DEFINED, attached nowhere -- rogue RA is open"
    assert fhs["dhcp_guard_present"] is False


DEFINED_BEFORE_THE_INTERFACES = """version 16.12
hostname sw1
!
ipv6 unicast-routing
!
ipv6 nd raguard policy HOST_POLICY
 device-role host
!
ipv6 dhcp guard policy CLIENT_POLICY
 device-role client
!
interface GigabitEthernet1/0/1
 description ACCESS PORT - nothing attached
 switchport mode access
 switchport access vlan 10
!
interface Vlan10
 ipv6 address 2001:DB8:10::1/64
!
line vty 0 4
end
"""


def test_policy_definition_order_does_not_change_the_verdict(tmp_path):
    """The old walk was order-dependent, which is how the same estate could read two ways: with the policy
    stanzas BEFORE the interfaces `cur_if` was still empty and the config read (correctly) unprotected;
    emitted AFTER them, the identical config reported first-hop security on the last interface. Same
    evidence, one answer."""
    after = _fhs(tmp_path, DEFINED_BUT_UNATTACHED, "after.txt")
    before = _fhs(tmp_path, DEFINED_BEFORE_THE_INTERFACES, "before.txt")
    for k in ("ra_guard_ifaces", "dhcp_guard_ifaces", "ra_guard_present", "dhcp_guard_present"):
        assert after[k] == before[k], k
    assert after["ra_guard_present"] is False and after["dhcp_guard_present"] is False


@pytest.mark.parametrize("cfg, ids", [(ATTACHED_ON_THE_INTERFACE, ["Gi1/0/1"]),
                                      (ATTACHED_BARE, ["Gi1/0/1"])],
                         ids=["attach-policy", "bare"])
def test_a_real_per_interface_attachment_is_still_detected(tmp_path, cfg, ids):
    """Non-vacuity: the fix must not blind the builder to genuine first-hop security. Both spellings of the
    interface-level command (`attach-policy <NAME>` and the bare default-policy form) still count."""
    fhs = _fhs(tmp_path, cfg)
    assert fhs["ra_guard_ifaces"] == ids and fhs["dhcp_guard_ifaces"] == ids
    assert fhs["ra_guard_present"] is True and fhs["dhcp_guard_present"] is True


def test_a_vlan_wide_attachment_counts_as_present_but_names_no_interface(tmp_path):
    """`vlan configuration <ids>` really does protect -- it just protects a VLAN, not a port. Credit the
    presence; never invent an interface list for it (which is what the stale cur_if used to do)."""
    fhs = _fhs(tmp_path, ATTACHED_ON_THE_VLAN)
    assert fhs["ra_guard_present"] is True and fhs["dhcp_guard_present"] is True
    assert fhs["ra_guard_ifaces"] == [] and fhs["dhcp_guard_ifaces"] == []


def test_pure_ipv4_device_still_contributes_nothing(tmp_path):
    """The {} contract: a device with no IPv6 at all must stay silent so the detector never cries wolf."""
    assert _fhs(tmp_path, "hostname sw9\n!\ninterface Vlan10\n ip address 10.0.0.1 255.255.255.0\n!\nend\n") == {}


# ------------------------------------------------------------------------------------------------ #46

def test_a_lag_on_one_switch_is_not_a_dual_connection():
    """Po1 and its physical members carry the SAME MAC by construction (build_interfaces step 7 copies it
    between them), so the old (hostname, port) keying reported a single-homed endpoint as dual-homed."""
    ID = build.InterfaceData
    ai = {"sw1": {"Po1": ID(port="Po1", end_host_mac="dead.beef.0001"),
                  "Gi1/0/1": ID(port="Gi1/0/1", end_host_mac="dead.beef.0001"),
                  "Gi1/0/2": ID(port="Gi1/0/2", end_host_mac="dead.beef.0001")}}
    build.detect_cross_device_dual_connections(ai)
    assert [d.dual_connection for d in ai["sw1"].values()] == ["", "", ""]


def test_a_mac_on_two_switches_is_still_flagged():
    """Non-vacuity: the real cross-device case -- the whole point of the function -- is unchanged."""
    ID = build.InterfaceData
    ai = {"sw1": {"Po1": ID(port="Po1", end_host_mac="dead.beef.0002"),
                  "Gi1/0/1": ID(port="Gi1/0/1", end_host_mac="dead.beef.0002")},
          "sw2": {"Gi1/0/9": ID(port="Gi1/0/9", end_host_mac="dead.beef.0002")}}
    build.detect_cross_device_dual_connections(ai)
    assert ai["sw1"]["Po1"].dual_connection == "Yes"
    assert ai["sw1"]["Gi1/0/1"].dual_connection == "Yes"
    assert ai["sw2"]["Gi1/0/9"].dual_connection == "Yes"


def test_same_port_name_on_two_switches_is_a_dual_connection():
    """The devices differ even though the port names collide -- keying on the hostname set, not on the
    (hostname, port) pair count, is what makes this case work."""
    ID = build.InterfaceData
    ai = {"sw1": {"Gi1/0/5": ID(port="Gi1/0/5", end_host_mac="dead.beef.0003")},
          "sw2": {"Gi1/0/5": ID(port="Gi1/0/5", end_host_mac="dead.beef.0003")}}
    build.detect_cross_device_dual_connections(ai)
    assert ai["sw1"]["Gi1/0/5"].dual_connection == "Yes"
    assert ai["sw2"]["Gi1/0/5"].dual_connection == "Yes"
