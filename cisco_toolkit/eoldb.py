"""Offline Cisco hardware End-of-Life / End-of-Support knowledge base (NEW-V3.23.117).

A small, CURATED, human-readable table mapping a device model (PID family) to its Cisco lifecycle
milestones -- end-of-sale (EoS) and last-day-of-support (LDoS) -- so per-device replacement urgency can be
assessed fully OFFLINE / air-gapped, like `portdb` / `ouidb`. Unlike those gzipped data packs this table is
kept INLINE so the dates stay reviewable and citable: each row names its Cisco EoL bulletin.

Evidence discipline: these are REFERENCE dates from Cisco bulletins (as curated for this build), NOT read from
the device. Where Cisco publishes only end-of-sale, last-day-of-support is DERIVED = EoS + 5 years (Cisco's
standard hardware support window) and tagged `conf='derived'`. ALWAYS verify the exact LDoS on Cisco's
End-of-Life portal before a procurement decision.
"""
from typing import Optional

# pat = uppercase model PREFIX; longest matching prefix wins (a specific PID beats its family).
# eos/ldos = ISO dates ('' = n/a / active). source cites the Cisco bulletin. conf: confirmed | derived | active.
_EOL = [
    # --- Catalyst (classic IOS / IOS-XE) ---
    {"pat": "WS-C4948E", "platform": "Catalyst 4948E", "eos": "2017-10-31", "ldos": "2022-10-31",
     "source": "Cisco EOL c51-738116", "conf": "derived"},
    {"pat": "WS-C4948", "platform": "Catalyst 4948", "eos": "2013-10-31", "ldos": "2018-10-31",
     "source": "Cisco EOL c51-712223", "conf": "derived"},
    {"pat": "WS-C4900M", "platform": "Catalyst 4900M", "eos": "2016-10-30", "ldos": "2021-10-31",
     "source": "Cisco EOL c51-736182", "conf": "derived"},
    {"pat": "WS-C4500X", "platform": "Catalyst 4500-X", "eos": "2020-10-30", "ldos": "2025-10-31",
     "source": "Cisco EOL c51-743098", "conf": "derived"},
    {"pat": "WS-C4500-X", "platform": "Catalyst 4500-X", "eos": "2020-10-30", "ldos": "2025-10-31",
     "source": "Cisco EOL c51-743098", "conf": "derived"},
    {"pat": "WS-C3560X", "platform": "Catalyst 3560-X", "eos": "2016-10-30", "ldos": "2021-10-31",
     "source": "Cisco EOL c51-736139", "conf": "derived"},
    {"pat": "WS-C3560-X", "platform": "Catalyst 3560-X", "eos": "2016-10-30", "ldos": "2021-10-31",
     "source": "Cisco EOL c51-736139", "conf": "derived"},
    {"pat": "WS-C3750X", "platform": "Catalyst 3750-X", "eos": "2016-10-30", "ldos": "2021-10-31",
     "source": "Cisco EOL c51-736139", "conf": "derived"},
    {"pat": "WS-C3850", "platform": "Catalyst 3850", "eos": "2021-10-30", "ldos": "2026-10-31",
     "source": "Cisco EOL (Catalyst 3850)", "conf": "derived"},
    {"pat": "WS-C3650", "platform": "Catalyst 3650", "eos": "2021-10-30", "ldos": "2026-10-31",
     "source": "Cisco EOL (Catalyst 3650)", "conf": "derived"},
    {"pat": "WS-C3560", "platform": "Catalyst 3560", "eos": "2013-10-31", "ldos": "2018-10-31",
     "source": "Cisco EOL (Catalyst 3560)", "conf": "derived"},
    {"pat": "WS-C2960X", "platform": "Catalyst 2960-X", "eos": "2025-04-30", "ldos": "2030-04-30",
     "source": "Cisco EOL (Catalyst 2960-X)", "conf": "derived"},
    {"pat": "WS-C2960", "platform": "Catalyst 2960", "eos": "2019-10-31", "ldos": "2024-10-31",
     "source": "Cisco EOL (Catalyst 2960)", "conf": "derived"},
    {"pat": "WS-C6500", "platform": "Catalyst 6500", "eos": "2017-09-30", "ldos": "2022-09-30",
     "source": "Cisco EOL (Catalyst 6500)", "conf": "derived"},
    {"pat": "C9300", "platform": "Catalyst 9300", "eos": "", "ldos": "",
     "source": "no EoL announced", "conf": "active"},
    {"pat": "C9200", "platform": "Catalyst 9200", "eos": "", "ldos": "",
     "source": "no EoL announced", "conf": "active"},
    {"pat": "C9400", "platform": "Catalyst 9400", "eos": "", "ldos": "",
     "source": "no EoL announced", "conf": "active"},
    {"pat": "C9500", "platform": "Catalyst 9500", "eos": "", "ldos": "",
     "source": "no EoL announced", "conf": "active"},
    # --- Nexus (NX-OS) ---
    {"pat": "N6K-C6001", "platform": "Nexus 6001", "eos": "2017-04-30", "ldos": "2022-04-30",
     "source": "Cisco EOL c51-737195", "conf": "derived"},
    {"pat": "N6K", "platform": "Nexus 6000", "eos": "2017-04-30", "ldos": "2022-04-30",
     "source": "Cisco EOL c51-737195", "conf": "derived"},
    {"pat": "N5K-C56", "platform": "Nexus 5600", "eos": "2021-04-30", "ldos": "2026-04-30",
     "source": "Cisco EOL (Nexus 5600)", "conf": "derived"},
    {"pat": "N5K-C55", "platform": "Nexus 5500", "eos": "2018-01-31", "ldos": "2023-01-31",
     "source": "Cisco EOL c51-740720", "conf": "derived"},
    {"pat": "N5K", "platform": "Nexus 5000", "eos": "2018-01-31", "ldos": "2023-01-31",
     "source": "Cisco EOL (Nexus 5000)", "conf": "derived"},
    {"pat": "N7K", "platform": "Nexus 7000", "eos": "2023-12-31", "ldos": "2028-12-31",
     "source": "Cisco EOL (Nexus 7000)", "conf": "derived"},
    {"pat": "N9K-C95", "platform": "Nexus 9500", "eos": "", "ldos": "",
     "source": "no EoL announced", "conf": "active"},
    {"pat": "N9K-C93", "platform": "Nexus 9300", "eos": "", "ldos": "",
     "source": "no EoL announced", "conf": "active"},
    {"pat": "N9K-C92", "platform": "Nexus 9200", "eos": "", "ldos": "",
     "source": "no EoL announced", "conf": "active"},
    {"pat": "N9K", "platform": "Nexus 9000", "eos": "", "ldos": "",
     "source": "no EoL announced", "conf": "active"},
    {"pat": "N3K", "platform": "Nexus 3000", "eos": "", "ldos": "",
     "source": "no EoL announced", "conf": "active"},
]
# longest pattern first so a specific PID beats its family prefix
_EOL_SORTED = sorted(_EOL, key=lambda r: -len(r["pat"]))


def lifecycle_for(model: str) -> Optional[dict]:
    """The curated EoL record for a device model (PID), matched by longest model-prefix, or None if the
    model is blank / unknown. Tolerant of a non-string / empty model."""
    m = str(model or "").strip().upper()
    if not m:
        return None
    for rec in _EOL_SORTED:
        if m.startswith(rec["pat"]):
            return rec
    return None
