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
import re
from pathlib import Path

import pytest

_DS = Path(__file__).resolve().parents[1] / ".design-sync"

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


def _config_path_citations() -> list[tuple[str, str]]:
    """(key, path) for every path-like value in config.json — what the converter resolves at run
    time. Read from the file rather than hardcoded, so a new entry is covered automatically."""
    import json

    cfg = json.loads((_DS / "config.json").read_text(encoding="utf-8"))
    out: list[tuple[str, str]] = []
    for key in ("entry", "readmeHeader", "cssEntry", "tsconfig", "docsDir"):
        if isinstance(cfg.get(key), str):
            out.append((key, cfg[key]))
    for i, extra in enumerate(cfg.get("extraEntries") or []):
        out.append((f"extraEntries[{i}]", extra))
    for comp, src in sorted((cfg.get("componentSrcMap") or {}).items()):
        out.append((f"componentSrcMap.{comp}", src))
    return out


@pytest.mark.parametrize("key,cited", _config_path_citations(), ids=lambda v: str(v)[:40])
def test_config_json_path_citations_resolve(key, cited):
    """A path in config.json that stops resolving breaks the next `resync` run, and the failure
    surfaces inside the external converter rather than here.

    The config mixes two bases — `entry`/`readmeHeader` are repo-root-relative while `cssEntry`,
    `tsconfig` and `componentSrcMap` are relative to the package dir — and the resolution rules
    belong to a tool this repo does not vendor. So this asserts the weaker, checkable claim: the
    citation resolves from one of those two bases. It cannot prove the converter picks the same
    one; it does prove the file has not been moved or deleted."""
    repo = _DS.parent
    bases = (repo, repo / "webapp" / "frontend")
    resolved = [b / cited for b in bases if (b / cited).exists()]
    assert resolved, (
        f"config.json {key} = {cited!r} resolves from neither the repo root nor webapp/frontend; "
        f"the next design-sync run will fail on it"
    )
