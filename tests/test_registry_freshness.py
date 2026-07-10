"""Freshness guard for the SSOT registry's STATUS and cached-VALUE prose (docs/ssot.md).

`test_ssot_registry.py` guards the registry's POINTERS: every owner file/symbol it names must
resolve. This file guards the complementary rot class found live on 2026-07-10 (architect plan
gap G-005 / task P0-5): rows whose pointers resolve fine while their PROSE has gone stale --

  (a) a STATUS claim contradicting the tracked tree -- the intel-feed row still said
      "no live feed yet (no sweep run)" while `docs/intel/feed-2026-07-07.jsonl` sat TRACKED
      with 93 CISA-KEV entries, and the vault-digest row said "no digest data yet" after the
      first digest had been produced on the owner machine;
  (b) a cached VALUE drifting from the owner named on the same row -- the release-version
      cache said 3.26.0 while `pyproject.toml` said 3.30.0.

Same doctrine as the pointer guard (Law 1: a copy is a cache and must reconcile to its owner),
applied to the registry's own prose. Anchors stay as structural as prose allows: owner paths,
dated `feed-YYYY-MM-DD.jsonl` filenames, `(currently N)` caches, and narrow absence-claim
phrases. Double-quoted spans are stripped before scanning for absence claims, so the display
CONTRACTS the rows legitimately quote (`Empty -> "no intel feed (gated)"`) never false-positive
as status claims. Removing a value cache entirely is always a PASS -- reference-don't-restate
is the registry's preferred end state; this guard only bites a cache that is present AND wrong.
"""
import json
import os
import re
import subprocess

import pytest

from test_ssot_registry import ROOT, _main_checkout_root, _registry_text

DATED_FEED = re.compile(r"feed-\d{4}-\d{2}-\d{2}\.jsonl")
DATED_DIGEST = re.compile(r"digest-\d{4}-\d{2}-\d{2}\.jsonl")
# Narrow status-claim phrases, checked on quote-stripped text only. Deliberately NOT a generic
# negation scan: the rows legitimately contain conditional contracts ("no digest => recall falls
# back to graph+docs") that describe behavior when data is absent, not a claim that it is.
FEED_ABSENCE = re.compile(r"\bno\s+(?:live\s+)?feed\b|\bno\s+sweep\b", re.IGNORECASE)
DIGEST_ABSENCE = re.compile(r"\bno\s+digest\s+(?:data\s+)?yet\b|\bno\s+data\s+yet\b", re.IGNORECASE)


def _row(anchor: str) -> str:
    """The single registry table row containing the structural anchor (an owner path fragment)."""
    rows = [ln for ln in _registry_text().splitlines() if anchor in ln]
    assert rows, f"registry no longer has a row anchored by {anchor!r} -- repoint this guard"
    assert len(rows) == 1, f"anchor {anchor!r} is ambiguous in the registry ({len(rows)} rows)"
    return rows[0]


def _strip_quoted(text: str) -> str:
    """Drop double-quoted spans -- they are quoted DISPLAY contracts, not status claims."""
    return re.sub(r'"[^"]*"', '""', text)


def _tracked(subdir: str) -> list:
    """Filenames git tracks under ROOT/<subdir> (the reality a status claim must not contradict)."""
    try:
        out = subprocess.run(
            ["git", "ls-files", subdir],
            cwd=ROOT, capture_output=True, text=True, timeout=30, check=True,
        ).stdout
    except Exception:
        pytest.skip("git unavailable -- cannot establish tracked-file reality")
    return [line.rsplit("/", 1)[-1] for line in out.splitlines() if line.strip()]


def _pyproject_version() -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    try:
        import tomllib
        return tomllib.loads(text)["project"]["version"]
    except ModuleNotFoundError:  # pre-3.11 fallback; the key is unique in this pyproject
        m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
        assert m, "pyproject.toml no longer carries a version -- the owner itself moved"
        return m.group(1)


# --- (b) cached VALUES must reconcile to the owner named on the same row -------------------------

def test_release_version_cache_reconciles_to_pyproject():
    """The exact 2026-07-10 drift: the row named pyproject.toml as owner while caching 3.26.0
    against an owner that said 3.30.0. A '(currently N)' cache is optional; a wrong one is a bug."""
    row = _row("**Release version**")
    assert "pyproject.toml" in row, "Release-version row no longer names its owner"
    cached = re.search(r"\(currently\s+([0-9][\w.]*)\)", row)
    if cached is None:
        return  # cache removed -- reference-don't-restate; nothing to reconcile
    owner = _pyproject_version()
    assert cached.group(1) == owner, (
        f"docs/ssot.md caches release version {cached.group(1)} but the owner it names "
        f"(pyproject.toml) says {owner} -- update the cache from the owner"
    )


def test_schema_version_cache_reconciles_to_package():
    """Same cache class, other version row. This reconciles the CACHE to cisco_toolkit.__version__;
    it does NOT equate schema and release versions (they are decoupled by design -- row 32's rule)."""
    import cisco_toolkit

    row = _row("**Schema version**")
    assert "__version__" in row, "Schema-version row no longer names its owner symbol"
    cached = re.search(r"\(currently\s+([0-9][\w.]*)\)", row)
    if cached is None:
        return
    assert cached.group(1) == cisco_toolkit.__version__, (
        f"docs/ssot.md caches schema version {cached.group(1)} but cisco_toolkit.__version__ "
        f"is {cisco_toolkit.__version__}"
    )


def test_intel_feed_entry_count_cache_reconciles_to_manifest():
    """If the feed row caches an entry count ('N CISA KEV entries'), it must match the `n` field
    of the signed manifest (line 1) of the dated feed file the row cites. No count stated = pass."""
    row = _row("docs/intel/feed-")
    count = re.search(r"(\d+)\s+CISA[\s-]?KEV\s+entries", row, re.IGNORECASE)
    if count is None:
        return
    cited = DATED_FEED.findall(row)
    assert cited, "feed row caches an entry count but cites no dated feed file to reconcile against"
    manifest = json.loads((ROOT / "docs" / "intel" / cited[0]).read_text(encoding="utf-8").splitlines()[0])
    assert manifest.get("kind") == "intel-feed-manifest", f"{cited[0]} line 1 is not the manifest"
    assert int(count.group(1)) == manifest.get("n"), (
        f"docs/ssot.md caches {count.group(1)} feed entries but {cited[0]}'s manifest says n={manifest.get('n')}"
    )


# --- (a) STATUS claims must not contradict the tracked tree --------------------------------------

def test_intel_feed_status_does_not_contradict_tracked_files():
    """The exact 2026-07-10 drift: 'no live feed yet (no sweep run)' while feed-2026-07-07.jsonl
    was tracked. Both directions: tracked feeds forbid an absence claim; zero tracked feeds forbid
    citing a dated feed. Every dated feed the row cites must actually be tracked."""
    row = _row("docs/intel/feed-")
    tracked = [f for f in _tracked("docs/intel") if DATED_FEED.fullmatch(f)]
    cited = DATED_FEED.findall(row)
    if tracked:
        claim = FEED_ABSENCE.search(_strip_quoted(row))
        assert claim is None, (
            f"docs/ssot.md intel-feed row claims {claim.group(0)!r} but git tracks {tracked} -- "
            "the status line has rotted; update it from the tree"
        )
    else:
        assert not cited, (
            f"docs/ssot.md intel-feed row cites {cited} but git tracks no feed files -- "
            "the row claims data that no clone carries"
        )
    ghosts = [f for f in cited if f not in tracked]
    assert not ghosts, f"docs/ssot.md intel-feed row cites untracked feed files: {ghosts}"


def test_vault_digest_never_tracked_and_row_stays_clean_clone_honest():
    """Runs everywhere. Two clean-clone invariants: (1) digest data must NEVER be tracked --
    .gitignore fences `docs/vault-digest/digest-*.jsonl` because it derives from the personal
    vault; a tracked digest is a privacy leak, whatever the registry says. (2) If the row cites
    a dated digest as produced, it must also carry the gitignore qualifier, so a clean-clone
    reader is told the file deliberately does not exist on their checkout."""
    tracked = [f for f in _tracked("docs/vault-digest") if DATED_DIGEST.fullmatch(f)]
    assert not tracked, (
        f"personal-vault-derived digest files are TRACKED: {tracked} -- the .gitignore privacy "
        "fence (docs/vault-digest/digest-*.jsonl) has been bypassed"
    )
    row = _row("docs/vault-digest/digest-")
    if DATED_DIGEST.search(row):
        assert "gitignor" in row, (
            "digest row cites a produced digest without saying it is gitignored/owner-machine-only "
            "-- clean-clone readers would go looking for a file that deliberately is not there"
        )


@pytest.mark.skipif(bool(os.environ.get("CI")),
                    reason="digest data is gitignored (personal-vault-derived) -- only the owner "
                           "machine can compare the row's status claim against reality")
def test_vault_digest_status_matches_owner_machine_reality():
    """Owner machine only (mirrors the side-engagement existence guard): digests live untracked
    under the MAIN checkout, so compare the row's claim against that tree. A produced digest
    forbids an absence claim; a cited digest must exist; no digest on disk forbids citing one."""
    row = _row("docs/vault-digest/digest-")
    digest_dir = _main_checkout_root() / "docs" / "vault-digest"
    on_disk = sorted(p.name for p in digest_dir.glob("digest-*.jsonl")) if digest_dir.is_dir() else []
    cited = DATED_DIGEST.findall(row)
    if on_disk:
        claim = DIGEST_ABSENCE.search(_strip_quoted(row))
        assert claim is None, (
            f"docs/ssot.md vault-digest row claims {claim.group(0)!r} but the owner machine holds "
            f"{on_disk} under {digest_dir} -- the status line has rotted"
        )
    else:
        assert not cited, (
            f"docs/ssot.md vault-digest row cites {cited} but no digest exists under {digest_dir}"
        )
    ghosts = [f for f in cited if f not in on_disk]
    assert not ghosts, f"docs/ssot.md vault-digest row cites digests missing from the owner machine: {ghosts}"
