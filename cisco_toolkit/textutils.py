"""Pure interface-name / text normalization helpers + the interface regex
constants. Leaf layer: depends only on `re`. Extracted verbatim from
COLLECT_PARSE_V3_23_0.py in PHASE 2.7 step 1 (behaviour byte-identical)."""
import re
from typing import List

IFACE_TOKEN_RE = re.compile(
    r"\b(?:Po\d+|Eth\d+/\d+(?:/\d+)?|Gi\d+/\d+(?:/\d+)?|Te\d+/\d+(?:/\d+)?|"
    r"Tw\d+/\d+(?:/\d+)?|Fo\d+/\d+(?:/\d+)?|Hu\d+/\d+(?:/\d+)?|Fa\d+/\d+(?:/\d+)?)\b",
    re.IGNORECASE)

VALID_IFACE_RE = re.compile(
    r"^(?:Po\d+|Eth\d+/\d+(?:/\d+)?|Gi\d+/\d+(?:/\d+)?|Te\d+/\d+(?:/\d+)?|"
    r"Tw\d+/\d+(?:/\d+)?|Fo\d+/\d+(?:/\d+)?|Hu\d+/\d+(?:/\d+)?|Fa\d+/\d+(?:/\d+)?|"
    r"Vlan\d+|Lo\d+|mgmt0)$",
    re.IGNORECASE)

PHYSICAL_IFACE_RE = re.compile(
    r"^(?:Po\d+|Eth\d+/\d+(?:/\d+)?|Gi\d+/\d+(?:/\d+)?|Te\d+/\d+(?:/\d+)?|"
    r"Tw\d+/\d+(?:/\d+)?|Fo\d+/\d+(?:/\d+)?|Hu\d+/\d+(?:/\d+)?|Fa\d+/\d+(?:/\d+)?)$",
    re.IGNORECASE)

_JUNK_IFACE_TOKENS  = {"port","ports","capability","status","native","vlan","name","duplex","speed","type"}
_TRUNK_STATUS_WORDS = {"trunking","trnk-bndl","notconnect","connected","disabled","suspended"}


def normalize_ifname(s: str) -> str:
    if not s: return ""
    x = s.strip()
    x = re.sub(r"^Ethernet",          "Eth", x, flags=re.IGNORECASE)
    x = re.sub(r"^FastEthernet",      "Fa",  x, flags=re.IGNORECASE)
    x = re.sub(r"^GigabitEthernet",   "Gi",  x, flags=re.IGNORECASE)
    x = re.sub(r"^TenGigabitEthernet","Te",  x, flags=re.IGNORECASE)
    x = re.sub(r"^FortyGigabitEthernet","Fo",x, flags=re.IGNORECASE)
    x = re.sub(r"^TwentyFiveGigE",    "Tw",  x, flags=re.IGNORECASE)
    x = re.sub(r"^HundredGigE",       "Hu",  x, flags=re.IGNORECASE)
    x = re.sub(r"^[Pp]ort-[Cc]hannel","Po",  x)
    return x

def is_valid_iface(name: str) -> bool:
    n = normalize_ifname((name or "").strip())
    if not n: return False
    if n.lower() in _JUNK_IFACE_TOKENS: return False
    return bool(VALID_IFACE_RE.match(n))

def normalize_status(s: str) -> str:
    if not s: return ""
    t = s.strip().lower()
    return {"up": "connected", "down": "notconnect"}.get(t, t)

def normalize_duplex(s: str) -> str:
    if not s: return ""
    t = s.strip().lower()
    return {"a-full":"Auto","a-half":"Auto","full":"Full","half":"Half","auto":"Auto"}.get(t, s.strip())

def normalize_speed(s: str) -> str:
    if not s: return ""
    t = s.strip().lower().replace("a-","auto-")
    t = re.sub(r"\([ad]\)", "", t)
    mp = {
        "auto":"Auto","auto-1000":"1000","auto-10g":"10G","auto-25g":"25G",
        "auto-40g":"40G","auto-100g":"100G","10g":"10G","25g":"25G","40g":"40G",
        "100g":"100G","1g":"1000","1000":"1000","100":"100","10":"10",
    }
    return mp.get(t, s.strip())

def normalize_mac(mac_str: str) -> str:
    if not mac_str: return ""
    mac = re.sub(r"[\s\-:.]", "", mac_str.strip().lower())
    if len(mac) != 12 or not re.match(r"^[0-9a-f]{12}$", mac): return ""
    return f"{mac[0:4]}.{mac[4:8]}.{mac[8:12]}"

def detect_link_type(transceiver_or_type: str, speed: str) -> str:
    t = (transceiver_or_type or "").lower()
    if any(k in t for k in ["sr","lr","lrm","er","zr","qsfp","sfp","xfp","cfp","glc","-sx","-lx","-lr"]):
        return "Fiber"
    if any(k in t for k in ["copper","cr","dac","twinax","base-t","rj45","-t"]):
        return "Copper"
    s = normalize_speed(speed)
    if any(x in s for x in ["10G","25G","40G","100G"]): return "Fiber"
    if s in ["1000","100","10"]: return "Copper"
    return ""

def safe_fs_name(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r'[<>:"/\\|?*]', "_", s)
    return s.rstrip(". ") or "UNKNOWN_DEVICE"

def _split_macs(s: str) -> List[str]:
    # NEW-V3.23.21 (PHASE 2.7 step 11): pure MAC-list splitter, shared by the VLAN
    # census (excel) + compute_move_groups / build_network_model (analyze).
    return [t for t in re.split(r"[,\s;]+", s or "") if t]
