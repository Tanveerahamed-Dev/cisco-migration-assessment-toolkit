"""NEW-V3.23.146: golden-config drift — per-device running-config drift vs a baseline (a supplied golden
file, else the auto-derived MAJORITY baseline). Normalized substring/line matching. Pins both modes, the
structural-line exclusion, the whitespace/case tolerance, and empty/small-fleet handling."""
from cisco_toolkit.analyze import compute_golden_drift

CFG_A = "\n".join(["service password-encryption", "no ip http server", "ntp server 10.0.0.1",
                   "spanning-tree mode rapid-pvst", "hostname A",
                   "interface Gi0/1", " ip address 1.1.1.1 255.255.255.0"])
CFG_B = "\n".join(["service password-encryption", "no ip http server", "ntp server 10.0.0.1",
                   "spanning-tree mode rapid-pvst", "hostname B",
                   "interface Gi0/1", " ip address 1.1.1.2 255.255.255.0"])
# C is the OUTLIER: missing 'no ip http server' AND the spanning-tree mode
CFG_C = "\n".join(["service password-encryption", "ntp server 10.0.0.1", "hostname C",
                   "interface Gi0/1", " ip address 1.1.1.3 255.255.255.0"])


def test_majority_flags_the_outlier():
    out = compute_golden_drift({"A": CFG_A, "B": CFG_B, "C": CFG_C})
    assert out["mode"] == "majority"
    base = set(out["baseline"])
    assert {"no ip http server", "spanning-tree mode rapid-pvst",
            "service password-encryption", "ntp server 10.0.0.1"} <= base
    # structural / identity lines never enter the auto-derived baseline
    assert not any(b.startswith(("interface", "hostname", "ip address")) for b in out["baseline"])
    pdev = {d["host"]: d for d in out["per_device"]}
    assert pdev["C"]["n_missing"] == 2 and pdev["A"]["n_missing"] == 0
    assert pdev["C"]["compliance_pct"] < 100 and pdev["A"]["compliance_pct"] == 100
    assert out["summary"]["n_drifting"] == 1


def test_golden_file_mode_required_directives():
    golden = ["# org standard baseline", "service password-encryption", "no ip http server",
              "logging host 10.0.0.99", "re:^aaa new-model"]
    out = compute_golden_drift({"A": CFG_A, "C": CFG_C}, golden_lines=golden)
    assert out["mode"] == "golden-file"
    assert out["summary"]["n_baseline"] == 4                  # comment dropped, 4 required directives
    pdev = {d["host"]: d for d in out["per_device"]}
    assert "logging host 10.0.0.99" in pdev["A"]["missing"]   # nobody has a logging host
    assert any("aaa new-model" in m for m in pdev["A"]["missing"])
    assert "no ip http server" in pdev["C"]["missing"]        # C is missing it
    assert "no ip http server" not in pdev["A"]["missing"]    # A has it


def test_normalized_match_tolerates_spacing_and_case():
    cfg = "  SERVICE   Password-Encryption  \nno ip   http server"
    out = compute_golden_drift({"X": cfg}, golden_lines=["service password-encryption", "no ip http server"])
    assert out["per_device"][0]["n_missing"] == 0            # case + whitespace differences still match


def test_empty_and_small_fleet():
    assert compute_golden_drift({})["per_device"] == []
    out = compute_golden_drift({"A": CFG_A})                  # < 3 devices -> no meaningful majority baseline
    assert out["summary"]["n_baseline"] == 0 and out["per_device"][0]["compliance_pct"] == 100
