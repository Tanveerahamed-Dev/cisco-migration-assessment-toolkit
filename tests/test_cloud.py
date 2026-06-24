"""Public-cloud (AWS) network-exposure assessment -- the FIRST cloud-domain axis.

Proves the engine extends beyond on-prem multi-vendor to PUBLIC CLOUD, reusing the offline JSON-ingestion
pattern (a cloud account is added as a 'device', like the ACI/ISE/FMC controllers; its read-only export --
'aws ec2 describe-security-groups' -- is read through the same _load_cmd_output path). Covers
parse_aws_security_groups, build_cloud, the _signals extraction, the _d_cloud_sg_open_ingress detector, the KB
principle and the _ARCH_COVERAGE_REGISTRY entry.

FIRING STATE (coverage-honest, CIS AWS 5.2/5.3): a security group that allows INBOUND from 0.0.0.0/0 (or ::/0)
to a SENSITIVE admin port (SSH/RDP/DB/...) or to ALL ports/protocols -- the host is exposed to the entire
internet. SILENT for a SG open only on 80/443 (a legitimate public web tier), for internal-only rules, and for
no SG export. Surfaces the EXPOSURE ('open to the world'), never claims a vulnerability. JSON shape per the AWS
EC2 DescribeSecurityGroups API."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from cisco_toolkit import parse        # noqa: E402
from cisco_toolkit import build        # noqa: E402
import cisco_toolkit.design_advisor as da  # noqa: E402
import cisco_toolkit.design_kb as design_kb  # noqa: E402


# --- real 'aws ec2 describe-security-groups' JSON (per the EC2 DescribeSecurityGroups API) -----------------
# sg-web: 443 open to the world -> a legitimate public web tier (must STAY SILENT -- no cry-wolf).
# sg-adm: SSH(22) open to the world (a CIS 5.2 finding) PLUS an internal-only mgmt rule (must NOT fire).
_OPEN_SSH = """\
{"SecurityGroups": [
  {"GroupId": "sg-0web01", "GroupName": "web-tier", "VpcId": "vpc-1", "IpPermissions": [
    {"IpProtocol": "tcp", "FromPort": 443, "ToPort": 443, "IpRanges": [{"CidrIp": "0.0.0.0/0"}], "Ipv6Ranges": []}
  ]},
  {"GroupId": "sg-0adm01", "GroupName": "admin-sg", "VpcId": "vpc-1", "IpPermissions": [
    {"IpProtocol": "tcp", "FromPort": 22, "ToPort": 22, "IpRanges": [{"CidrIp": "0.0.0.0/0", "Description": "ssh from anywhere"}], "Ipv6Ranges": []},
    {"IpProtocol": "tcp", "FromPort": 8080, "ToPort": 8090, "IpRanges": [{"CidrIp": "10.0.0.0/8"}], "Ipv6Ranges": []}
  ]}
]}
"""
# all protocols/ports open to the world (IpProtocol -1) -- the worst case.
_ALL_OPEN = """\
{"SecurityGroups": [
  {"GroupId": "sg-0all01", "GroupName": "danger", "VpcId": "vpc-1", "IpPermissions": [
    {"IpProtocol": "-1", "IpRanges": [{"CidrIp": "0.0.0.0/0"}], "Ipv6Ranges": []}
  ]}
]}
"""
# RDP open to the world via IPv6 (::/0) -- IPv6 exposure must fire too.
_RDP_V6 = """\
{"SecurityGroups": [
  {"GroupId": "sg-0rdp01", "GroupName": "win", "VpcId": "vpc-1", "IpPermissions": [
    {"IpProtocol": "tcp", "FromPort": 3389, "ToPort": 3389, "IpRanges": [], "Ipv6Ranges": [{"CidrIpv6": "::/0"}]}
  ]}
]}
"""
# Present export, but only 80/443 open to the world -> assessed, nothing critical -> CLEAN (silent).
_WEB_ONLY = """\
{"SecurityGroups": [
  {"GroupId": "sg-0web02", "GroupName": "web", "VpcId": "vpc-1", "IpPermissions": [
    {"IpProtocol": "tcp", "FromPort": 80, "ToPort": 80, "IpRanges": [{"CidrIp": "0.0.0.0/0"}], "Ipv6Ranges": []},
    {"IpProtocol": "tcp", "FromPort": 443, "ToPort": 443, "IpRanges": [{"CidrIp": "0.0.0.0/0"}], "Ipv6Ranges": []}
  ]}
]}
"""
# Present export, SSH allowed only from an internal CIDR -> not world-open -> CLEAN (silent).
_INTERNAL = """\
{"SecurityGroups": [
  {"GroupId": "sg-0int01", "GroupName": "mgmt", "VpcId": "vpc-1", "IpPermissions": [
    {"IpProtocol": "tcp", "FromPort": 22, "ToPort": 22, "IpRanges": [{"CidrIp": "10.0.0.0/8"}], "Ipv6Ranges": []}
  ]}
]}
"""


def _snap(*sg_jsons):
    cloud = {}
    for i, j in enumerate(sg_jsons):
        sgs = parse.parse_aws_security_groups(j)
        if sgs is not None:                                # None = no/invalid export; [] or [...] = observed
            cloud[f"acct{i + 1}"] = {"security_groups": sgs}
    return {"cloud": cloud}


def _fire(snap):
    sig = da._signals(snap)
    return da._d_cloud_sg_open_ingress(snap, sig)


# ----------------------------------------------------------------------------- parser
def test_parse_collects_world_open_ingress():
    sgs = parse.parse_aws_security_groups(_OPEN_SSH)
    by = {s["group_id"]: s for s in sgs}
    # both web (443) and admin (22) are world-open and collected; the internal 8080-8090 rule is NOT
    assert by["sg-0web01"]["open_ingress"][0]["from_port"] == 443
    adm = by["sg-0adm01"]["open_ingress"]
    assert len(adm) == 1 and adm[0]["from_port"] == 22 and adm[0]["cidr"] == "0.0.0.0/0"


def test_parse_present_but_nothing_world_open_is_empty_list_not_none():
    # an export that parses but has no world-open ingress -> [] (OBSERVED/clean), distinct from None (absent)
    assert parse.parse_aws_security_groups(_INTERNAL) == []
    assert parse.parse_aws_security_groups('{"SecurityGroups": []}') == []


def test_parse_no_or_invalid_export_is_none():
    for bad in ("", "not json", "[1,2,3]", "{}", '{"Foo": 1}'):
        assert parse.parse_aws_security_groups(bad) is None


def test_build_cloud_offline(tmp_path):
    d = tmp_path / "aws-acct"
    d.mkdir()
    (d / "aws_ec2_describe-security-groups.txt").write_text(_OPEN_SSH, encoding="utf-8")
    out = build.build_cloud({"aws ec2 describe-security-groups": str(d / "aws_ec2_describe-security-groups.txt")})
    assert isinstance(out.get("security_groups"), list) and any(s["group_id"] == "sg-0adm01" for s in out["security_groups"])
    assert build.build_cloud({}) == {}                     # no export -> not observed


# ----------------------------------------------------------------------------- detector: FIRES on exposure
def test_fires_on_ssh_open_to_world():
    d = _fire(_snap(_OPEN_SSH))
    assert d and d["id"] == "cloud-security-group-open-ingress" and d["priority"] in ("High", "Critical")
    s = d["evidence"]["summary"]
    assert "sg-0adm01" in s and "22" in s and "0.0.0.0/0" in s
    assert "sg-0web01" not in s                            # 443-to-world is NOT flagged (no cry-wolf)


def test_fires_on_all_ports_open():
    d = _fire(_snap(_ALL_OPEN))
    assert d and "ALL" in d["evidence"]["summary"]


def test_fires_on_rdp_open_via_ipv6():
    d = _fire(_snap(_RDP_V6))
    assert d and "3389" in d["evidence"]["summary"] and "::/0" in d["evidence"]["summary"]


# ----------------------------------------------------------------------------- detector: SILENT on clean
def test_silent_on_public_web_tier():
    assert _fire(_snap(_WEB_ONLY)) is None                 # 80/443 open to the world is a legitimate web tier


def test_silent_on_internal_only_admin():
    assert _fire(_snap(_INTERNAL)) is None                 # SSH from 10/8 is not world-open


def test_silent_when_no_export():
    assert _fire(_snap("")) is None                        # parse -> None -> no axis
    assert _fire({"cloud": {}}) is None
    assert _fire({}) is None


# ----------------------------------------------------------------------------- robustness (proposer != verifier)
def test_detector_never_raises_on_malformed_axis():
    for bad in ({"cloud": "x"}, {"cloud": ["acct"]}, {"cloud": {"a": "x"}},
                {"cloud": {"a": {"security_groups": "x"}}},
                {"cloud": {"a": {"security_groups": [{"open_ingress": "x"}]}}},
                {"cloud": {"a": {"security_groups": [{"open_ingress": [{"from_port": None, "to_port": None, "proto": None}]}]}}}):
        sig = da._signals(bad)
        out = da._d_cloud_sg_open_ingress(bad, sig)
        assert out is None or isinstance(out, dict)


# ----------------------------------------------------------------------------- KB principle + registry
def test_principle_complete_and_engine_actionable():
    p = design_kb.by_id("cloud-security-group-open-ingress")
    assert p and p["engine_actionable"] is True and p["domain"] == "cloud"
    for k in ("title", "design_intent", "observable", "trigger", "recommended_action",
              "alternatives", "tradeoffs", "citation"):
        assert (p.get(k) or "").strip(), f"principle missing {k}"
    assert "CIS" in p["citation"] or "AWS" in p["citation"]


def test_cloud_in_architecture_coverage_registry():
    keys = {axis for axis, *_ in da._ARCH_COVERAGE_REGISTRY}
    assert "cloud" in keys
    snap = _snap(_OPEN_SSH) | {"design_blueprint": {"decisions": [{"id": "cloud-security-group-open-ingress"}]}}
    cov = da.compute_architecture_coverage(snap)
    by = {c["key"]: c for c in cov["classes"]}
    assert by["cloud"]["observed"] and by["cloud"]["status"] == "finding" and by["cloud"]["channel"] == "json"
    none = {c["key"]: c for c in da.compute_architecture_coverage({})["classes"]}
    assert none["cloud"]["status"] == "not-observed"
