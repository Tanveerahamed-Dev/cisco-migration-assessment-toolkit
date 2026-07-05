"""End-to-end --redact security regression (audit-3 #8).

`--redact` is documented as the SHARE-SAFE switch. It correctly pseudonymizes the snapshot.json and the
*_explorer.html, but the ALWAYS-produced .xlsx workbook is built from the raw all_interfaces / all_device_physical
dataclasses and saved BEFORE redact_snapshot ever runs on the JSON -- so it used to ship real serials / management
IPs / MACs in the primary deliverable.

This runs the REAL offline pipeline twice over the synthetic collection -- once WITHOUT --redact (to prove the real
inventory genuinely reaches the workbook) and once WITH --redact (to prove every real value is gone and pseudonyms
took their place). It is deliberately end-to-end: it would have FAILED before the redact_collected_inplace +
redact_workbook_cells passes were wired in.
"""
import json
import os
import re
import subprocess
import sys

from openpyxl import Workbook, load_workbook

import synthetic_fixtures as fx

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "COLLECT_PARSE_V3_23_0.py")

# Distinctive REAL inventory values the synthetic collection embeds. Serials come from `show version`; the MAC is a
# `show mac address-table` endpoint; the IPs are SVI HOST addresses (not network/remap-target addresses). None is a
# protocol constant -- HSRP 0000.0c07.acXX and the like are intentionally PRESERVED by redaction, so they are not
# asserted here.
REAL_SERIALS = ("FCW1234A001", "FOC2233B002", "FDO12345ABC")
REAL_MAC_DOTTED = "0011.2233.4455"
REAL_MAC_COLON = "00:11:22:33:44:55"
REAL_SVI_IPS = ("10.0.10.1", "10.0.20.1", "10.0.30.1")


def _run_workbook_cells(base, redact):
    """Run the offline pipeline into `base` and return every workbook cell joined into one string."""
    os.makedirs(base, exist_ok=True)
    collection = fx.write_collection(os.path.join(base, "collection"))
    devices = os.path.join(base, "devices.json")
    with open(devices, "w", encoding="utf-8") as f:
        json.dump(fx.DEVICES, f)
    template = os.path.join(base, "template.xlsx")
    wb = Workbook(); ws = wb.active; ws.title = "Interface Data"
    ws.append(["Hostname", "Port", "Status"]); wb.save(template)
    out_xlsx = os.path.join(base, "out.xlsx")
    cmd = [sys.executable, SCRIPT, "--no-collect", "--collection-dir", collection,
           "--devices-file", devices, "--template", template, "--output", out_xlsx,
           "--no-html", "--no-docx", "--no-pptx", "--no-design", "--no-mop", "--no-crd",
           "--no-engagement", "--no-opshandbook", "--no-archreview", "--workers", "1"]
    if redact:
        cmd.append("--redact")
    proc = subprocess.run(cmd, cwd=base, capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, f"pipeline failed:\nSTDOUT\n{proc.stdout}\nSTDERR\n{proc.stderr}"
    wb = load_workbook(out_xlsx, read_only=True, data_only=True)
    return "\n".join(str(c) for s in wb.sheetnames
                     for row in wb[s].iter_rows(values_only=True) for c in row if c is not None)


def test_redact_workbook_does_not_leak_real_inventory(tmp_path):
    # 1) WITHOUT --redact the workbook genuinely CONTAINS the real inventory -> these are real leak vectors, so the
    #    --redact assertions below are non-vacuous.
    plain = _run_workbook_cells(str(tmp_path / "plain"), redact=False)
    assert REAL_SERIALS[0] in plain, "fixture serial should reach the unredacted workbook (test would be vacuous otherwise)"
    assert REAL_MAC_DOTTED in plain, "fixture endpoint MAC should reach the unredacted workbook"

    # 2) WITH --redact, NONE of the real serials / MACs / SVI IPs survive in ANY cell of ANY sheet, and the
    #    pseudonyms ARE present (proving redaction ran, not that the data merely vanished).
    redacted = _run_workbook_cells(str(tmp_path / "redact"), redact=True)
    for s in REAL_SERIALS:
        assert s not in redacted, f"real serial {s} leaked into the --redact workbook"
    assert REAL_MAC_DOTTED not in redacted and REAL_MAC_COLON not in redacted, \
        "real endpoint MAC leaked into the --redact workbook"
    for ip in REAL_SVI_IPS:
        assert ip not in redacted, f"real SVI host IP {ip} leaked into the --redact workbook"
    assert re.search(r"\bSN\d{4}\b", redacted), "expected pseudonymized serials (SN####) -> redaction did not run"


def test_make_redactor_ip_map_never_reproduces_a_real_address():
    """[NRFU sheet audit] The per-call IPv4 pseudonym map must be COLLISION-PROOF: with the old in-band
    `10.{len(ip_map)}`-indexed scheme, the Nth distinct real /24 could draw a pseudonym equal to ANOTHER
    real net (observed: net 10.0.20 -> '10.0.10', re-emitting the real gateway 10.0.10.1 into a --redact
    workbook), or a net at its own index survived VERBATIM (identity). Pseudonyms now live in the
    IANA-reserved 240.0.0.0/4 (Class E) block, which no deployed device can carry — so a scrubbed output
    can never contain a real input IP."""
    from cisco_toolkit.html import _make_redactor
    scrub, _ = _make_redactor()
    # 12 distinct real /24s, so 10.0.10 and 10.0.20 sit near their own would-be indices; host octet .1
    # everywhere makes any in-band collision reproduce a real address exactly.
    reals = [f"10.0.{n}.1" for n in (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 20)]
    outs = [scrub(ip) for ip in reals]
    for real in reals:
        assert all(real not in o for o in outs), f"real address {real} reproduced by the pseudonym map"
    # /24 grouping is preserved and the pseudonym space is the unassignable Class E block
    assert all(o.startswith("240.") and o.endswith(".1") for o in outs), outs
    # the belt-and-braces guards hold even for a (theoretically impossible) 240.x input:
    assert scrub("240.0.0.7") != "240.0.0.7"
    # determinism within a call: the same input scrubs to the same output
    assert scrub(reals[0]) == outs[0]
