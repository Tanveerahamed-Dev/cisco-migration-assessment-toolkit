"""Freshness guard for the SSOT registry's STATUS and cached-VALUE prose (docs/ssot.md).

`test_ssot_registry.py` guards the registry's POINTERS: every owner file/symbol it names must
resolve. This file guards the complementary rot class found live on 2026-07-10 (architect plan
gap G-005 / task P0-5): rows whose pointers resolve fine while their PROSE has gone stale --

  (a) a STATUS claim contradicting the tracked tree -- the intel-feed row still said
      "no live feed yet (no sweep run)" while `docs/intel/feed-2026-07-07.jsonl` sat TRACKED
      with 93 verified CISA-KEV entries, and the vault-digest row said "no digest data yet"
      after the first digest had been produced on the owner machine;
  (b) a cached VALUE drifting from the owner named on the same row -- the release-version
      cache said 3.26.0 while `pyproject.toml` said 3.30.0.

Same doctrine as the pointer guard (Law 1: a copy is a cache and must reconcile to its owner),
applied to the registry's own prose. Anchors stay as structural as prose allows: table rows
only, owner paths, dated `feed-YYYY-MM-DD.jsonl` filenames, `(currently N)` caches, and narrow
absence-claim phrases. Double-quoted spans (straight or curly) are stripped before scanning for
absence claims, so the display CONTRACTS the rows legitimately quote (`Empty -> "no intel feed
(gated)"`) never false-positive as status claims. Removing a value cache entirely is always a
PASS -- reference-don't-restate is the registry's preferred end state; this guard only bites a
cache that is present AND wrong -- and the `(currently ...)` completeness scan keeps that rule
fail-closed for caches added to rows this file doesn't anchor yet.

Feed facts are read through `cisco_toolkit.intel_feed.verify_feed` (the provenance gate the
registry row itself names as consumer) rather than a private re-parse: the manifest's
self-declared `n` is NOT covered by the feed's SHA-256, so the reconcile target is the count of
*verified* entries, and a feed the gate refuses can't back the row's claims at all.
"""
import os
import re
import subprocess
from fnmatch import fnmatch
from pathlib import Path

import pytest

from cisco_toolkit import intel_feed, recall
from test_ssot_registry import ROOT, _main_checkout_root, _registry_text

# Store locations come from their owner modules (a second hardcoding of "where feeds live" would
# itself be the drift this file polices). os.path.join gives the platform separator; git pathspecs
# want "/" on every platform.
INTEL_DIR = intel_feed.INTEL_DIR
VAULT_DIGEST_DIR = recall.VAULT_DIGEST_DIR
FEED_GLOB = "feed-*.jsonl"        # breadth of the row's owner-cell pattern (and the producer contract)
DIGEST_GLOB = "digest-*.jsonl"    # breadth of the .gitignore privacy fence -- NOT only dated names

DATED_FEED = re.compile(r"feed-\d{4}-\d{2}-\d{2}\.jsonl")
DATED_DIGEST = re.compile(r"digest-\d{4}-\d{2}-\d{2}\.jsonl")
# Narrow status-claim phrases, checked on quote-stripped TABLE-ROW text only. Deliberately NOT a
# generic negation scan: the rows legitimately contain conditional contracts ("no digest => recall
# falls back to graph+docs") that describe behavior when data is absent, not a claim that it is.
# "intel" is included because `intel_feed.load_feeds` itself emits "no intel feed ..." -- the most
# likely wording for a recurrence of the 2026-07-10 rot.
FEED_ABSENCE = re.compile(r"\bno\s+(?:live\s+|intel\s+)?feeds?\b|\bno\s+sweep\b", re.IGNORECASE)
DIGEST_ABSENCE = re.compile(
    r"\bno\s+digests?\s+(?:data\s+)?yet\b|\bno\s+data\s+yet\b|\bnot\s+yet\s+produced\b", re.IGNORECASE)
# The registry's value-cache idiom. Case-insensitive and tolerant of "v" so a reworded cache is
# still checked instead of silently retiring the guard (fail-closed, not fail-open).
CACHED_CURRENT = re.compile(r"\(currently[:\s]+v?([0-9][\w.]*)\)", re.IGNORECASE)


def _row(anchor: str) -> str:
    """The single registry TABLE ROW containing the structural anchor (an owner path fragment).
    Restricting to `|` rows keeps a prose footnote that mentions the same path from making the
    anchor ambiguous -- or worse, being scanned in place of the real row."""
    rows = [ln for ln in _registry_text().splitlines() if ln.lstrip().startswith("|") and anchor in ln]
    assert rows, f"registry no longer has a table row anchored by {anchor!r} -- repoint this guard"
    assert len(rows) == 1, f"anchor {anchor!r} is ambiguous in the registry ({len(rows)} rows)"
    return rows[0]


def _strip_quoted(text: str) -> str:
    """Drop double-quoted spans (straight or typographic) -- they are quoted DISPLAY contracts,
    not status claims."""
    return re.sub(r'"[^"]*"|“[^”]*”', '""', text)


def _tracked(subdir: str, pattern: str) -> list:
    """Basenames git tracks under ROOT/<subdir> matching pattern (the reality a status claim must
    not contradict). Skips only when git itself is unavailable (OSError: not installed / not on
    PATH); a FAILING git call (non-repo ROOT, timeout) propagates loudly -- that is broken guard
    infrastructure, not an environment without git."""
    try:
        out = subprocess.run(
            ["git", "ls-files", subdir.replace(os.sep, "/")],
            cwd=ROOT, capture_output=True, text=True, timeout=30, check=True,
        ).stdout
    except OSError:
        pytest.skip("git unavailable -- cannot establish tracked-file reality")
    names = [line.rsplit("/", 1)[-1] for line in out.splitlines() if line.strip()]
    return [n for n in names if fnmatch(n, pattern)]


def _pyproject_version() -> str:
    """One parser on every supported interpreter (a tomllib/regex split gave 3.10 and 3.11+
    different failure behavior for the same tree). The key is unique in this repo's pyproject."""
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    assert m, "pyproject.toml no longer carries a [project] version -- the owner itself moved"
    return m.group(1)


# --- (b) cached VALUES must reconcile to the owner named on the same row -------------------------

def test_release_version_cache_reconciles_to_pyproject():
    """The exact 2026-07-10 drift: the row named pyproject.toml as owner while caching 3.26.0
    against an owner that said 3.30.0. A '(currently N)' cache is optional; a wrong one is a bug."""
    row = _row("**Release version**")
    assert "pyproject.toml" in row, "Release-version row no longer names its owner"
    cached = CACHED_CURRENT.search(row)
    if cached is None:
        return  # cache removed -- reference-don't-restate; nothing to reconcile
    owner = _pyproject_version()
    assert cached.group(1) == owner, (
        f"docs/ssot.md caches release version {cached.group(1)} but the owner it names "
        f"(pyproject.toml) says {owner} -- update the cache from the owner"
    )


def test_schema_version_cache_reconciles_to_package():
    """Same cache class, other version row. This reconciles the CACHE to cisco_toolkit.__version__;
    it does NOT equate schema and release versions (they are decoupled by design -- that row's rule)."""
    import cisco_toolkit

    row = _row("**Schema version**")
    assert "__version__" in row, "Schema-version row no longer names its owner symbol"
    cached = CACHED_CURRENT.search(row)
    if cached is None:
        return
    assert cached.group(1) == cisco_toolkit.__version__, (
        f"docs/ssot.md caches schema version {cached.group(1)} but cisco_toolkit.__version__ "
        f"is {cisco_toolkit.__version__}"
    )


def test_every_currently_cache_is_enrolled_in_this_guard():
    """Completeness scan (fail-closed): the two tests above anchor specific rows, so a NEW
    '(currently ...)' cache added anywhere else in the registry would be unguarded -- the
    3.26.0-vs-3.30.0 rot recurring one row over. Any registry line using the cache idiom must be
    one of the enrolled rows; enrolling means adding a reconcile test here."""
    enrolled = ("**Release version**", "**Schema version**")
    strays = [ln.strip() for ln in _registry_text().splitlines()
              if "(currently" in ln.lower() and not any(a in ln for a in enrolled)]
    assert not strays, (
        "docs/ssot.md caches a value with '(currently ...)' on a row this guard does not "
        f"reconcile -- add a reconcile test for it in {Path(__file__).name}: {strays}"
    )


def test_intel_feed_entry_count_cache_reconciles_to_verified_feed():
    """If the feed row caches an entry count ('N CISA KEV entries'), it must match the count of
    entries the provenance gate (`intel_feed.verify_feed` -- the consumer the row itself names)
    actually verifies in the dated feed the row cites. The manifest's self-declared `n` is NOT
    hash-covered, so it is not the reconcile target. No count stated = pass."""
    row = _row(f"{INTEL_DIR.replace(os.sep, '/')}/feed-")
    count = re.search(r"(\d+)\s+(?:verified\s+)?CISA[\s-]?KEV\s+entries", row, re.IGNORECASE)
    if count is None:
        return
    cited = sorted(set(DATED_FEED.findall(row)))
    assert cited, "feed row caches an entry count but cites no dated feed file to reconcile against"
    assert len(cited) == 1, (
        f"feed row cites {len(cited)} dated feeds {cited}; this guard reconciles the count against "
        "exactly one -- extend it before citing multiple feeds on the row"
    )
    path = ROOT / INTEL_DIR / cited[0]
    assert path.exists(), f"feed row cites {cited[0]} but {path} does not exist -- repoint the row"
    res = intel_feed.verify_feed(path.read_text(encoding="utf-8"))
    assert res["ok"], (
        f"feed row cites {cited[0]} but the provenance gate refuses it ({res['reason']}) -- "
        "a refused feed cannot back the row's status or count claims"
    )
    assert int(count.group(1)) == len(res["entries"]), (
        f"docs/ssot.md caches {count.group(1)} feed entries but verify_feed({cited[0]}) verifies "
        f"{len(res['entries'])} -- update the cache from the verified feed"
    )


# --- (a) STATUS claims must not contradict the tracked tree --------------------------------------

def test_intel_feed_status_does_not_contradict_tracked_files():
    """The exact 2026-07-10 drift: 'no live feed yet (no sweep run)' while feed-2026-07-07.jsonl
    was tracked. Tracked feeds forbid an absence claim; every dated feed the row cites must be
    tracked (which also covers the no-tracked-feeds-but-row-cites-one direction)."""
    row = _row(f"{INTEL_DIR.replace(os.sep, '/')}/feed-")
    tracked = _tracked(INTEL_DIR, FEED_GLOB)
    if tracked:
        claim = FEED_ABSENCE.search(_strip_quoted(row))
        assert claim is None, (
            f"docs/ssot.md intel-feed row claims {claim.group(0)!r} but git tracks {tracked} -- "
            "the status line has rotted; update it from the tree"
        )
    ghosts = [f for f in DATED_FEED.findall(row) if f not in tracked]
    assert not ghosts, f"docs/ssot.md intel-feed row cites feed files git does not track: {ghosts}"


def test_vault_digest_never_tracked_and_row_stays_clean_clone_honest():
    """Runs everywhere. Two clean-clone invariants, ordered so the git-independent one always
    executes: (1) if the row cites a dated digest as produced, it must also carry the gitignore
    qualifier, so a clean-clone reader is told the file deliberately does not exist on their
    checkout; (2) digest data must NEVER be tracked -- .gitignore fences `digest-*.jsonl`
    (personal-vault-derived); a tracked digest is a privacy leak, whatever the registry says.
    The tracked check uses the FENCE's breadth (any digest-*.jsonl), not only dated names, so a
    force-added `digest-latest.jsonl` cannot slip past it."""
    row = _row(f"{VAULT_DIGEST_DIR.replace(os.sep, '/')}/digest-")
    if DATED_DIGEST.search(row):
        assert "gitignor" in row, (
            "digest row cites a produced digest without saying it is gitignored/owner-machine-only "
            "-- clean-clone readers would go looking for a file that deliberately is not there"
        )
    tracked = _tracked(VAULT_DIGEST_DIR, DIGEST_GLOB)
    assert not tracked, (
        f"personal-vault-derived digest files are TRACKED: {tracked} -- the .gitignore privacy "
        f"fence ({VAULT_DIGEST_DIR.replace(os.sep, '/')}/{DIGEST_GLOB}) has been bypassed"
    )


def test_vault_digest_status_matches_owner_machine_reality():
    """Digest reality is only observable where a digest exists (the MAIN checkout on the owner
    machine -- mirrors the side-engagement existence guard). A checkout with no digest on disk
    is indistinguishable from a clean clone, WHICH THE ROW DOCUMENTS AS A DESIGNED STATE -- so
    absence here is a skip, never a failure (unlike the side-engagement guard, where absence
    means lost artifacts). This also covers hosted CI without an env-var proxy. Where a digest
    IS visible: the row may not claim absence, and every digest it cites must exist."""
    row = _row(f"{VAULT_DIGEST_DIR.replace(os.sep, '/')}/digest-")
    digest_dir = _main_checkout_root() / VAULT_DIGEST_DIR
    on_disk = sorted(p.name for p in digest_dir.glob(DIGEST_GLOB)) if digest_dir.is_dir() else []
    if not on_disk:
        pytest.skip("no digest on this checkout -- owner-machine reality not observable here "
                    "(clean clones / worktrees / CI carry none by design)")
    claim = DIGEST_ABSENCE.search(_strip_quoted(row))
    assert claim is None, (
        f"docs/ssot.md vault-digest row claims {claim.group(0)!r} but this machine holds "
        f"{on_disk} under {digest_dir} -- the status line has rotted"
    )
    ghosts = [f for f in DATED_DIGEST.findall(row) if f not in on_disk]
    assert not ghosts, f"docs/ssot.md vault-digest row cites digests missing from {digest_dir}: {ghosts}"


def test_registry_cites_this_guard_by_its_current_name():
    """The registry's enforcement cells name this file as their mechanical guard (4 rows), and
    ADR 0001 points here too. A rename would leave five citations asserting enforcement by a file
    that no longer exists -- this self-citation check goes red under the NEW name until the docs
    are repointed. (Deletion is covered by selfcheck.GUARD_FILES + test_ssot_registry's
    owner-files list.)"""
    assert Path(__file__).name in _registry_text(), (
        f"docs/ssot.md no longer cites {Path(__file__).name} -- if this guard was renamed, "
        "repoint the registry's enforcement cells (and selfcheck.GUARD_FILES) to the new name"
    )
