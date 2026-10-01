"""Shared producer-backed dossier inputs for coverage disclosures across presentation exits."""
import tempfile
from pathlib import Path

from cisco_toolkit import analyze, parse


CLEAN_CONFIG = "\n".join([
    "hostname fixture", "version 17.12", "service password-encryption", "aaa new-model",
    "ntp server 192.0.2.1", "logging buffered 8192", "banner motd #Authorized users only#",
    "no ip http server", "no ip http secure-server", "ip ssh version 2", "no vstack",
])


def observed_stp_receipt(hosts):
    """A real partial seven-family receipt: one usable STP capture and one emitted Info row."""
    health = [{"switch": host, "protocol": "STP", "severity": "Info"} for host in hosts]
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "stp.txt"
        path.write_text("VLAN0010\nRoot ID Priority 32778\n", encoding="utf-8")
        commands = {host: {"show spanning-tree": str(path)} for host in hosts}
        return health, analyze.compute_protocol_assessability(hosts, {h: {} for h in hosts}, commands, health)


def coverage_dossiers(assessed, hosts=("sw0",), roles=None):
    """Unassessed case has two observed axes; assessed has six, with other collection absent."""
    roles = roles or {}
    inputs = {
        "health_scores": [{"switch": h, "score": 92 if assessed else 70,
                           "band": "Excellent" if assessed else "Good",
                           "role": roles.get(h, "access")} for h in hosts],
        "failure_impact": [{"host": h, "stranded": 4 if assessed else (220 if h == "core1" else 40),
                            "vlans_impacted": 1 if assessed else 2} for h in hosts],
        "lifecycle_risk": {"per_device": [{"host": h, "band": "Active" if assessed else "Unknown",
                                            "model": "C9300"} for h in hosts]},
    }
    if assessed:
        health, receipt = observed_stp_receipt(hosts)
        inputs.update(software_risk=analyze.compute_software_risk({h: CLEAN_CONFIG for h in hosts}),
                      security={h: parse.parse_security(CLEAN_CONFIG) for h in hosts},
                      config_hygiene={h: value for h in hosts
                                      if (value := parse.parse_config_hygiene(CLEAN_CONFIG))},
                      protocol_health=health, protocol_assessability=receipt)
    return analyze.compute_device_dossiers(**inputs)
