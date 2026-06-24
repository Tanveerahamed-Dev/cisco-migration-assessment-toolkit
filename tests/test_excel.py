"""Workbook (excel.py) robustness — control-character sanitization at the cell-write chokepoint.

The workbook is the ONE deliverable produced unconditionally (there is no --no-excel). openpyxl raises
IllegalCharacterError on a control char (0x00-0x08, 0x0B-0x0C, 0x0E-0x1F), and device-derived free-text
(a CDP/LLDP neighbour name, an interface description, a banner) is read with errors='ignore', which passes
valid-UTF-8 control bytes through. A single one used to abort the entire workbook. harden_workbook() sanitizes
at the cell-write chokepoint so no device-text field can crash it -- one guard over all ~329 write sites.
"""
import io

import pytest

openpyxl = pytest.importorskip("openpyxl")
from openpyxl import Workbook, load_workbook  # noqa: E402

from cisco_toolkit.excel import _xls_sanitize, harden_workbook, write_endpoint_census_sheet  # noqa: E402
from cisco_toolkit.model import InterfaceData  # noqa: E402

_DIRTY = "EDGE-SW1\x07\x1b[31m desc\x0b end\x00"   # BEL + ESC-seq + VT + NUL embedded in a device string


def test_xls_sanitize_strips_control_chars_keeps_text():
    clean = _xls_sanitize(_DIRTY)
    assert "EDGE-SW1" in clean and "desc" in clean and "end" in clean   # real text preserved
    assert not any(ord(ch) < 0x20 and ch not in "\t\n\r" for ch in clean)  # no illegal control chars left
    assert _xls_sanitize(42) == 42 and _xls_sanitize(None) is None         # non-strings pass through


def test_harden_workbook_sanitizes_cell_and_append_no_raise():
    wb = harden_workbook(Workbook())
    ws = wb.create_sheet("t")          # created AFTER harden -> still wrapped via create_sheet
    ws.cell(row=1, column=1, value=_DIRTY)         # kwargs form
    ws.cell(2, 1, _DIRTY)                           # positional form
    ws.append([_DIRTY, "ok", 7])                    # append form
    buf = io.BytesIO()
    wb.save(buf)                                    # must NOT raise IllegalCharacterError
    assert buf.tell() > 0
    for addr in ("A1", "A2", "A3"):
        assert "\x07" not in ws[addr].value and "\x1b" not in ws[addr].value


def test_endpoint_census_sheet_survives_control_char_in_device_text(tmp_path):
    """End-to-end on a real sheet writer: a control char in a device field (CDP neighbour, location) must not
    abort the workbook; it saves and the dirty text is sanitized in the written cell."""
    wb = harden_workbook(Workbook())
    d = InterfaceData(port="Gi1/0/1", vlan="10", vlan_name="DATA", end_host_mac="00:11:22:33:44:55",
                      end_host_ip="10.0.10.5", cdp_neighbor=_DIRTY, endpoint_location="rack\x0b3")
    write_endpoint_census_sheet(wb, {"SW1": {"Gi1/0/1": d}})   # must not raise
    out = tmp_path / "wb.xlsx"
    wb.save(str(out))
    assert out.exists() and out.stat().st_size > 0
    wb2 = load_workbook(str(out))
    vals = [c.value for row in wb2[wb2.sheetnames[-1]].iter_rows()
            for c in row if isinstance(c.value, str)]
    assert any("EDGE-SW1" in v for v in vals)                       # neighbour text survived
    assert not any("\x07" in v or "\x1b" in v or "\x0b" in v for v in vals)   # control chars gone


def test_append_interface_rows_survives_control_char_no_silent_port_drop(tmp_path):
    """EXCEL-01 (silent data loss): append_interface_rows writes device text via DIRECT `cell.value = val`
    (not ws.cell(value=...)), so a control char in ONE port's description raised IllegalCharacterError mid-loop;
    _run_phase (per host) swallowed it, and every port written AFTER the offending one was silently dropped from
    the customer-facing interface census. The Cell.value-setter guard installed by harden_workbook must keep ALL
    four ports (the bug landed only 2)."""
    from openpyxl import Workbook
    from cisco_toolkit.excel import append_interface_rows
    from cisco_toolkit.model import InterfaceData

    def mk(p, desc):
        d = InterfaceData(); d.port = p; d.status = "connected"; d.description = desc; return d
    ifaces = {"Gi1/0/1": mk("Gi1/0/1", "one"),
              "Gi1/0/2": mk("Gi1/0/2", "uplink \x1b[0m core"),   # control char mid-loop
              "Gi1/0/3": mk("Gi1/0/3", "three"),
              "Gi1/0/4": mk("Gi1/0/4", "four")}
    wb = harden_workbook(Workbook())
    ws = wb.active
    col_map = {"hostname": 1, "port": 2, "status": 3, "description": 4}
    for h, c in col_map.items():
        ws.cell(row=1, column=c, value=h)
    append_interface_rows(ws, 1, col_map, "SW1", ifaces)          # must NOT raise nor drop the tail
    ports = [ws.cell(r, 2).value for r in range(2, ws.max_row + 1) if ws.cell(r, 2).value]
    assert set(ports) == {"Gi1/0/1", "Gi1/0/2", "Gi1/0/3", "Gi1/0/4"}, ports
    wb.save(str(tmp_path / "if.xlsx"))
