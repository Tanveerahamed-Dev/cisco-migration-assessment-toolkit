"""`.design-sync/` is the ONE directory in this repo whose contents are uploaded off-host.

The design-sync converter reads the durable set (`config.json`, `NOTES.md`, `conventions.md`,
`previews/`, `docs/`, `providers/`, `overrides/`) and ships it to claude.ai/design. Everything else
here is air-gapped by doctrine, so this is the only place where "is this fictional?" is a question
with consequences.

`.design-sync/NOTES.md` states the rule in prose:

    **Sample data is 100% fictional** (Meridian fleet, TEST-NET IPs). Never regenerate it from real
    <client> snapshots — client-confidential data must not be uploaded to claude.ai (no-egress
    doctrine).

Prose does not survive a hurried `npm run resync`. These tests make the rule mechanical, in the same
spirit as tests/test_readme_field.py (ratchets README-FIELD.txt) and tests/test_ssot_registry.py
(stops the SSOT pointers rotting).

Scope note: this walks the FILESYSTEM, not `git ls-files`. The converter reads what is on disk, so an
uncommitted regeneration is exactly the case that matters — a tracked-only check would be blind to
it. The three gitignored working dirs are skipped: `.cache/` legitimately records local absolute
paths (the run log), and `node_modules/` + `learnings/` are machine state. None are uploaded.
"""

from __future__ import annotations

import ipaddress
import json
import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_DS = _REPO / ".design-sync"
_FRONTEND = _REPO / "webapp" / "frontend"
_BARREL = _FRONTEND / "ds.entry.ts"
_SAMPLE = _DS / "providers" / "sample-data.ts"

# These are intentionally public from ds.entry.ts, but they are helpers rather than Design cards.
# Keeping the list explicit makes a new barrel export fail closed until it is classified. The
# provider is deliberately NOT here: DemoDataProvider is one of the 21 public component contracts.
_BARREL_HELPER_EXPORTS = frozenset(
    {
        "VERIFICATION_CONTRACT_VERSION",
        "bandColor",
        "gateColor",
        "normalizedVerification",
        "readyColor",
        "sevColor",
        "sevSoft",
        "useAsync",
        "usePositionTween",
        "useReducedMotion",
        "useToast",
        "useViewTransition",
    }
)

# Topology3D is an internal, lazy-loaded implementation detail of TopologyGraph. It takes internal
# graph state rather than a public snapId contract and cannot produce a useful static Design card.
# ComparisonDecision is likewise a workflow-internal renderer: it requires a complete source-bound
# comparison receipt, preserves uncapped custody fields, and exports that receipt. Turning it into a
# static design-sync card would require maintaining a second fictional semantic receipt outside the
# server-owned contract, so Campaign and Execution reuse it directly without publishing it as a
# standalone design-system component.
_DELIBERATE_SOURCE_ONLY_COMPONENTS = frozenset({
    "ComparisonDecision",
    "ObservedL2TrialInput",
    "Topology3D",
})

_BARREL_EXPORT_BLOCK = re.compile(
    r"^\s*export\s*{(?P<body>.*?)}\s*from\s*[\"'][^\"']+[\"']\s*;?",
    re.MULTILINE | re.DOTALL,
)
_BARREL_EXPORT_ITEM = re.compile(
    r"(?P<local>default|[A-Za-z_$][A-Za-z0-9_$]*)"
    r"(?:\s+as\s+(?P<public>[A-Za-z_$][A-Za-z0-9_$]*))?"
)
_DTS_PLACEHOLDER = re.compile(
    r"\s*(?:{\s*)?\[\s*key\s*:\s*string\s*\]\s*:\s*unknown\s*;?\s*(?:}\s*)?"
)

# gitignored (.gitignore:64-66) — local machine state, not part of what the converter uploads
_SKIP_DIRS = {".cache", "node_modules", "learnings"}

_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")

# RFC 5737 TEST-NET-1/2/3 and RFC 2544 benchmarking — the ranges NOTES.md says the fixtures use.
# ipaddress marks TEST-NET as neither private nor global, so name them explicitly.
_DOC_NETS = tuple(
    ipaddress.ip_network(c)
    for c in ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24", "198.18.0.0/15")
)


def _uploaded_files() -> list[Path]:
    out: list[Path] = []
    for p in _DS.rglob("*"):
        if not p.is_file():
            continue
        if _SKIP_DIRS & set(p.relative_to(_DS).parts):
            continue
        out.append(p)
    return out


def _config() -> dict:
    return json.loads((_DS / "config.json").read_text(encoding="utf-8"))


def _barrel_exports() -> set[str]:
    """Return the public names from the committed named-export barrel."""
    text = _BARREL.read_text(encoding="utf-8")
    exports: set[str] = set()
    blocks = list(_BARREL_EXPORT_BLOCK.finditer(text))
    assert blocks, f"no named re-export blocks found in {_BARREL}"
    for block in blocks:
        for raw_item in block.group("body").split(","):
            item = raw_item.strip()
            if not item:
                continue
            match = _BARREL_EXPORT_ITEM.fullmatch(item)
            assert match, f"unrecognised named export {item!r} in {_BARREL}"
            exports.add(match.group("public") or match.group("local"))
    return exports


def _source_component_exports() -> dict[str, set[str]]:
    """Discover PascalCase component declarations in the app's component modules.

    This is the committed form of NOTES.md's manual-barrel probe. Unlike that illustrative probe,
    it uses a named default function/class when one exists, so CausalFlowPanel is not mistaken for
    the source filename CausalFlow.
    """
    found: dict[str, set[str]] = {}

    def record(name: str, path: Path) -> None:
        found.setdefault(name, set()).add(str(path.relative_to(_FRONTEND)))

    declaration = re.compile(
        r"^\s*export\s+(?P<default>default\s+)?(?:async\s+)?"
        r"(?:function|class)\s+(?P<name>[A-Z][A-Za-z0-9]*)\b",
        re.MULTILINE,
    )
    named_const = re.compile(
        r"^\s*export\s+const\s+(?P<name>[A-Z][A-Za-z0-9]*)\s*(?::|=)",
        re.MULTILINE,
    )
    default_reference = re.compile(
        r"^\s*export\s+default\s+(?P<name>[A-Z][A-Za-z0-9]*)\s*;",
        re.MULTILINE,
    )

    for path in sorted((_FRONTEND / "src" / "components").rglob("*.tsx")):
        if path.name.endswith(".test.tsx"):
            continue
        text = path.read_text(encoding="utf-8")
        named_default = False
        for match in declaration.finditer(text):
            record(match.group("name"), path)
            named_default = named_default or bool(match.group("default"))
        for match in named_const.finditer(text):
            record(match.group("name"), path)
        default_refs = list(default_reference.finditer(text))
        for match in default_refs:
            record(match.group("name"), path)
        if re.search(r"^\s*export\s+default\b", text, re.MULTILINE):
            if not named_default and not default_refs:
                record(path.stem, path)
    return found


def _is_empty_or_placeholder_dts(body: object) -> bool:
    if not isinstance(body, str) or not body.strip():
        return True
    return bool(_DTS_PLACEHOLDER.fullmatch(body) or re.fullmatch(r"\s*{\s*}\s*", body))


def _is_non_identifying(token: str, is_cidr_base: bool) -> bool:
    """True when the literal cannot identify real client infrastructure.

    NON-VACUITY (mutation-proved, 2026-07-28). This used to return True for `ip.is_private`,
    which made the check below — the one its own docstring calls "what actually distinguishes
    'regenerated from a real fleet' from 'synthetic'" — blind to the ONLY address family a real
    fleet is ever numbered from. Planting four real-shaped client management addresses
    (10.200.200.1, 10.14.7.22, 172.16.4.9, 192.168.10.254) in providers/sample-data.ts left the
    whole file GREEN. A switch inventory carries RFC 1918 hosts, essentially never public ones,
    so the pre-fix rule caught the one case that does not happen and passed the one that does.

    RFC 1918 is therefore an OFFENDER now, with one carve-out: an address written as the base of
    a CIDR (`10.0.0.0/16`) names an address SPACE, not a device — sample-data.ts legitimately uses
    it as the target-address-space example. That carve-out is keyed on the trailing '/', so a bare
    `10.0.0.1` host literal can never claim it.
    """
    try:
        ip = ipaddress.ip_address(token)
    except ValueError:
        return True  # e.g. a version string like 1.2.3.4.5 -> not an address at all
    if any(ip in net for net in _DOC_NETS):
        return True  # the documented fictional ranges NOTES.md says the fixtures use
    if ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified or ip.is_reserved:
        return True  # identifies no host anywhere
    if ip.is_private:
        return is_cidr_base  # a /nn base is an address space; a bare host literal is client data
    return False             # anything else is a routable, real-world address


def test_design_sync_dir_is_present_and_populated():
    """Guard the guard: the three tests below assert over a file list, and an empty list passes
    every one of them. If the directory is renamed or emptied, fail here rather than go quietly
    inert."""
    assert _DS.is_dir(), f"{_DS} is missing — the tests below would pass vacuously"
    files = _uploaded_files()
    assert len(files) >= 20, f"only {len(files)} uploadable files found; expected the durable set"
    sample = _DS / "providers" / "sample-data.ts"
    assert sample.is_file(), "providers/sample-data.ts missing — NOTES.md names it as the fixture"
    assert len(sample.read_text(encoding="utf-8", errors="ignore")) > 500, \
        "sample-data.ts is a stub; the fictional-fleet assertion would be meaningless"


def test_no_client_identifying_ip_literals_are_uploaded():
    """A real snapshot carries real management addresses; the Meridian fixture must not.

    This is the load-bearing check: it is what actually distinguishes 'regenerated from a real
    fleet' from 'synthetic'. See _is_non_identifying for why "routable" was the wrong bar."""
    offenders: list[str] = []
    for path in _uploaded_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        for m in _IPV4.finditer(text):
            token, is_cidr_base = m.group(0), text[m.end():m.end() + 1] == "/"
            if not _is_non_identifying(token, is_cidr_base):
                offenders.append(f"{path.relative_to(_DS)}: {token}")
    assert not offenders, (
        "client-identifying IPv4 literal(s) in the design-sync upload set — this is what a "
        "fixture regenerated from a real collection looks like. RFC 1918 counts: a real fleet is "
        "numbered from it, and this directory is the one place in the repo whose contents leave "
        "the host:\n  " + "\n  ".join(sorted(set(offenders)))
    )


def test_the_ip_rule_actually_rejects_a_real_fleet_address():
    """Guard the guard, at the level of the predicate. The check above is a `not offenders` loop
    over a clean directory, so it is green whether the rule is right or wrong — the pre-fix
    version passed with real client management addresses planted in the upload set. Pin the
    rule's DECISIONS directly, in both directions."""
    # what a fixture regenerated from a real collection looks like -> REJECTED
    for host in ("10.200.200.1", "10.14.7.22", "172.16.4.9", "192.168.10.254", "8.8.8.8",
                 "203.0.114.7"):
        assert not _is_non_identifying(host, False), f"{host} must count as client-identifying"
    # a private address is NOT laundered by a trailing slash unless it really is the CIDR base
    assert not _is_non_identifying("10.14.7.22", False)
    assert _is_non_identifying("10.0.0.0", True)          # the address-space example, allowed
    # the documented fictional ranges and the identifies-nobody specials -> allowed either way
    for ok in ("192.0.2.1", "198.51.100.9", "203.0.113.5", "198.18.0.1", "127.0.0.1",
               "0.0.0.0", "224.0.0.5", "169.254.1.1"):
        assert _is_non_identifying(ok, False), f"{ok} must not be flagged"
    assert _is_non_identifying("1.2.3.4.5", False)        # not an address at all


def _config_path_citations() -> list[tuple[str, Path, str]]:
    """(key, resolved path, expected kind) for every path-like config value.

    `entry` and `readmeHeader` are repo-root-relative; the remaining converter inputs are relative
    to the private app package. Reading the mappings dynamically enrolls every future component.
    """
    cfg = _config()
    out: list[tuple[str, Path, str]] = []
    for key in ("entry", "readmeHeader"):
        if isinstance(cfg.get(key), str):
            out.append((key, _REPO / cfg[key], "file"))
    for key in ("cssEntry", "tsconfig"):
        if isinstance(cfg.get(key), str):
            out.append((key, _FRONTEND / cfg[key], "file"))
    if isinstance(cfg.get("docsDir"), str):
        out.append(("docsDir", _FRONTEND / cfg["docsDir"], "directory"))
    for i, extra in enumerate(cfg.get("extraEntries") or []):
        out.append((f"extraEntries[{i}]", _FRONTEND / extra, "file"))
    for comp, src in sorted((cfg.get("componentSrcMap") or {}).items()):
        out.append((f"componentSrcMap.{comp}", _FRONTEND / src, "file"))
    return out


@pytest.mark.parametrize("key,path,kind", _config_path_citations(), ids=lambda v: str(v)[:40])
def test_config_json_path_citations_resolve(key, path, kind):
    """A path in config.json that stops resolving breaks the next `resync` run, and the failure
    surfaces inside the external converter rather than here."""
    exists_as_expected = path.is_dir() if kind == "directory" else path.is_file()
    assert exists_as_expected, f"config.json {key} cites missing {kind}: {path}"


def test_design_sync_public_component_surfaces_stay_in_lockstep():
    """Every public Design card has one source, prop contract, doc, preview, and barrel export."""
    cfg = _config()
    component_src_map = cfg.get("componentSrcMap")
    dts_props_for = cfg.get("dtsPropsFor")
    assert isinstance(component_src_map, dict) and component_src_map, \
        "config.json componentSrcMap must be a non-empty object"
    assert isinstance(dts_props_for, dict) and dts_props_for, \
        "config.json dtsPropsFor must be a non-empty object"

    barrel_exports = _barrel_exports()
    missing_helpers = _BARREL_HELPER_EXPORTS - barrel_exports
    assert not missing_helpers, (
        "ds.entry.ts lost documented non-component helper export(s): "
        + ", ".join(sorted(missing_helpers))
    )
    barrel_components = barrel_exports - _BARREL_HELPER_EXPORTS

    provider = cfg.get("provider")
    assert isinstance(provider, dict) and isinstance(provider.get("component"), str), \
        "config.json provider.component must name the public preview-support provider"
    assert provider["component"] in barrel_components, (
        f"configured provider {provider['component']!r} is not exported from ds.entry.ts"
    )

    docs_dir_value = cfg.get("docsDir")
    assert isinstance(docs_dir_value, str), "config.json docsDir must be a path string"
    docs_dir = _FRONTEND / docs_dir_value
    previews_dir = _DS / "previews"
    assert docs_dir.is_dir(), f"configured docsDir is missing: {docs_dir}"
    assert previews_dir.is_dir(), f"design-sync previews directory is missing: {previews_dir}"

    surfaces = {
        "componentSrcMap": set(component_src_map),
        "dtsPropsFor": set(dts_props_for),
        "docsDir/*.md": {path.stem for path in docs_dir.glob("*.md") if path.is_file()},
        "previews/*.tsx": {
            path.stem for path in previews_dir.glob("*.tsx") if path.is_file()
        },
        "ds.entry.ts components": barrel_components,
    }
    all_names = set().union(*surfaces.values())
    omissions = {
        surface: sorted(all_names - names)
        for surface, names in surfaces.items()
        if names != all_names
    }
    assert not omissions, (
        "design-sync public component surfaces drifted; each name must occur in componentSrcMap, "
        "dtsPropsFor, docs, previews, and the manual barrel:\n  "
        + "\n  ".join(f"{surface} missing: {', '.join(names)}" for surface, names in omissions.items())
    )

    discovered = _source_component_exports()
    wrong_sources = {
        name: source
        for name, source in component_src_map.items()
        if name != provider["component"]
        and str(Path(source)) not in discovered.get(name, set())
    }
    assert not wrong_sources, (
        "componentSrcMap must cite the module that actually exports each component; mismatches: "
        + ", ".join(f"{name} -> {source}" for name, source in sorted(wrong_sources.items()))
    )


def test_manual_barrel_covers_source_components_except_internal_topology3d():
    """Catch a new exported component that was omitted from the converter's manual barrel."""
    discovered = _source_component_exports()
    stale_exclusions = _DELIBERATE_SOURCE_ONLY_COMPONENTS - set(discovered)
    assert not stale_exclusions, (
        "documented internal-component exclusion is stale: "
        + ", ".join(sorted(stale_exclusions))
    )

    public_barrel_components = _barrel_exports() - _BARREL_HELPER_EXPORTS
    missing = set(discovered) - _DELIBERATE_SOURCE_ONLY_COMPONENTS - public_barrel_components
    details = [f"{name} ({', '.join(sorted(discovered[name]))})" for name in sorted(missing)]
    assert not missing, (
        "PascalCase component export(s) are missing from ds.entry.ts; add each public component to "
        "the barrel/componentSrcMap/dtsPropsFor/docs/previews, or document a deliberate internal "
        "exclusion:\n  " + "\n  ".join(details)
    )


def test_dts_props_for_never_uses_the_unknown_index_placeholder():
    """The private app emits no declarations, so a missing manual body becomes an empty API."""
    dts_props_for = _config().get("dtsPropsFor")
    assert isinstance(dts_props_for, dict) and dts_props_for
    assert _is_empty_or_placeholder_dts("[key: string]: unknown;"), \
        "guard bug: the converter's known placeholder is not recognised"
    assert _is_empty_or_placeholder_dts("{ }"), \
        "guard bug: an empty props body is not recognised"
    placeholders = {
        name: body for name, body in dts_props_for.items()
        if _is_empty_or_placeholder_dts(body)
    }
    assert not placeholders, (
        "dtsPropsFor must publish concrete props, not the converter's "
        f"[key: string]: unknown placeholder: {placeholders}"
    )


def test_topology_fixture_preserves_bridge_assessment_authority():
    """A claimed bridge is unusable unless the fixture also carries its assessed bits.

    TopologyGraph intentionally discards ``is_bridge`` when the edge-level authority flag is
    absent. The fleet-level flag separately controls its incomplete-assessment notice. A fixture
    that says "2 bridges" while omitting either class of authority therefore contradicts the
    surrounding Design cards, even though only ``bridge_assessed`` gates red SPOF styling.
    """
    text = _SAMPLE.read_text(encoding="utf-8")
    graph = text.split("const GRAPH =", 1)[1].split("const CABLE_MAP =", 1)[0]
    edges = graph.split("edges: [", 1)[1].split("],", 1)[0]
    edge_count = len(re.findall(r"\{\s*source:", edges))

    assert edge_count > 0, "GRAPH fixture has no edges; authority assertions would be vacuous"
    assert graph.count("link_centrality_assessed: true") == 1
    assert len(re.findall(r"\bbridge_assessed:\s*true\b", edges)) == edge_count, (
        "every GRAPH edge must explicitly carry bridge_assessed: true when bridge claims are used"
    )
    assert len(re.findall(r"\bis_bridge:\s*true\b", edges)) == 2, (
        "the fictional Meridian evidence and D-02 both claim exactly two assessed bridge links"
    )


def test_sample_fleet_collection_counts_are_self_consistent():
    """Derive switch collection coverage instead of trusting duplicated display totals."""
    text = _SAMPLE.read_text(encoding="utf-8")
    cable_map = text.split("const CABLE_MAP =", 1)[1].split("const CAUSAL_FLOWS =", 1)[0]
    collection_states = re.findall(
        r'host:\s*"[^"]+"[^\n]*kind:\s*"switch"[^\n]*collected:\s*(true|false)',
        cable_map,
    )
    assert collection_states == ["true"] * 8 + ["false"], (
        "the fictional fleet must contain eight collected switches and one uncollected switch"
    )

    assert 'summary: "aaa new-model absent on 4 of 8 collected devices"' in text
    assert re.search(
        r"coverage:\s*\{\s*inventory:\s*9,\s*collected:\s*8,\s*not_collected:\s*1",
        text,
    )
    provider_preview = (_DS / "previews" / "DemoDataProvider.tsx").read_text(encoding="utf-8")
    assert 'value={9} hint="8 collected · 1 not"' in provider_preview


def test_design_fixture_uses_the_canonical_lifecycle_contract():
    """Keep the upload fixture aligned with the server-owned lifecycle decision semantics."""
    text = _SAMPLE.read_text(encoding="utf-8")
    blueprint = text.split("const DESIGN =", 1)[1].split("const NRFU =", 1)[0]
    decisions = blueprint.split("decisions: [", 1)[1].split("tradeoff_scorecard:", 1)[0]
    decision_matches = list(re.finditer(r'^\s{6}id:\s*"([^"]+)"', decisions, re.MULTILINE))
    decision_ids = [match.group(1) for match in decision_matches]
    assert decision_ids == [
        "D-01",
        "lifecycle-eol-out-of-critical-roles",
        "fhrp-not-observed-is-not-healthy",
        "D-02",
        "lifecycle-near-ldos-refresh-before-deadline",
        "D-04",
        "lifecycle-past-eos-refresh-planning",
        "lifecycle-unknown-resolve-authority",
        "D-05",
    ], "baseline priority/count ordering and the lifecycle tie stabilizer must stay deterministic"

    blocks = {}
    for index, match in enumerate(decision_matches):
        end = decision_matches[index + 1].start() if index + 1 < len(decision_matches) else len(decisions)
        blocks[match.group(1)] = decisions[match.start():end]

    expected = {
        "lifecycle-eol-out-of-critical-roles": (
            "Critical",
            "Observed",
            "Supportability: the target fabric must not inherit end-of-support assets.",
            "2 device(s) are past last-day-of-support -- those end-of-support assets in forwarding roles "
            "cannot be safely relied on in the target design.",
        ),
        "lifecycle-near-ldos-refresh-before-deadline": (
            "High",
            "Observed",
            "Deadline risk: preserve time for a staged replacement before recorded LDoS.",
            "1 device(s) are within one year of recorded LDoS. Give each an owned, approved replacement "
            "disposition and implementation window before that deadline; the date band does not establish "
            "contract entitlement.",
        ),
        "lifecycle-past-eos-refresh-planning": (
            "Medium",
            "Observed",
            "Investment planning: act before sourcing and migration choices narrow.",
            "1 device(s) are past end-of-sale with recorded LDoS still future. Place each in an owned, dated "
            "refresh plan; this is not an immediate-removal or support-entitlement claim.",
        ),
        "lifecycle-unknown-resolve-authority": (
            "Medium",
            "Coverage-gap",
            "Coverage honesty: an unclassified asset needs evidence closure, not a healthy default.",
            "1 lifecycle row(s) are Unknown and 1 fleet asset(s) received no lifecycle row. Resolve exact "
            "PID/serial before carry-forward or procurement. Accept either a verified dated bulletin match, "
            "or a time-stamped authoritative EoX no-notice check with an owner and review date; no lifecycle "
            "or support-entitlement conclusion is inferred from absence.",
        ),
    }
    for decision_id, (priority, confidence, driver, summary) in expected.items():
        block = blocks[decision_id]
        assert 'domain: "methodology"' in block
        assert f'priority: "{priority}"' in block
        assert f'confidence: "{confidence}"' in block
        assert f'driver: "{driver}"' in block
        assert f'evidence: {{ summary: "{summary}"' in block
        assert "effective_priority" not in block

    coverage_block = blocks["fhrp-not-observed-is-not-healthy"]
    assert 'domain: "methodology"' in coverage_block
    assert 'priority: "Critical", status: "recommended", confidence: "Coverage-gap"' in coverage_block
    assert 'driver: "Coverage honesty: do not design resilience on devices you have not seen."' in coverage_block
    assert (
        'evidence: { summary: "1 of 9 inventoried device(s) were not collected -- their role and '
        'redundancy are UNKNOWN.' in coverage_block
    )
    assert 'count: 1, devices: [], fields: ["collection_completeness.summary.not_collected"]' in coverage_block
    assert "effective_priority" not in decisions, (
        "requirements_provided=false uses baseline priority/count ordering and must not publish weights"
    )

    assert re.search(
        r"n_decisions:\s*9,\s*n_recommended:\s*7,\s*n_needs_requirement:\s*2,\s*n_critical:\s*3",
        blueprint,
    )
    assert "by_domain: { resiliency: 2, methodology: 5, segmentation: 1, capacity: 1 }" in blueprint
    assert (
        'headline: "3 critical recommended target-state design decision(s); leading: Deploy first-hop '
        'redundancy (HSRP) on all user VLANs."' in blueprint
    )


def test_design_fixture_lifecycle_target_state_reconciles_overlapping_censuses():
    """Keep lifecycle bands disjoint while retaining the independent not-collected overlap."""
    text = _SAMPLE.read_text(encoding="utf-8")
    blueprint = text.split("const DESIGN =", 1)[1].split("const NRFU =", 1)[0]

    assert (
        'current: "2 past-LDoS, 2 approaching-LDoS or past-EoS (1 Near-LDoS; 1 Past-EoS), '
        '1 not-collected of 9 inventoried. 1 of the 8 lifecycle-assessed asset(s) carry an '
        'UNDETERMINED band. 1 asset(s) of the fleet census were NOT lifecycle-assessed at all '
        '(the axis produced no row for them)."' in blueprint
    )
    assert "identify ~3 pre-EoS date-band asset(s) as carry-forward candidates" in blueprint
    assert "collect the 1 un-assessed device(s) before finalising" in blueprint
    assert "A further 1 asset(s) were never lifecycle-assessed" in blueprint
    assert (
        'drivers: ["lifecycle-eol-out-of-critical-roles", '
        '"lifecycle-near-ldos-refresh-before-deadline", '
        '"lifecycle-past-eos-refresh-planning", "lifecycle-unknown-resolve-authority", '
        '"fhrp-not-observed-is-not-healthy"]' in blueprint
    )

    assert 'replace_now: [["WS-C2960S-48", 2]]' in blueprint
    assert 'refresh_soon: [["N5K-C56128P", 1], ["WS-C2960X-48FPD-L", 1]]' in blueprint
    assert 'undetermined: [["C9300-48P", 1], ["Unknown", 1]]' in blueprint
    assert re.search(
        r"n_replace:\s*2,\s*n_refresh:\s*2,\s*n_near:\s*1,\s*"
        r"n_past_eos:\s*1,\s*n_undetermined:\s*2,\s*n_not_assessed:\s*1",
        blueprint,
    )
    assert "support entitlement was not assessed" in blueprint

    causal = text.split("const CAUSAL_FLOWS =", 1)[1].split("const ARCH_REVIEW =", 1)[0]
    assert 'key: "lifecycle-past-ldos-access"' in causal
    assert 'title: "Past-LDoS access switches carry production video"' in causal
    assert 'fields: ["lifecycle_risk.per_device[].band"]' in causal
    assert 'fields: ["lifecycle"]' not in causal
    assert re.search(
        r"summary:\s*\{\s*n_flows:\s*5,\s*n_families:\s*5,\s*n_critical:\s*2,\s*"
        r"by_severity:\s*\{\s*Critical:\s*2,\s*High:\s*1,\s*Medium:\s*1,\s*Info:\s*1",
        causal,
    )
    provider_preview = (_DS / "previews" / "DemoDataProvider.tsx").read_text(encoding="utf-8")
    assert '<Kpi label="critical findings" value={2} tone="crit" />' in provider_preview, (
        "the canonical sample-fleet composition must agree with both critical-count summaries"
    )


def test_design_fixture_nrfu_tracks_every_recommended_decision_and_owner_citation():
    """NRFU generation is one-to-one, deterministically phased, and principle-traceable."""
    text = _SAMPLE.read_text(encoding="utf-8")
    nrfu = text.split("const NRFU =", 1)[1].split("const COVERAGE =", 1)[0]
    item_ids = re.findall(r'^\s{6}decision_id:\s*"([^"]+)"', nrfu, re.MULTILINE)
    assert item_ids == [
        "D-01",
        "fhrp-not-observed-is-not-healthy",
        "lifecycle-eol-out-of-critical-roles",
        "lifecycle-near-ldos-refresh-before-deadline",
        "lifecycle-past-eos-refresh-planning",
        "lifecycle-unknown-resolve-authority",
        "D-02",
    ]
    assert "n_items: 7" in nrfu
    assert "evpn_acceptance: []" in nrfu
    assert "proposer ≠ verifier" in nrfu

    expected_citations = {
        "lifecycle-eol-out-of-critical-roles": (
            "CCDE In Depth Ch.2 Scalability (scale-out avoids the Flag Day) & Cost/TCO; "
            "engine EoL/software_risk axes"
        ),
        "lifecycle-near-ldos-refresh-before-deadline": (
            "Cisco Product Lifecycle Policy; engine lifecycle_risk retained EoX evidence"
        ),
        "lifecycle-past-eos-refresh-planning": (
            "Cisco Product Lifecycle Policy; engine lifecycle_risk retained EoX evidence"
        ),
        "lifecycle-unknown-resolve-authority": (
            "Cisco Product Lifecycle Policy; engine lifecycle_risk coverage and provenance contract"
        ),
        "fhrp-not-observed-is-not-healthy": (
            "Repo doctrine (evidence-grounded, coverage-honest); commits ee3a362/642ee31 "
            "(FHRP false-health fix); analyze.py:1886 canonical FHRP gate"
        ),
    }
    item_matches = list(re.finditer(r'^\s{6}decision_id:\s*"([^"]+)"', nrfu, re.MULTILINE))
    blocks = {}
    for index, match in enumerate(item_matches):
        end = item_matches[index + 1].start() if index + 1 < len(item_matches) else len(nrfu)
        blocks[match.group(1)] = nrfu[match.start():end]
    for decision_id, citation in expected_citations.items():
        assert f'principle_citation: "{citation}"' in blocks[decision_id]

    coverage = text.split("const COVERAGE =", 1)[1].split("const DOMAIN_PACKS =", 1)[0]
    assert "Representative nine-class visual subset only" in coverage
    assert "27-class /architecture_coverage response" in coverage
