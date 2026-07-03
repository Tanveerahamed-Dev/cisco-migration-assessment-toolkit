"""Explorer MODES registry conformance (Plan A / Tier-2 #9).

The drift class: adding an explorer mode used to mean SEVEN hand-parallel sites
(HASH_MODES, toolbar button, srAnnounce label, setHint, setModeTag, setLegend,
keyboard) — and the keyboard site proved it: five of thirteen modes (xlayer /
waves / apps / review / design) simply never got shortcuts, and the help overlay
still said "1 … 7".

Now ONE `MODES` table drives them: HASH_MODES and MODE_BY_KEY are DERIVED, the
announce/hint/tag/legend sites read the registry, the keyboard handler walks it
(digit bindings 1–8 preserved verbatim for muscle memory; the five missing modes
got collision-free mnemonic letters), and the help chips are generated from it.
The static toolbar buttons remain hand-written HTML (boot-order safety) but are
PINNED here — a registry mode without a matching button fails the suite.
repaint/renderDrawer keep their per-mode branches: that is mode BEHAVIOR,
deliberately colocated, not wiring."""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
EXPL = (ROOT / "cisco_toolkit" / "blast_radius_explorer.html").read_text(encoding="utf-8")

# keys already claimed by non-mode shortcuts in the global keydown handler
RESERVED_KEYS = {"f", "t", "g", "m", "a", "r", "/", "escape"}
# the historic digit bindings — preserved verbatim so muscle memory survives
LEGACY_KBD = {"1": "blast", "2": "trace", "3": "compare", "4": "flow",
              "5": "health", "6": "protocols", "7": "causality", "8": "cablemap"}


def _registry_block():
    m = re.search(r"MODES-REGISTRY START.*?const MODES\s*=\s*\[(.*?)\n\];", EXPL, re.S)
    assert m, "explorer is missing the MODES registry block"
    return m.group(1)


def _entries():
    block = _registry_block()
    keys = re.findall(r'\bkey:"([a-z0-9_]+)"', block)
    segs = re.split(r'\bkey:"[a-z0-9_]+"', block)[1:]
    return dict(zip(keys, segs))


def test_registry_is_complete_and_unique():
    entries = _entries()
    assert len(entries) >= 14, f"expected all 14 modes, found {sorted(entries)}"
    for key, seg in entries.items():
        for field in ("kbd:", "gl:", "btn:", "label:", "tag:", "hint:", "legend:"):
            assert field in seg, f"mode {key!r} lost its {field.rstrip(':')} field"


def test_hash_modes_and_lookup_are_derived_not_hand_listed():
    assert re.search(r"const HASH_MODES\s*=\s*MODES\.map\(", EXPL), \
        "HASH_MODES must derive from the registry"
    assert not re.search(r'const HASH_MODES\s*=\s*\["blast"', EXPL), \
        "the old hand-maintained HASH_MODES literal must not return"
    assert "MODE_BY_KEY" in EXPL


def test_keyboard_shortcuts_cover_every_mode_without_collisions():
    entries = _entries()
    kbd = {}
    for key, seg in entries.items():
        m = re.search(r'kbd:"([^"]+)"', seg)
        assert m, f"mode {key!r} has no keyboard shortcut — the 5-missing-shortcuts class"
        kbd[key] = m.group(1).lower()
    assert len(set(kbd.values())) == len(kbd), f"duplicate shortcuts: {sorted(kbd.values())}"
    clash = {k: v for k, v in kbd.items() if v in RESERVED_KEYS}
    assert not clash, f"mode shortcut collides with a reserved action key: {clash}"
    for digit, mode in LEGACY_KBD.items():
        assert kbd.get(mode) == digit, \
            f"legacy binding broken: {digit!r} must stay {mode!r} (got {kbd.get(mode)!r})"
    # the handler itself must WALK the registry, not re-list modes by hand
    assert re.search(r"MODES\.find\(\s*\w+\s*=>\s*\w+\.kbd===k\s*\)", EXPL), \
        "keyboard handler is not registry-driven"
    assert 'if(k==="1")setMode("blast")' not in EXPL, "the hand-chained shortcut ladder returned"


def test_announce_hint_tag_legend_read_the_registry():
    for probe, site in (("MODE_BY_KEY[m]", "setMode announce"),
                        ("MODE_BY_KEY[MODE].hint()", "setHint"),
                        ("MODE_BY_KEY[MODE].tag", "setModeTag"),
                        ("MODE_BY_KEY[MODE].legend()", "setLegend")):
        assert probe in EXPL, f"{site} no longer reads the registry ({probe} missing)"
    # the old inline per-mode maps must be gone from those sites
    assert 'blast:"Blast radius"' not in EXPL, "setMode's inline label map returned"
    assert 'blast:"Pull a switch from the fabric' not in EXPL, "setModeTag's inline map returned"


def test_every_registry_mode_has_its_toolbar_button():
    """The toolbar strip stays static HTML (boot-order safety) — this pin makes a
    missing/renamed button a suite failure instead of a silent dead mode."""
    entries = _entries()
    for key, seg in entries.items():
        m = re.search(r'gl:"([^"]+)"', seg)
        btn = re.search(rf'<button data-mode="{key}"[^>]*>.*?</button>', EXPL)
        assert btn, f"mode {key!r} has no toolbar button"
        assert m.group(1) in btn.group(0), \
            f"mode {key!r}: button glyph diverged from the registry glyph {m.group(1)!r}"


def test_help_overlay_chips_are_generated_from_the_registry():
    assert 'id="kbdModes"' in EXPL, "help overlay lost its generated shortcut chips"
    assert "1</span> … <span" not in EXPL.replace("\n", ""), \
        "the stale hand-written '1 … 7' help row must not return"
