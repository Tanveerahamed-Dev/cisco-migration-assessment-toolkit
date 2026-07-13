"""Tests for offline external-SoT import + intent-vs-observed reconcile (roadmap B / NetClaw netbox-reconcile).

ssot.reconcile is INTERNAL-only (published canonical vs raw derivation). This adds the OTHER reconcile:
ingest a declared inventory (CMDB/NetBox/CSV export) from a file drop and diff it against the collected
evidence — emitting a named drift taxonomy plus the coverage-honest UNVERIFIABLE 5th state for a device
that is declared but was never collected (a blind spot, never a silent match or a silent miss).
"""
from cisco_toolkit import external_import as ei


def test_normalize_rows_maps_column_aliases():
    rows = [{"hostname": "SW1", "device_type": "C9300-48P", "primary_ip": "10.0.0.1", "serial_number": "FOC123"}]
    out = ei.normalize_rows(rows)
    assert out[0] == {"host": "SW1", "model": "C9300-48P", "mgmt_ip": "10.0.0.1", "serial": "FOC123"}


def test_read_inventory_csv():
    text = "hostname,device_type,primary_ip\nSW1,C9300-48P,10.0.0.1\nSW2,C9300-24P,10.0.0.2\n"
    rows = ei.read_inventory_csv(text)
    assert len(rows) == 2 and rows[0]["host"] == "SW1" and rows[1]["mgmt_ip"] == "10.0.0.2"


def test_reconcile_external_named_taxonomy_with_unverifiable():
    snap = {
        "lifecycle_risk": {"per_device": [
            {"host": "SW1", "model": "C9300-48P"},
            {"host": "SW2", "model": "C9300-24P"},
            {"host": "SW7", "model": "C9200-24T"},     # observed but not declared -> UNDOCUMENTED
        ]},
        "collection_completeness": {"devices": [
            {"host": "SW4", "status": "not collected"},  # in inventory, never collected -> UNVERIFIABLE
        ]},
    }
    declared = [
        {"host": "SW1", "model": "C9300-48P"},           # matches -> no row
        {"host": "SW2", "model": "C9300-24X"},           # MODEL_MISMATCH (24X vs 24P)
        {"host": "SW4", "model": "C9200"},               # declared but uncollected -> UNVERIFIABLE
        {"host": "SW9", "model": "C9500-48Y"},           # declared, never observed -> MISSING_DEVICE
    ]
    out = ei.reconcile_external(snap, declared)
    by = {r["host"]: r for r in out["rows"]}
    assert "SW1" not in by                                # a clean match emits no drift row
    assert by["SW2"]["type"] == "MODEL_MISMATCH"
    assert by["SW4"]["type"] == "UNVERIFIABLE"
    assert by["SW9"]["type"] == "MISSING_DEVICE"
    assert by["SW7"]["type"] == "UNDOCUMENTED_DEVICE"
    assert out["summary"]["MODEL_MISMATCH"] == 1
    assert out["summary"]["UNVERIFIABLE"] == 1
    assert out["summary"]["MISSING_DEVICE"] == 1
    assert out["summary"]["UNDOCUMENTED_DEVICE"] == 1


def test_reconcile_is_case_insensitive_on_host():
    snap = {"lifecycle_risk": {"per_device": [{"host": "Core-1", "model": "X"}]}}
    out = ei.reconcile_external(snap, [{"host": "core-1", "model": "X"}])
    assert out["rows"] == []                              # same device, different case -> matched, no drift


# --- review-wave-1 regression tests --------------------------------------------------------------

def test_utf8_bom_csv_still_parses():
    text = "﻿hostname,device_type,primary_ip\nSW1,C9300-48P,10.0.0.1\n"   # Excel 'Save as CSV UTF-8' BOM
    rows = ei.read_inventory_csv(text)
    assert len(rows) == 1 and rows[0]["host"] == "SW1"   # was: [] (whole inventory silently discarded)


def test_cidr_mgmt_ip_no_spurious_ip_drift():
    snap = {"lifecycle_risk": {"per_device": [{"host": "SW1", "model": "C9300-48P", "mgmt_ip": "10.0.0.1"}]}}
    out = ei.reconcile_external(snap, [{"host": "SW1", "model": "C9300-48P", "mgmt_ip": "10.0.0.1/24"}])
    assert out["summary"]["IP_DRIFT"] == 0               # NetBox stores CIDR; same host address -> no drift


def test_partial_device_is_unverifiable_not_missing():
    snap = {"collection_completeness": {"devices": [{"host": "SW-PART", "status": "partial"}]}}
    out = ei.reconcile_external(snap, [{"host": "SW-PART", "model": "C9300"}])
    by = {r["host"]: r for r in out["rows"]}
    assert by["SW-PART"]["type"] == "UNVERIFIABLE"        # partially observed -> presence cannot be refuted


def test_duplicate_declared_hosts_deduped():
    snap = {"lifecycle_risk": {"per_device": [{"host": "SW1", "model": "A"}]}}
    out = ei.reconcile_external(snap, [{"host": "SW1", "model": "B"}, {"host": "SW1", "model": "C"}])
    assert out["summary"]["MODEL_MISMATCH"] == 1 and out["summary"]["n_declared"] == 1   # one row per host


def test_raw_alias_columns_normalized_even_when_host_present():
    snap = {"lifecycle_risk": {"per_device": [{"host": "SW1", "model": "C9300-24P"}]}}
    out = ei.reconcile_external(snap, [{"host": "SW1", "device_type": "C9300-48P"}])   # host literal + raw alias
    assert out["summary"]["MODEL_MISMATCH"] == 1         # was: 0 (alias never canonicalized, drift missed)


def test_read_inventory_file_csv_and_xlsx(tmp_path):
    csv_p = tmp_path / "inv.csv"
    csv_p.write_text("hostname,device_type\nSW1,C9300-48P\n", encoding="utf-8")
    assert ei.read_inventory_file(str(csv_p)) == [{"host": "SW1", "model": "C9300-48P"}]
    from openpyxl import Workbook
    xl = tmp_path / "inv.xlsx"
    wb = Workbook(); ws = wb.active
    ws.append(["hostname", "device_type", "primary_ip"]); ws.append(["SW2", "C9500", "10.0.0.2"]); wb.save(str(xl))
    rows = ei.read_inventory_file(str(xl))
    assert rows[0]["host"] == "SW2" and rows[0]["model"] == "C9500" and rows[0]["mgmt_ip"] == "10.0.0.2"


def test_reconcile_flags_ip_drift():
    """The 5th drift type, IP_DRIFT (declared mgmt IP != observed), was only tested for its ABSENCE.
    Same model, moved management IP → one IP_DRIFT row + summary count."""
    snap = {"lifecycle_risk": {"per_device": [{"host": "SW1", "model": "C9300", "mgmt_ip": "10.0.0.1"}]}}
    declared = [{"host": "SW1", "model": "C9300", "mgmt_ip": "10.0.0.2"}]
    out = ei.reconcile_external(snap, declared)
    by = {r["host"]: r for r in out["rows"]}
    assert by["SW1"]["type"] == "IP_DRIFT"
    assert "10.0.0.1" in by["SW1"]["detail"] and "10.0.0.2" in by["SW1"]["detail"]
    assert out["summary"]["IP_DRIFT"] == 1


def test_reconcile_ip_drift_compares_host_address_not_cidr():
    # NetBox stores the mgmt IP as CIDR; only the host address is compared → no spurious IP_DRIFT
    snap = {"lifecycle_risk": {"per_device": [{"host": "SW1", "model": "C9300", "mgmt_ip": "10.0.0.1"}]}}
    declared = [{"host": "SW1", "model": "C9300", "mgmt_ip": "10.0.0.1/24"}]
    assert all(r["type"] != "IP_DRIFT" for r in ei.reconcile_external(snap, declared)["rows"])
