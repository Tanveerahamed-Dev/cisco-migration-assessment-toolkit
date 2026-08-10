"""Ratchets between live controller owners and the Atlas capability catalog.

The catalog is a bounded support statement, not a second implementation
registry. These tests fail when the executable collector denominator changes
without the owner and capability records changing with it.
"""

import json
from pathlib import Path
import subprocess
import sys

from cisco_toolkit import rest_collect


ROOT = Path(__file__).resolve().parents[1]


def _load(relative_path):
    return json.loads((ROOT / relative_path).read_text(encoding="utf-8"))


def _capability(catalog, capability_id):
    return next(
        entry
        for domain in catalog["domains"]
        for entry in domain["entries"]
        if entry["id"] == capability_id
    )


def test_live_controller_registry_is_the_cli_and_catalog_denominator():
    expected = {
        "apic": rest_collect.collect_apic,
        "vmanage": rest_collect.collect_vmanage,
        "ise": rest_collect.collect_ise,
        "fmc": rest_collect.collect_fmc,
    }
    assert rest_collect.CONTROLLER_COLLECTORS == expected

    help_run = subprocess.run(
        [sys.executable, "-m", "cisco_toolkit.rest_collect", "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert help_run.returncode == 0, help_run.stderr
    for choice in expected:
        assert choice in help_run.stdout

    core = _load("master-reference/content/atlas-core.json")
    owner = next(row for row in core["owners"] if row["id"] == "owner.rest.collection")
    for function in expected.values():
        assert function.__name__ in owner["symbol"]
    for label in ("APIC", "vManage", "ISE", "FMC"):
        assert label in owner["claim_scope"]

    doctrine_line = next(
        line
        for line in (ROOT / "CLAUDE.md").read_text(encoding="utf-8").splitlines()
        if "rest_collect.CONTROLLER_COLLECTORS" in line
    )
    for choice in expected:
        assert choice in doctrine_line
    assert "--password-env" in doctrine_line
    assert "dedicated read-only RBAC is the hard control" in doctrine_line

    catalog = _load("master-reference/content/capability-catalog.json")
    for capability_id in (
        "cap.security.identity-ise",
        "cap.vendor.cisco-ise",
        "cap.vendor.cisco-fmc",
        "cap.channel.controller-rest",
    ):
        capability = _capability(catalog, capability_id)
        assert "owner.rest.collection" in capability["owner_refs"]
        scope = capability["current_scope"].lower()
        assert "collector" in scope or "collection" in scope
        assert "no live collector" not in scope
        assert "live collection are incomplete" not in scope

    governance = _load("master-reference/content/delivery-governance.json")
    channel_gap = next(row for row in governance["gaps"] if row["id"] == "gap.controller-channels")
    for shipped in ("APIC", "vManage", "ISE", "FMC"):
        assert shipped in channel_gap["problem"]
    assert "have opt-in HTTPS evidence collectors" in channel_gap["problem"]
    assert "live only for APIC and vManage" not in channel_gap["title"]


def test_shipped_vendor_channels_do_not_retain_the_remaining_channel_gap():
    catalog = _load("master-reference/content/capability-catalog.json")
    for capability_id in (
        "cap.vendor.cisco-apic",
        "cap.vendor.cisco-vmanage",
        "cap.vendor.cisco-ise",
        "cap.vendor.cisco-fmc",
    ):
        capability = _capability(catalog, capability_id)
        assert "gap.controller-channels" not in capability["gap_refs"]
        assert capability["gap_refs"], "partial capability must retain its real residuals"
