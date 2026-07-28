"""Pure interface-name / text normalization helpers + the interface regex
constants. Leaf layer: depends only on `re` + `math`. Extracted verbatim from
COLLECT_PARSE_V3_23_0.py in PHASE 2.7 step 1 (behaviour byte-identical)."""
import math
import re
import sys
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

# ---- native-VLAN-1 exposure: the TWO deliberately-different measures (PR-#396 review) -------------
# One token owner for the unit nouns + basis labels every renderer interpolates (analyze punch-list,
# design_advisor decision, design_kb observable, detector_schema descriptor, archreview L2-3), so the
# self-disambiguating wording cannot fork per-site again. The two numbered-unit vocabularies must stay
# DISJOINT across bases -- guarded by
# tests/test_design_blueprint.py::test_native_vlan1_design_and_punchlist_texts_are_self_disambiguating.
NATIVE1_OPS_UNIT = "operationally-trunking port(s)"          # live-basis port unit
NATIVE1_OPS_SWITCH_UNIT = "live-trunking switch(es)"         # live-basis switch unit (NOT plain 'switch(es)')
NATIVE1_OPS_BASIS = "live trunk status"
NATIVE1_CFG_UNIT = "trunk-mode port(s)"                      # switchport-mode-basis port unit
NATIVE1_CFG_BASIS = "switchport-mode basis, administrative or negotiated"


def is_live_trunk_status(status) -> bool:
    """ONE owner for the 'is this port operationally trunking' token decision (live trunk-table
    status). 'trnk-bndl' (a port-channel trunk member) IS trunking but does NOT start with 'trunk'
    ('trnk' has no u) -- the miss behind the PR-#396-review undercount, where bundle members landed in
    the switchport-mode figure (build.py promotes them to mode Trunk) but out of the live figure."""
    s = str(status or "").strip().lower()
    return s.startswith("trunk") or s.startswith("trnk-bndl")


def is_trunk_mode(mode) -> bool:
    """ONE owner for the 'is this port trunk-mode by switchport_mode' decision. The field is
    administrative OR negotiated (parse folds the operational mode in; build promotes from the live
    trunk table) -- never pure config intent. Substring match: the engine emits 'Trunk'/'Access'/'',
    but foreign/webapp-uploaded snapshots carry values like 'dynamic trunk' / 'trunk (802.1q)', and
    design_advisor + archreview L2-3 must count them identically (PR-#396 review: the two hand-rolled
    predicates diverged substring-vs-exact)."""
    return "trunk" in str(mode or "").lower()


# ---- BPDU-Guard token decision (cross-module SSOT audit 2026-07-28) -------------------------------
# The PRODUCER's vocabulary for `stp_bpduguard` is exactly {"Enable", "Disable", ""}: parse.py's
# parse_run_config_interfaces writes "Enable"/"Disable", build.py promotes a global
# `spanning-tree portfast bpduguard default` to "Enable", and "" means the run-config channel never
# landed for that port -- NOT ASSESSED, never "off".
# Both consumers hand-rolled their own token set and NEITHER matched it, in opposite directions:
# archreview L2-2 asked `v not in ("no","disabled","off","false","-","--")`, and "disable" is not in
# that set, so an explicitly DISABLED edge port counted as GUARDED (6 such ports on the [HISTORY-REDACTED] fleet);
# design_advisor asked `v in ("enable","enabled","true","on")` and counted the same ports UNGUARDED.
# Same field, same snapshot, opposite verdicts -- and archreview's direction was the false-health one.
# Same class as is_trunk_mode above (PR-#396). Three-state on purpose so no caller can collapse "no
# evidence" into "off" (Law 3): True = protected, False = protection off, None = not assessable.
_BPDUGUARD_ON = {"enable", "enabled", "true", "on", "yes", "1"}
_BPDUGUARD_OFF = {"disable", "disabled", "false", "off", "no", "0", "-", "--", "none"}


def bpduguard_state(value):
    """ONE owner for the 'is BPDU Guard on for this port' token decision.

    Returns ``True`` (protected), ``False`` (explicitly not protected) or ``None`` (no evidence --
    the field was never populated, or carries a token that proves neither state). A caller counting
    "protected" must test ``is True``; a caller counting an OBSERVED gap must test ``is False``;
    ``None`` belongs in a not-assessed bucket, never in either verdict."""
    s = str(value if value is not None else "").strip().lower()
    if not s:
        return None                                     # never collected -> not assessed, never "off"
    if s in _BPDUGUARD_OFF or s.startswith("no ") or "disable" in s:
        return False
    if s in _BPDUGUARD_ON or "enable" in s:
        return True
    return None                                         # an unknown token proves neither state

# Characters that abort XML serialization (python-docx / openpyxl both serialize to XML): the C0 control chars
# XML 1.0 forbids -- 0x00-0x08, 0x0B-0x0C, 0x0E-0x1F (tab 0x09 / newline 0x0A / CR 0x0D stay legal) -- plus the
# U+FFFE / U+FFFF noncharacters and the lone surrogates U+D800-U+DFFF. Device-derived free-text (a CDP/LLDP
# neighbour name, an interface description, a banner) is collected with errors='ignore', which passes valid-UTF-8
# control bytes through, so a single one of these still aborts the ENTIRE .docx / .xlsx at save -- with a
# ValueError "All strings must be XML compatible" (noncharacter) or a UnicodeEncodeError (lone surrogate).
_XML_ILLEGAL_RE = re.compile(
    "[\x00-\x08\x0b\x0c\x0e-\x1f" + chr(0xD800) + "-" + chr(0xDFFF) + chr(0xFFFE) + chr(0xFFFF) + "]")

# The largest magnitude openpyxl can hand to the XLSX writer: it converts every numeric cell through a
# C double, so an int beyond this raises OverflowError at wb.save() (see xml_safe).
_FLOAT_MAX = sys.float_info.max


def is_finite_num(v) -> bool:
    """True for a number that float arithmetic and cell rendering can both survive.

    THE predicate to filter a device-derived numeric leaf on -- and specifically the correct
    replacement for the `isinstance(v, (int, float)) and math.isfinite(v)` idiom, which is itself
    unsafe: `json.loads` accepts an integer literal of unbounded precision, and
    ``math.isfinite(10**400)`` raises ``OverflowError: int too large to convert to float`` BEFORE it
    can return False. So the guard written to reject the JSON `Infinity` crashed on the JSON huge int
    -- the same class it was added to close, one input away.

    The int bound is therefore tested by INTEGER comparison against the float64 max, never by
    converting. ``bool`` is excluded: it is an int subclass, and a True/False where a count belongs is
    not an observed number (callers that legitimately count bools test them explicitly).

    Companion to :func:`_as_num`, which COERCES; this one FILTERS, for the sites that must keep the
    value's original type (a mean over scores, a set of renderable cells)."""
    if isinstance(v, bool):
        return False
    if isinstance(v, int):
        return -_FLOAT_MAX <= v <= _FLOAT_MAX
    return isinstance(v, float) and math.isfinite(v)


def xml_safe(value):
    """Strip the characters that make XML serialization raise, so one bad byte in device-derived text cannot abort
    an entire .docx / .xlsx deliverable. Scalars (int / float / None / bool) pass through unchanged -- openpyxl and
    python-docx render them natively (callers stringify the rest when they must). A CONTAINER (dict / list / tuple /
    set) is the exception: it can only reach here if a compute placed one in a directly-rendered cell, where openpyxl
    would raise ValueError -- which excel._run_phase catches PER SHEET, silently dropping every row after it (a
    coverage-honesty false all-clear). Disclose it as a typed placeholder instead of passing it through to crash.
    Canonical, shared by the excel + docx generators (excel._xls_sanitize delegates here).

    NUMERIC out-of-domain values are the second exception, and they are the JSON-snapshot twin of the
    container case (crash-safety fuzz, 2026-07-28). `json.loads` accepts the bare `Infinity` / `-Infinity`
    / `NaN` tokens and integer literals of unbounded precision, so an untrusted snapshot -- a `--no-collect`
    re-analysis file, a webapp upload, a foreign-tool export -- puts either straight into a rendered cell:

      * an int outside the float64 range (e.g. ``10**400``) raises ``OverflowError: int too large to
        convert to float`` inside ``wb.save()``, i.e. AFTER every sheet is built, aborting the ONE
        deliverable produced unconditionally (there is no ``--no-excel``);
      * ``inf`` / ``-inf`` / ``nan`` are WORSE than a crash: openpyxl saves them without complaint and
        Excel reads the cell back as EMPTY. The number silently disappears from the delivered workbook
        with no disclosure -- 'not observed' masquerading as 'nothing to report', the exact false-health
        class the coverage-honesty doctrine forbids.

    Both degrade to the same typed placeholder the container case uses, so the value is VISIBLY
    unrenderable rather than absent. ``bool`` is checked before ``int`` (it is a subclass) and every
    in-range int/float still passes through byte-identically, so well-formed output is unchanged."""
    if isinstance(value, str):
        return _XML_ILLEGAL_RE.sub("", value)
    if isinstance(value, (dict, list, tuple, set)):
        return "[unrenderable %s]" % type(value).__name__
    if isinstance(value, bool):                       # bool is an int subclass -- renders natively
        return value
    if isinstance(value, float) and not math.isfinite(value):
        return "[unrenderable %s]" % value            # -> '[unrenderable inf]' / '[unrenderable nan]'
    if isinstance(value, int) and not -_FLOAT_MAX <= value <= _FLOAT_MAX:
        return "[unrenderable number: %d digits]" % len(str(abs(value)))
    return value


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


def _as_num(x, default=0):
    """Fail-soft numeric coercion of a device-derived leaf value, returning a finite number (an int when
    integer-valued, else a float) or `default` when `x` cannot be coerced. This is the shared guard for the
    engine's #1 doctrine (fail-soft): an externally-supplied snapshot -- a webapp upload, a `--compare` /
    `--trend` file -- can carry a malformed leaf into an `int()` / `round()` / arithmetic coercion of a
    device-derived count, and a single bad field must degrade THAT field (to `default`), never crash the whole
    deliverable or endpoint. The three trap inputs it neutralizes:
      * a non-numeric string / dict / list  -> `float()` raises ValueError / TypeError;
      * the bare JSON `Infinity` / `-Infinity`  -> `json.loads` accepts it as `float('inf')`, which then raises
        OverflowError on `int()` (the usual `except (TypeError, ValueError)` guards MISS this) -> rejected here;
      * the bare JSON `NaN`  -> accepted as `float('nan')` -> rejected here (isnan).
    Route every raw leaf count coercion through this so no single field can 500 an endpoint or abort a workbook."""
    try:
        f = float(x)
    except (TypeError, ValueError, OverflowError):
        return default
    if math.isnan(f) or math.isinf(f):
        return default
    return int(f) if f.is_integer() else f


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
    x = re.sub(r"^Vl(\d+)\b",         r"Vlan\1", x, flags=re.IGNORECASE)   # abbreviated SVI 'Vl10' -> canonical 'Vlan10'
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
