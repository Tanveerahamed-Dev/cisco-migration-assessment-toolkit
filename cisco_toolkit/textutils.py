"""Pure interface-name / text normalization helpers + the interface regex
constants. Leaf layer: depends only on `re`. Extracted verbatim from
COLLECT_PARSE_V3_23_0.py in PHASE 2.7 step 1 (behaviour byte-identical)."""
import re
from typing import List

IFACE_TOKEN_RE = re.compile(
    r"\b(?:Po\d+|Eth\d+/\d+(?:/\d+)?|Gi\d+/\d+(?:/\d+)?|Te\d+/\d+(?:/\d+)?|"
    r"Tw\d+/\d+(?:/\d+)?|Twe\d+/\d+(?:/\d+)?|Fif\d+/\d+(?:/\d+)?|Fi\d+/\d+(?:/\d+)?|App?\d+/\d+(?:/\d+)?|Fo\d+/\d+(?:/\d+)?|Hu\d+/\d+(?:/\d+)?|Fa\d+/\d+(?:/\d+)?)\b",
    re.IGNORECASE)

VALID_IFACE_RE = re.compile(
    r"^(?:Po\d+|Eth\d+/\d+(?:/\d+)?|Gi\d+/\d+(?:/\d+)?|Te\d+/\d+(?:/\d+)?|"
    r"Tw\d+/\d+(?:/\d+)?|Twe\d+/\d+(?:/\d+)?|Fif\d+/\d+(?:/\d+)?|Fi\d+/\d+(?:/\d+)?|App?\d+/\d+(?:/\d+)?|Fo\d+/\d+(?:/\d+)?|Hu\d+/\d+(?:/\d+)?|Fa\d+/\d+(?:/\d+)?|"
    r"Vlan\d+|Lo\d+|Tu\d+|mgmt0)$",
    re.IGNORECASE)

PHYSICAL_IFACE_RE = re.compile(
    r"^(?:Po\d+|Eth\d+/\d+(?:/\d+)?|Gi\d+/\d+(?:/\d+)?|Te\d+/\d+(?:/\d+)?|"
    r"Tw\d+/\d+(?:/\d+)?|Twe\d+/\d+(?:/\d+)?|Fif\d+/\d+(?:/\d+)?|Fi\d+/\d+(?:/\d+)?|App?\d+/\d+(?:/\d+)?|Fo\d+/\d+(?:/\d+)?|Hu\d+/\d+(?:/\d+)?|Fa\d+/\d+(?:/\d+)?)$",
    re.IGNORECASE)

_JUNK_IFACE_TOKENS  = {"port","ports","capability","status","native","vlan","name","duplex","speed","type"}
_TRUNK_STATUS_WORDS = {"trunking","trnk-bndl","notconnect","connected","disabled","suspended"}

# Characters that abort XML serialization (python-docx / openpyxl both serialize to XML): the C0 control chars
# XML 1.0 forbids -- 0x00-0x08, 0x0B-0x0C, 0x0E-0x1F (tab 0x09 / newline 0x0A / CR 0x0D stay legal) -- plus the
# U+FFFE / U+FFFF noncharacters and the lone surrogates U+D800-U+DFFF. Device-derived free-text (a CDP/LLDP
# neighbour name, an interface description, a banner) is collected with errors='ignore', which passes valid-UTF-8
# control bytes through, so a single one of these still aborts the ENTIRE .docx / .xlsx at save -- with a
# ValueError "All strings must be XML compatible" (noncharacter) or a UnicodeEncodeError (lone surrogate).
_XML_ILLEGAL_RE = re.compile(
    "[\x00-\x08\x0b\x0c\x0e-\x1f" + chr(0xD800) + "-" + chr(0xDFFF) + chr(0xFFFE) + chr(0xFFFF) + "]")


def xml_safe(value):
    """Strip the characters that make XML serialization raise, so one bad byte in device-derived text cannot abort
    an entire .docx / .xlsx deliverable. Non-strings pass through unchanged (callers stringify when they must).
    Canonical, shared by the excel + docx generators (excel._xls_sanitize delegates here)."""
    if not isinstance(value, str):
        return value
    return _XML_ILLEGAL_RE.sub("", value)


def xml_safe_deep(obj):
    """Recursively xml_safe() every string in a JSON-like structure (dict keys + values, list items, scalars).
    A docx/xlsx generator can sanitize the WHOLE snapshot once at entry with this, so no device-derived string --
    a CDP name nested in interfaces, a hostname used as a dict key, a failure-impact host -- can carry an
    XML-illegal char into serialization regardless of which field it lands in."""
    if isinstance(obj, dict):
        return {xml_safe(k): xml_safe_deep(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [xml_safe_deep(v) for v in obj]
    return xml_safe(obj)


def normalize_ifname(s: str) -> str:
    if not s: return ""
    x = s.strip()
    x = re.sub(r"^Ethernet",          "Eth", x, flags=re.IGNORECASE)
    x = re.sub(r"^FastEthernet",      "Fa",  x, flags=re.IGNORECASE)
    x = re.sub(r"^GigabitEthernet",   "Gi",  x, flags=re.IGNORECASE)
    x = re.sub(r"^TenGigabitEthernet","Te",  x, flags=re.IGNORECASE)
    x = re.sub(r"^FortyGigabitEthernet","Fo",x, flags=re.IGNORECASE)
    # Multi-gig long forms must converge on the SAME canonical short token the rest of the codebase + the
    # device's own `show interfaces status` use (verified vs Cisco IOS-XE Catalyst 9300/9400/9600 docs):
    # 25G=Twe (NOT Tw -- Tw is 2.5G TwoGigabitEthernet), 5G=Fi, 50G=Fif, 2.5G=Tw, AppGig=Ap. The old
    # TwentyFiveGigE->Tw folded 25G onto the 2.5G token, so the long and short paths disagreed.
    x = re.sub(r"^TwentyFiveGig(?:abitEthernet|E)?", "Twe", x, flags=re.IGNORECASE)
    x = re.sub(r"^TwoGigabitEthernet",               "Tw",  x, flags=re.IGNORECASE)
    x = re.sub(r"^FiftyGig(?:abitEthernet|E)?",      "Fif", x, flags=re.IGNORECASE)
    x = re.sub(r"^FiveGigabitEthernet",              "Fi",  x, flags=re.IGNORECASE)
    x = re.sub(r"^AppGigabitEthernet",               "Ap",  x, flags=re.IGNORECASE)
    x = re.sub(r"^HundredGigE",       "Hu",  x, flags=re.IGNORECASE)
    x = re.sub(r"^[Pp]ort-[Cc]hannel","Po",  x)
    x = re.sub(r"^Tunnel",            "Tu",  x, flags=re.IGNORECASE)
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
    # An absent/empty bay is not a medium: 'No Transceiver' contains the fiber 'er' token (transceiv-ER) and
    # would mis-read as Fiber. Blank it so classification falls through to the speed heuristic instead.
    if t.strip() in ("no transceiver", "not present", "unknown", "none", "n/a", "--", ""):
        t = ""
    # Copper twisted-pair / RJ45 SFPs (GLC-T, SFP-GE-T, 1000BASE-T, 10GBASE-T) carry an SFP/GLC fiber-family
    # substring yet are electrically COPPER -- the unambiguous copper markers must win over the generic fiber
    # list below (else 'glc-t' hits the 'glc' fiber token and is mislabeled Fiber). base-?tx? = BaseT/Base-T/
    # BaseTX forms; the -t suffix covers GLC-T / SFP-GE-T / SFP-1G-T copper SKUs. (DAC/-CR twinax left to the
    # form-factor list below, unchanged.)
    if t and (re.search(r"base-?tx?|rj-?45|10gbase-t|sfp-(?:ge|1g)-t", t)
              or t.endswith("-t") or "glc-t" in t
              or any(k in t for k in ("copper", "twinax", "dac"))):
        return "Copper"
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
