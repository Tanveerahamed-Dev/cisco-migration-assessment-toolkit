"""Verify that release archives contain the complete, privacy-safe runtime.

The verifier is intentionally stdlib-only.  It inspects an untrusted wheel and
sdist before installation, validates the wheel RECORD rather than trusting file
names, and proves that every installed command has its code and runtime assets.

What it compares archives against is the **working tree** at ``--root``.  The
``--source-commit`` / ``--source-tree`` arguments are a *claim* about which
commit that working tree is; they are resolved with a local, read-only ``git``
when a repository is present at ``--root``, and recorded as unverified
caller-supplied labels when one is not, because this module is also run against
a downloaded archive with no repository.  Nothing here touches the network.

Read ``source_binding`` in the emitted proof for what that resolution is worth.
Three limits are structural rather than incidental, and the block states all
three:

* **The binding is a SELF-check.**  Every value this module can reach -- the
  archives, the working tree, and the Git repository the claim is resolved
  against -- comes from the same checkout, so no field here can be evidence
  about an outside authority.  The headline field is named
  ``self_verified_against_this_worktree`` for that reason, and the constant
  ``independent_of_the_verified_worktree`` is ``false`` on every run this module
  can ever produce.  A binding to something genuinely independent is not
  implementable here; it would have to be supplied by a caller that is not this
  checkout (a signed tag verified against its signer, an attestation), and this
  module cannot tell whether it was given one.
* The claim is compared against ``git rev-parse HEAD`` **in the same work tree**
  the archives were built from.  Every current caller derives the claim from that
  same tree (``.github/workflows/*`` and ``RELEASING.md`` both run ``git
  rev-parse`` there), so for those callers the comparison is a tautology: it
  proves the caller quoted its own tree correctly and nothing about which
  reviewed revision that tree is.
* ``git status --untracked-files=no`` and ``git ls-files`` see tracked paths only,
  while the archives ship untracked paths (the built SPA under
  ``webapp/frontend/dist`` and the retained official sources under
  ``reference-data/`` above all).  Those members are shipped and bound to no
  commit at all; ``source_binding``,
  ``measurements.shipped_bytes_coverage`` and
  ``measurements.runtime_inventory`` disclose them by path prefix, and
  ``self_verified_against_this_worktree`` is false whenever any of them exists.

``source_binding.self_verified_against_this_worktree`` is the headline verdict.
Its coverage set is **the member set of the two archives that actually ship**,
not the expected runtime inventory: the sdist carries packaging files and the
retained official sources that the wheel's runtime inventory never names, and
deriving coverage from that inventory left those bytes bound to nothing while
the headline read true.  Members the build backend generates (``*.dist-info/**``,
``*.egg-info/**``, ``PKG-INFO``, ``setup.cfg``) cannot belong to any commit; they
stay in the denominator, are counted and disclosed by prefix as
``members_build_generated_unbindable``, and are never silently dropped.

The verdict is true only when the claim matches local HEAD, the tracked work
tree is clean, coverage of the shipped member set was measured, and nothing
shipped and bindable falls outside it.  Anything unmeasured leaves it false.

Part of what is compared is self-derived: ``measurements.runtime_inventory`` and
``measurements.sdist_source_inventory`` count how many members are "expected"
only because a glob found them on disk.  For those, expected and actual are the
same measurement, and the proof says so rather than presenting the agreement as
a check.

The verdict is **advisory** by default: ``main`` exits ``0`` on an unverified
binding, printing ``WARNING:`` caveats, because the ordinary run against a
downloaded archive has no repository to resolve and would otherwise be a
permanent red.  Pass ``--require-source-binding`` to make it exit ``3`` instead.
Repository CI, release, and publication workflows opt into that fail-closed
contract; ad-hoc callers that omit the flag must treat the field as disclosure.

Every field of ``measurements`` is a count of work actually performed rather than
a boolean that is true by construction, so ``--expected-json`` can detect a run
that checked less than the run that produced the trusted proof.
"""

from __future__ import annotations

import argparse
import base64
import configparser
import csv
import hashlib
import io
import json
import os
import re
import stat
import struct
import subprocess
import tarfile
import unicodedata
import zipfile
from collections import Counter
from email.parser import BytesParser
from email.policy import default as email_policy
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised by the Python 3.10 CI lane
    import tomli as tomllib

from .registry_integrity import PackIntegrityError, verify_retained_source_chain
from .eoldb import verify_retained_eol_source_chain

_FORBIDDEN_PARTS = {
    ".claude",
    ".design-sync",
    ".github",
    ".gstack",
    "docs",
    "portable",
    "research_lane",
    "tests",
}
_FORBIDDEN_SUFFIXES = (
    ".db",
    ".sqlite",
    ".sqlite3",
    ".docx",
    ".pptx",
    ".xlsx",
    ".precert.json",
    ".precert-readiness.json",
)
_EXPECTED_CONSOLE_SCRIPTS = {
    "assesshub": "webapp.backend.serve:main",
    "cisco-assess": "COLLECT_PARSE_V3_23_0:main",
    "cisco-mcp-server": "cisco_toolkit.mcp_server:main",
}
_SDIST_SOURCE_FILES = {
    "LICENSE",
    "MANIFEST.in",
    "README.md",
    "pyproject.toml",
    "setup.py",
}
_OFFICIAL_SOURCE_FILES = {
    "reference-data/official-sources/README.md",
    "reference-data/official-sources/manifest.json",
    "reference-data/official-sources/cisco/eol-bulletins.json",
    "reference-data/official-sources/iana/service-names-port-numbers.csv",
    "reference-data/official-sources/ieee/oui.csv",
    "reference-data/official-sources/ieee/mam.csv",
    "reference-data/official-sources/ieee/oui36.csv",
}
# The generated wheel metadata members this verifier reads and allows, minus the
# license documents: those are NOT a hand-maintained name here, because the
# wheel's own METADATA declares them in `License-File` and the allowlist is
# derived from that declaration (see `verify_archives`).  `licenses/LICENSE` used
# to be listed here, which allowed exactly one spelling and required none.
_WHEEL_METADATA_FILES = {
    "METADATA",
    "RECORD",
    "WHEEL",
    "entry_points.txt",
    "top_level.txt",
}
# The import roots the distribution is allowed to install.  One constant, used
# for the sdist's egg-info top_level.txt AND the wheel's dist-info copy: the
# wheel's was allowlisted as a member name and never read, so a wheel whose
# top_level.txt named a foreign package verified clean while the sdist's identical
# claim was checked.  The wheel is what pip installs, so that was the wrong half
# to leave unenforced.
_EXPECTED_TOP_LEVEL_PACKAGES = frozenset(
    {
        "COLLECT_PARSE_V3_23_0",
        "cisco_toolkit",
        "webapp",
    }
)
_WINDOWS_RESERVED_NAMES = {
    "aux",
    "con",
    "nul",
    "prn",
    *(f"com{number}" for number in range(1, 10)),
    *(f"lpt{number}" for number in range(1, 10)),
}
_MAX_ARCHIVE_BYTES = 256 * 1024 * 1024
_MAX_ARCHIVE_MEMBERS = 10_000
_MAX_MEMBER_BYTES = 64 * 1024 * 1024
_MAX_ARCHIVE_UNCOMPRESSED_BYTES = 512 * 1024 * 1024
_MAX_PROJECT_SOURCE_BYTES = 64 * 1024 * 1024
_MAX_PROJECT_TOTAL_BYTES = 512 * 1024 * 1024
_MAX_METADATA_BYTES = 4 * 1024 * 1024
_MAX_PROOF_BYTES = 1024 * 1024
_GIT_TIMEOUT_SECONDS = 120
_MAX_GIT_OUTPUT_BYTES = 8 * 1024 * 1024
_DIRTY_SAMPLE = 20
# Provenance of every member of the expected runtime inventory.  Only the first
# two are constrained by something outside the working tree being verified; the
# third exists in the expected set purely because it was found on disk, so its
# presence in an archive proves agreement with this tree and nothing more.
_PROVENANCE_REQUIRED = "verifier-required"
_PROVENANCE_INDEX = "frontend-index-referenced"
_PROVENANCE_WORKTREE = "worktree-glob"
_SOURCE_BINDING_GIT = "git-rev-parse"
_SOURCE_BINDING_UNVERIFIED = "unverified-caller-label"
# Exit-code status of the source binding, stated in the proof itself so a reader
# cannot mistake the disclosure for a control.  Constant on purpose: it describes
# the module's contract, not one run, so --expected-json stays comparable.
_BINDING_ENFORCEMENT = (
    "advisory: main() exits 0 on an unverified binding unless "
    "--require-source-binding is passed, which makes it exit 3"
)
_EXIT_UNVERIFIED_BINDING = 3
_UNTRACKED_PREFIX_SAMPLE = 40
# Constant, and constantly false: see the module docstring.  A reader who scans
# only the verdict field sees `self_verified_against_this_worktree`, and this
# pair states in the proof itself why no field here can say more than that.
_INDEPENDENT_BINDING = False
_INDEPENDENCE_LIMIT = (
    "structural, not incidental: the archives, the working tree and the Git "
    "repository the claim is resolved against are all the same checkout, so "
    "every value in this block is this release describing itself. "
    "self_verified_against_this_worktree is a SELF-check; it does NOT establish "
    "which reviewed revision the tree is. Only a claim carried in from outside "
    "-- a signed tag verified against its signer, a release ticket, a reviewer "
    "reading the commit id -- could do that, and this module cannot tell "
    "whether it was given one"
)
# Members the build backend synthesises.  No commit contains them, so they can
# never be bound; they stay in the coverage DENOMINATOR and are counted and
# disclosed by prefix rather than dropped, because a denominator that quietly
# excludes what it cannot cover is how a coverage figure becomes a lie.
# Matched structurally (a generated metadata directory / a PEP-517 generated
# top-level file), not by a hand-maintained list of this project's paths.
_BUILD_GENERATED_DIRECTORY_SUFFIXES = (".dist-info", ".egg-info")
_BUILD_GENERATED_TOP_LEVEL_FILES = frozenset({"PKG-INFO", "setup.cfg"})
_KNOWN_HOST_HASHES = PurePosixPath(
    ".github/privacy/known_client_hostname_sha256.txt"
)
_CONTENT_SCAN_EXEMPT = {
    "cisco_toolkit/data/oui_registry.tsv.gz",
    "cisco_toolkit/data/port_registry.tsv.gz",
    *_OFFICIAL_SOURCE_FILES,
}
_METADATA_SINGLETONS = {
    "Metadata-Version",
    "Name",
    "Version",
    "Summary",
    "Keywords",
    "Author",
    "Author-email",
    "Maintainer",
    "Maintainer-email",
    "Requires-Python",
    "Description-Content-Type",
    "License-Expression",
}


class _FrontendReferenceParser(HTMLParser):
    """Collect executable/style assets required by the built SPA shell."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.references: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "script" and values.get("src"):
            self.references.append(values["src"] or "")
            return
        if tag != "link" or not values.get("href"):
            return
        relationships = set((values.get("rel") or "").lower().split())
        if relationships.intersection({"stylesheet", "modulepreload", "preload", "icon"}):
            self.references.append(values["href"] or "")


def _frontend_references(index_data: bytes) -> tuple[set[str], list[str]]:
    """Return local dist-relative asset paths and malformed/offline violations."""

    errors: list[str] = []
    try:
        text = index_data.decode("utf-8")
    except UnicodeDecodeError as exc:
        return set(), [f"frontend index is not UTF-8: {exc}"]

    parser = _FrontendReferenceParser()
    parser.feed(text)
    parser.close()
    if not parser.references:
        errors.append("frontend index has no executable or stylesheet asset references")

    references: set[str] = set()
    for reference in parser.references:
        parsed = urlsplit(reference)
        if parsed.scheme == "data":
            continue
        if parsed.scheme or parsed.netloc:
            errors.append(f"frontend index uses a non-local runtime asset: {reference!r}")
            continue
        target = unquote(parsed.path).lstrip("/")
        parts = target.split("/")
        if (
            not target
            or "\\" in target
            or any(part in {"", ".", ".."} for part in parts)
            or PurePosixPath(target).as_posix() != target
        ):
            errors.append(f"frontend index has an unsafe asset path: {reference!r}")
            continue
        references.add(target)
    return references, errors


def _frontend_reference_errors(
    index_data: bytes,
    archive_names: set[str],
    index_name: str = "webapp/frontend/dist/index.html",
) -> list[str]:
    references, errors = _frontend_references(index_data)
    dist_root = PurePosixPath(index_name).parent
    for reference in sorted(references):
        member = (dist_root / reference).as_posix()
        if member not in archive_names:
            errors.append(f"frontend index references missing archive member: {member}")
    return errors


def _file_identity(info: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        int(info.st_dev),
        int(info.st_ino),
        int(info.st_mode),
        int(info.st_size),
        int(info.st_mtime_ns),
    )


def _is_reparse_point(info: os.stat_result) -> bool:
    attribute = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(int(getattr(info, "st_file_attributes", 0)) & attribute)


def _read_regular_bounded(path: Path, maximum: int) -> bytes:
    """Read one stable ordinary file without following links or reparse aliases."""
    before = path.lstat()
    if (
        stat.S_ISLNK(before.st_mode)
        or _is_reparse_point(before)
        or not stat.S_ISREG(before.st_mode)
    ):
        raise ValueError(f"not a regular non-link file: {path}")
    if before.st_size > maximum:
        raise ValueError(f"file exceeds {maximum} bytes: {path}")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or _file_identity(opened) != _file_identity(before)
        ):
            raise ValueError(f"file identity changed before read: {path}")
        data = bytearray()
        while len(data) <= maximum:
            block = os.read(
                descriptor,
                min(1024 * 1024, maximum + 1 - len(data)),
            )
            if not block:
                break
            data.extend(block)
        after_open = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    after_path = path.lstat()
    if (
        {
            _file_identity(before),
            _file_identity(opened),
            _file_identity(after_open),
            _file_identity(after_path),
        }
        != {_file_identity(before)}
        or stat.S_ISLNK(after_path.st_mode)
        or _is_reparse_point(after_path)
        or not stat.S_ISREG(after_path.st_mode)
    ):
        raise ValueError(f"file identity changed during read: {path}")
    if len(data) > maximum:
        raise ValueError(f"file exceeds {maximum} bytes: {path}")
    return bytes(data)


def _sha256(path: Path, maximum: int = _MAX_PROJECT_SOURCE_BYTES) -> str:
    return hashlib.sha256(_read_regular_bounded(path, maximum)).hexdigest()


def _strict_json_bytes(data: bytes, label: str) -> dict:
    def reject_duplicates(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key in {label}: {key}")
            result[key] = value
        return result

    parsed = json.loads(
        data.decode("utf-8", errors="strict"),
        object_pairs_hook=reject_duplicates,
    )
    if not isinstance(parsed, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return parsed


def _stable_source_authority_proof(proof: dict) -> dict:
    """Keep freshness enforcement while removing its live clock value."""
    if not isinstance(proof, dict):
        raise ValueError("source-authority proof is not an object")
    stable = dict(proof)
    source_age_days = stable.pop("source_age_days", None)
    if source_age_days is not None and (
        isinstance(source_age_days, bool)
        or not isinstance(source_age_days, (int, float))
    ):
        raise ValueError("source-authority proof has an invalid source age")
    return stable


# Same boundaries as `.github/scripts/verify_repository_privacy.py`, and for the same reason:
# `\b` treats `_` as a WORD character, so `\bxx\b` never matches `xx_switch01` or `brand_dc_design`
# -- the exact spellings the working tree actually carried. That was fixed in the repository gate
# and NOT here, in the copy that scans the wheel and sdist about to be uploaded to PyPI. Two copies
# of one rule, one of them fixed: the release-facing scanner was the weaker of the pair.
# Divergence measured before this change (structural forms; 8 inputs the repo gate FLAGGED and this
# module MISSED): brand+'_dc_design', short+'_core01', initials+'_switch01', initials+'_vlan_plan',
# bid+'_bid', user+'_home', '_'+user.
#: Core-metadata fields a build backend may legitimately compute at wheel-build time, and therefore
#: the only values `Dynamic:` may name in a wheel this project ships. Deliberately NOT "anything the
#: spec permits": `Dynamic: Requires-Dist` is legal metadata but would mean the dependency set was
#: decided during the build rather than declared in pyproject, which this verifier exists to refuse.
#: `license-file` is here because setuptools collects the license documents itself (PEP 639 /
#: Metadata 2.4). Add to this set only with the same question answered: may the BACKEND decide it?
_BACKEND_COMPUTABLE_FIELDS = frozenset({"license-file"})

_LB = r"(?<![A-Za-z0-9])"
_RB = r"(?![A-Za-z0-9])"

# Mirrors the repository gate's carve-out (verify_repository_privacy.py, kept in lockstep by
# tests/test_repository_privacy.py::test_the_two_client_marker_implementations_cannot_diverge):
# minified bundles emit ALPHABETICAL two-char export aliases (ah, ai, then the initials, then
# ak, ...), so the bare initials pattern is structurally guaranteed to false-positive inside
# built bundle assets. ONLY that pattern is excluded, ONLY for dist/assets bundle members
# (prefix-tolerant because sdist members carry the release-root prefix); every other marker
# stays active on them. (The initials never appear literally in this file — the §12.9 rule.)
_BARE_INITIALS_MARKER = re.compile(_LB + re.escape("a" + "j") + _RB, re.IGNORECASE)
_MINIFIED_BUNDLE_ASSETS = re.compile(r"(^|/)webapp/frontend/dist/assets/[^/]+\.js$")


def _marker_patterns_for(name: str) -> tuple[re.Pattern[str], ...]:
    patterns = _client_marker_patterns()
    if _MINIFIED_BUNDLE_ASSETS.search(name):
        return tuple(p for p in patterns if p is not _BARE_INITIALS_MARKER)
    return patterns


def _client_marker_patterns() -> tuple[re.Pattern[str], ...]:
    legacy_brand = "al" + "jazeera"
    legacy_short = "a" + "jmn"
    legacy_initials = "a" + "j"
    side_bid = "al" + "waj"
    side_brand = "syn" + "tys"
    former_user = "jaj" + "ch"
    former_machine_user = "sooq" + r"\s+" + "elaser"
    return (
        re.compile(
            re.escape(legacy_brand[:2])
            + r"[\s-]*"
            + re.escape(legacy_brand[2:]),
            re.IGNORECASE,
        ),
        re.compile(_LB + re.escape(legacy_short) + _RB, re.IGNORECASE),
        re.compile(r"\." + re.escape(legacy_short) + _RB, re.IGNORECASE),
        _BARE_INITIALS_MARKER,
        re.compile(
            _LB
            + re.escape(legacy_initials)
            + r"(?:"
            + r"[\s_-]+(?:fleet|snapshots?|estate|engagement|collection|data|rows?|"
            + r"case|campus|shape|sdd|specific)"
            + r"|-(?:scale|style|verified|re-verified)"
            + r"|[._-](?:ftd|core|acc|assessment|local)"
            + r")(?![A-Za-z0-9])",
            re.IGNORECASE,
        ),
        re.compile(
            _LB + r"requirements\."
            + re.escape(legacy_initials)
            + r"\.json" + _RB,
            re.IGNORECASE,
        ),
        re.compile(
            _LB + r"canonical-"
            + re.escape(legacy_initials)
            + r"-fleet" + _RB,
            re.IGNORECASE,
        ),
        re.compile(_LB + re.escape(side_bid) + _RB, re.IGNORECASE),
        re.compile(_LB + re.escape(side_brand) + _RB, re.IGNORECASE),
        re.compile(_LB + r"q" + "ag" + _RB, re.IGNORECASE),
        re.compile(_LB + re.escape(former_user) + _RB, re.IGNORECASE),
        re.compile(_LB + former_machine_user + _RB, re.IGNORECASE),
    )


def _parse_known_hostname_hashes(data: bytes) -> set[str]:
    values = {
        line.strip().casefold()
        for line in data.decode("utf-8", errors="strict").splitlines()
        if line.strip() and not line.startswith("#")
    }
    if not values or any(
        not re.fullmatch(r"[0-9a-f]{64}", value) for value in values
    ):
        raise ValueError("client-hostname digest denylist is invalid")
    return values


def _validated_git_oid(value: str, label: str) -> str:
    candidate = value.strip()
    if not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", candidate):
        raise ValueError(
            f"{label} must be one complete lowercase SHA-1 or SHA-256 Git object id"
        )
    return candidate


def _git_output(root: Path, *arguments: str) -> str | None:
    """Run one local, read-only Git command under ``root``.

    ``None`` means the answer could not be obtained at all -- no Git executable,
    no repository, an unreadable ref, or output beyond the size bound.  It never
    means "fine": every caller has to report the missing measurement rather than
    fold it into a pass.  Nothing here touches the network, and
    ``--no-optional-locks`` keeps the command from rewriting the index.
    """
    try:
        completed = subprocess.run(
            ["git", "--no-optional-locks", "-C", str(root), *arguments],
            capture_output=True,
            timeout=_GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    if len(completed.stdout) > _MAX_GIT_OUTPUT_BYTES:
        return None
    try:
        return completed.stdout.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return None


def _same_directory(left: str, right: Path) -> bool:
    try:
        return os.path.normcase(os.path.realpath(left)) == os.path.normcase(
            os.path.realpath(right)
        )
    except (OSError, ValueError):
        return False


def _plural(count: int) -> str:
    return "y" if count == 1 else "ies"


def _member_prefix(name: str) -> str:
    return PurePosixPath(name).parent.as_posix()


def _is_build_generated(name: str) -> bool:
    """Was this archive member synthesised by the build backend?

    Structural, not a list of this project's paths: a generated metadata
    directory at the archive root (``*.dist-info`` in the wheel, ``*.egg-info``
    in the sdist), or one of the two top-level files PEP 517 backends generate.
    """
    parts = PurePosixPath(name).parts
    if not parts:
        return False
    if parts[0].endswith(_BUILD_GENERATED_DIRECTORY_SUFFIXES):
        return True
    return len(parts) == 1 and parts[0] in _BUILD_GENERATED_TOP_LEVEL_FILES


def _untracked_scan(root: Path, shipped: set[str]) -> dict:
    """Measure the SHIPPED paths the source binding structurally cannot see.

    ``git status --untracked-files=no`` and ``git ls-files`` answer only for
    tracked paths, so a file that no commit contains is invisible to both -- and
    the archives ship exactly such files.  This lists what git does not track,
    directory-collapsed so the answer stays bounded, and keeps only the entries
    that are, or contain, a member of the shipped set.

    That scope is the fix for a proof that was unstable by construction.  The
    scan previously kept every untracked entry under a shipped top-level
    directory, so ``cisco_toolkit/__pycache__``, ``build/lib``,
    ``webapp/frontend/node_modules`` and test scratch all landed in the emitted
    proof -- and ``--expected-json`` compares the whole proof, so an ordinary
    local build or test run made a re-verification fail for reasons that have
    nothing to do with the archives.  Bytecode caches and build trees are never
    shipped members and never contain one, so scoping to the shipped set removes
    the whole machine-churn CLASS rather than naming the directories it happens
    to use today.

    ``untracked_scan_measured`` is ``False`` when the listing could not be read
    at all; the counts are then ``null``, never ``0``.
    """
    unmeasured: dict = {
        "untracked_scan_measured": False,
        "untracked_entries_covering_shipped_members": None,
        "untracked_prefixes_total": None,
        "untracked_prefixes_covering_shipped_members": None,
    }
    listing = _git_output(
        root,
        "ls-files",
        "--others",
        "--directory",
        "--no-empty-directory",
        "-z",
    )
    if listing is None:
        return unmeasured
    shipped_directories = {
        parent.as_posix()
        for name in shipped
        for parent in PurePosixPath(name).parents
        if parent.as_posix() != "."
    }
    entries = 0
    prefixes: set[str] = set()
    for entry in listing.split("\0"):
        if not entry:
            continue
        if entry.endswith("/"):
            directory = entry.rstrip("/")
            # A collapsed directory counts when it holds any shipped member.
            if directory not in shipped_directories:
                continue
            prefixes.add(directory)
        else:
            if entry not in shipped:
                continue
            prefixes.add(_member_prefix(entry))
        entries += 1
    ordered = sorted(prefixes)
    return {
        "untracked_scan_measured": True,
        "untracked_entries_covering_shipped_members": entries,
        "untracked_prefixes_total": len(ordered),
        # Truncation is disclosed by the total above rather than silently applied.
        "untracked_prefixes_covering_shipped_members": ordered[
            :_UNTRACKED_PREFIX_SAMPLE
        ],
    }


def _shipped_coverage_proof(
    wheel_names: set[str],
    sdist_names: set[str],
    tracked: set[str] | None,
) -> dict:
    """Measure the source binding against the bytes that actually SHIP.

    The coverage set used to be the expected *runtime* inventory, which is
    essentially ``{COLLECT_PARSE_V3_23_0.py, cisco_toolkit/**}`` plus the built
    SPA -- the wheel's members.  The sdist ships more than that (packaging
    files, the retained official sources under ``reference-data/``, the
    generated metadata), so a large fraction of the shipped archive sat outside
    the denominator and the headline verdict could read true while those bytes
    were bound to nothing.  Measured on a probe release before this change: 13
    of 29 distinct shipped members were in no commit and none of them was in the
    coverage set.

    ``tracked`` is ``None`` when the tracked path set could not be measured; the
    counts are then ``null`` rather than zero, and ``fully_bound_to_source_binding``
    is ``False``, so a missing input fails closed.
    """
    shipped = set(wheel_names) | set(sdist_names)
    generated = {name for name in shipped if _is_build_generated(name)}
    proof: dict = {
        "coverage_basis": (
            "the member set of both shipped archives, wheel and sdist, "
            "de-duplicated by archive-relative path"
        ),
        "wheel_members_classified": len(wheel_names),
        "sdist_members_classified": len(sdist_names),
        "members_shipped_distinct": len(shipped),
        # Counted and disclosed, never removed from the denominator.
        "members_build_generated_unbindable": len(generated),
        "prefixes_build_generated_unbindable": sorted(
            {_member_prefix(name) for name in generated}
        ),
        "source_binding_coverage_measured": tracked is not None,
        "fully_bound_to_source_binding": False,
        "members_bound_to_source_binding": None,
        "members_outside_source_binding": None,
        "prefixes_outside_source_binding": None,
    }
    if tracked is None:
        return proof
    bindable = shipped - generated
    outside = sorted(name for name in bindable if name not in tracked)
    proof["members_bound_to_source_binding"] = len(bindable) - len(outside)
    proof["members_outside_source_binding"] = len(outside)
    proof["prefixes_outside_source_binding"] = sorted(
        {_member_prefix(name) for name in outside}
    )
    # An empty shipped set has nothing outside the commit only because it has
    # nothing in it; that is a measurement failure, not a bound release.
    proof["fully_bound_to_source_binding"] = bool(shipped) and not outside
    return proof


def _binding_scope_statements(binding: dict) -> tuple[list[str], list[str]]:
    """Say in the proof what this binding does and does not establish.

    Both lists are functions of what was actually observed, so neither is
    boilerplate: an unresolved binding establishes nothing, and the tautology
    disclosure appears only where a Git comparison really happened.
    """
    establishes: list[str] = []
    does_not: list[str] = []
    if binding["method"] == _SOURCE_BINDING_GIT:
        if binding["claim_matches_local_head"]:
            establishes.append(
                "the claimed commit and tree are HEAD of the local repository at "
                "the verification root, as reported by that repository"
            )
        if binding["worktree_tracked_files_match_claimed_commit"]:
            establishes.append(
                "every TRACKED file in that work tree is identical to the claimed "
                "commit, so the tracked half of the bytes that were verified is "
                "the content of that commit"
            )
        does_not.append(
            "that the claimed commit came from anywhere other than this work "
            "tree: it is compared against `git rev-parse HEAD` in the same tree "
            "the archives were built from, so a caller that derives the claim "
            "from this tree -- every caller in .github/workflows and "
            "RELEASING.md does -- is checking a value against its own source. "
            "Only a claim carried in from outside (a signed tag, a reviewer "
            "reading the commit id) makes this comparison evidence, and this "
            "module cannot tell which kind it was given"
        )
    else:
        does_not.append(
            "anything whatever about the claimed commit or tree: no local "
            "repository resolved them, so they are caller-supplied labels "
            "recorded verbatim"
        )
    # Permanent and independent of what was observed: no run of this module can
    # ever establish it, so it is stated on every run rather than only on a bad
    # one.  See _INDEPENDENCE_LIMIT and the module docstring.
    does_not.append(
        "that this release is bound to anything INDEPENDENT of the checkout "
        f"being verified -- {_INDEPENDENCE_LIMIT}"
    )
    if not binding["untracked_scan_measured"]:
        does_not.append(
            "which paths git does not track: the untracked listing could not be "
            "read, so the set outside the binding is NOT MEASURED, not empty"
        )
    elif binding["untracked_entries_covering_shipped_members"]:
        count = binding["untracked_entries_covering_shipped_members"]
        does_not.append(
            "that the untracked paths holding shipped archive members "
            f"correspond to any commit ({count} "
            f"entr{_plural(count)}, collapsed by directory; see "
            "untracked_prefixes_covering_shipped_members)"
        )
    if not binding["runtime_inventory_all_covered_by_claimed_commit"]:
        does_not.append(
            "that the expected runtime inventory is bound to the claimed "
            "commit; see "
            "measurements.runtime_inventory.members_outside_source_binding and "
            "prefixes_outside_source_binding for the uncovered set"
        )
    if not binding["shipped_archive_members_all_covered_by_claimed_commit"]:
        does_not.append(
            "that the bytes actually shipped are bound to the claimed commit; "
            "see measurements.shipped_bytes_coverage."
            "members_outside_source_binding and prefixes_outside_source_binding "
            "for the uncovered set, and members_build_generated_unbindable for "
            "the members no commit can contain"
        )
    return establishes, does_not


def _close_source_binding(
    binding: dict,
    root: Path,
    inventory: dict[str, str],
    tracked: set[str] | None,
    errors: list[str],
    shipped: tuple[set[str], set[str]],
) -> tuple[dict, list[str], dict, dict]:
    """Settle the headline verdict at every exit of ``_source_binding``.

    ``self_verified_against_this_worktree`` is the field a reader scans for, so
    it must not read true on a run that ships bytes bound to no commit.  It
    requires the claim to resolve, the tracked tree to be clean, *and* the member
    set of the two archives that actually ship to be fully covered by the tracked
    set -- and anything that could not be measured leaves it false rather than
    assuming the missing measurement was clean.

    The expected runtime inventory is still measured, but as a sub-measurement:
    it names the wheel's runtime members only, so deriving the headline from it
    left the sdist's packaging files and retained official sources bound to
    nothing while the headline read true.
    """
    wheel_names, sdist_names = shipped
    binding.update(_untracked_scan(root, set(wheel_names) | set(sdist_names)))
    inventory_proof = _runtime_inventory_proof(inventory, tracked)
    shipped_proof = _shipped_coverage_proof(wheel_names, sdist_names, tracked)
    binding["runtime_inventory_all_covered_by_claimed_commit"] = bool(
        inventory_proof["fully_bound_to_source_binding"]
    )
    binding["shipped_archive_members_all_covered_by_claimed_commit"] = bool(
        shipped_proof["fully_bound_to_source_binding"]
    )
    unmet: list[str] = []
    if binding["method"] != _SOURCE_BINDING_GIT:
        unmet.append("no local repository resolved the claim")
    elif not binding["claim_matches_local_head"]:
        unmet.append("the claim does not match this work tree's HEAD")
    if (
        binding["method"] == _SOURCE_BINDING_GIT
        and not binding["worktree_tracked_files_match_claimed_commit"]
    ):
        unmet.append("tracked working-tree files differ from the claimed commit")
    unmet.extend(
        _coverage_unmet(
            shipped_proof,
            measured_label="coverage of the shipped archive member set",
            empty_label=(
                "no archive member was classified, so nothing shipped was "
                "measured to be inside the claimed commit"
            ),
            population="members_shipped_distinct",
            outside_label="shipped archive member(s)",
        )
    )
    unmet.extend(
        _coverage_unmet(
            inventory_proof,
            measured_label="coverage of the expected runtime inventory",
            empty_label=(
                "the expected runtime inventory is empty, so no runtime member "
                "was measured to be inside the claimed commit"
            ),
            population="members_expected",
            outside_label="expected runtime member(s)",
        )
    )
    if not binding["untracked_scan_measured"]:
        unmet.append("the untracked path listing could not be read")
    binding["self_verified_against_this_worktree"] = not unmet and not errors
    if unmet:
        reason = "; ".join(unmet)
        binding["unverified_reason"] = (
            f"{binding['unverified_reason']}; {reason}"
            if binding["unverified_reason"]
            else reason
        )
    establishes, does_not = _binding_scope_statements(binding)
    binding["establishes"] = establishes
    binding["does_not_establish"] = does_not
    return binding, errors, inventory_proof, shipped_proof


def _coverage_unmet(
    proof: dict,
    *,
    measured_label: str,
    empty_label: str,
    population: str,
    outside_label: str,
) -> list[str]:
    """Say why a coverage measurement did not close, in words that match it.

    An empty population reports ``0`` members outside the commit and
    ``fully_bound_to_source_binding: False`` at the same time, both correctly.
    Rendering that as "0 member(s) are outside the claimed commit" produced a
    verdict of false beside a reason that reads like a pass; the empty case gets
    its own sentence instead.
    """
    if not proof["source_binding_coverage_measured"]:
        return [f"{measured_label} could not be measured"]
    if proof["fully_bound_to_source_binding"]:
        return []
    if not proof[population]:
        return [empty_label]
    return [
        f"{proof['members_outside_source_binding']} {outside_label} "
        "are outside the claimed commit"
    ]


def _source_binding(
    root: Path,
    commit: str,
    tree: str,
    inventory: dict[str, str],
    shipped: tuple[set[str], set[str]],
) -> tuple[dict, list[str], dict, dict]:
    """Bind -- or honestly decline to bind -- the verified tree to a commit.

    The archives are always compared against the *working tree* at ``root``.  The
    caller-supplied ``--source-commit`` / ``--source-tree`` are only a claim about
    which commit that working tree is.  This resolves the claim locally where a
    repository exists, and labels it unverified where one does not, because the
    same module is run against a downloaded archive with no repository present.

    What the resolution is and is not worth is recorded in the block itself
    (``establishes`` / ``does_not_establish``), because the comparison is against
    HEAD of the very tree the claim is usually derived from, and because git can
    only answer for tracked paths while part of what ships is untracked.

    ``shipped`` is ``(wheel member names, normalised sdist member names)`` -- the
    bytes that actually ship, which is what the headline verdict has to cover.

    Returns the proof block, hard errors (a claim proven false), the runtime
    inventory proof, and the shipped-bytes coverage proof, whose numbers decide
    the headline verdict.
    """
    binding: dict = {
        "claimed_commit": commit,
        "claimed_tree": tree,
        "method": _SOURCE_BINDING_UNVERIFIED,
        # Named for what it is.  A reader who scans only this field must not come
        # away believing an outside authority signed off on anything.
        "self_verified_against_this_worktree": False,
        "independent_of_the_verified_worktree": _INDEPENDENT_BINDING,
        "independence_limit": _INDEPENDENCE_LIMIT,
        "unverified_reason": "",
        "observed_head_commit": "",
        "observed_head_tree": "",
        "claim_matches_local_head": False,
        "worktree_tracked_files_match_claimed_commit": False,
        "shipped_archive_members_all_covered_by_claimed_commit": False,
        "runtime_inventory_all_covered_by_claimed_commit": False,
        "untracked_scan_measured": False,
        "untracked_entries_covering_shipped_members": None,
        "untracked_prefixes_total": None,
        "untracked_prefixes_covering_shipped_members": None,
        "exit_code_enforcement": _BINDING_ENFORCEMENT,
        "establishes": [],
        "does_not_establish": [],
    }
    toplevel = _git_output(root, "rev-parse", "--show-toplevel")
    if toplevel is None:
        binding["unverified_reason"] = (
            "no readable Git work tree at the verification root; the archives "
            "were compared against the working tree only, and the claimed "
            "commit and tree are unverified caller-supplied labels"
        )
        return _close_source_binding(
            binding, root, inventory, None, [], shipped
        )
    if not _same_directory(toplevel.strip(), root):
        binding["unverified_reason"] = (
            "the verification root is not the top of the Git work tree "
            f"({toplevel.strip()!r}); the claimed commit and tree are "
            "unverified caller-supplied labels"
        )
        return _close_source_binding(
            binding, root, inventory, None, [], shipped
        )
    head_commit = _git_output(root, "rev-parse", "HEAD^{commit}")
    head_tree = _git_output(root, "rev-parse", "HEAD^{tree}")
    if head_commit is None or head_tree is None:
        binding["unverified_reason"] = (
            "the Git work tree at the verification root has no readable HEAD "
            "commit; the claimed commit and tree are unverified caller-supplied "
            "labels"
        )
        return _close_source_binding(
            binding, root, inventory, None, [], shipped
        )

    binding["method"] = _SOURCE_BINDING_GIT
    binding["observed_head_commit"] = head_commit.strip()
    binding["observed_head_tree"] = head_tree.strip()
    errors: list[str] = []
    if binding["observed_head_commit"] != commit:
        errors.append(
            "claimed source commit is not this work tree's HEAD: "
            f"{binding['observed_head_commit']} != {commit}"
        )
    if binding["observed_head_tree"] != tree:
        errors.append(
            "claimed source tree is not this work tree's HEAD tree: "
            f"{binding['observed_head_tree']} != {tree}"
        )
    binding["claim_matches_local_head"] = not errors

    tracked: set[str] | None = None
    status = _git_output(root, "status", "--porcelain", "--untracked-files=no")
    if status is None:
        errors.append(
            "tracked working-tree status could not be read, so the claimed "
            "commit cannot bind the bytes that were actually verified"
        )
    else:
        dirty = sorted(line for line in status.splitlines() if line.strip())
        binding["worktree_tracked_files_match_claimed_commit"] = not dirty
        if dirty:
            shown = dirty[:_DIRTY_SAMPLE]
            errors.append(
                "tracked working-tree files differ from the claimed commit "
                f"({len(dirty)} entr{_plural(len(dirty))}, "
                f"showing {len(shown)}): " + json.dumps(shown)
            )
        listing = _git_output(root, "ls-files", "-z")
        if listing is not None:
            tracked = {entry for entry in listing.split("\0") if entry}

    if errors:
        binding["unverified_reason"] = (
            "the claimed source identity does not match this work tree"
        )
    return _close_source_binding(
        binding, root, inventory, tracked, errors, shipped
    )


_HOST_TOKEN = re.compile(
    r"(?<![A-Za-z0-9-])[A-Za-z0-9][A-Za-z0-9-]{2,}(?![A-Za-z0-9-])"
)


def _content_privacy_errors(
    name: str,
    data: bytes,
    known_hostname_hashes: set[str],
) -> tuple[list[str], bool]:
    """Return content-privacy errors and whether the payload was really scanned.

    The second element is ``False`` for exempt members.  Those bytes are never
    read for markers, so counting them as scanned would be the "not observed
    became healthy" failure this proof exists to prevent.
    """
    if name in _CONTENT_SCAN_EXEMPT:
        return [], False
    try:
        text = data.decode("utf-8", errors="strict").casefold()
    except UnicodeDecodeError:
        return [f"archive member is opaque binary content: {name}"], True
    if "\x00" in text:
        return [f"archive member is opaque binary content: {name}"], True
    if any(pattern.search(text) for pattern in _marker_patterns_for(name)):
        return [f"known client marker appears in archive content: {name}"], True
    if any(
        hashlib.sha256(token.group(0).casefold().encode("utf-8")).hexdigest()
        in known_hostname_hashes
        for token in _HOST_TOKEN.finditer(text)
    ):
        return [f"known private hostname appears in archive content: {name}"], True
    return [], True


def _sha256_stream(stream) -> str:
    digest = hashlib.sha256()
    for block in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(block)
    return digest.hexdigest()


def _expected_sdist_generated(project_name: str) -> set[str]:
    egg_info = re.sub(r"[-_.]+", "_", project_name).strip("_") + ".egg-info"
    return {
        "PKG-INFO",
        "setup.cfg",
        f"{egg_info}/PKG-INFO",
        f"{egg_info}/SOURCES.txt",
        f"{egg_info}/dependency_links.txt",
        f"{egg_info}/entry_points.txt",
        f"{egg_info}/requires.txt",
        f"{egg_info}/top_level.txt",
    }


def _archive_name_errors(names: list[str]) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    windows_seen: dict[str, str] = {}
    windows_prefixes: dict[tuple[str, ...], tuple[str, ...]] = {}
    for name in names:
        if name in seen:
            errors.append(f"duplicate member: {name}")
        seen.add(name)
        path = PurePosixPath(name)
        canonical_name = path.as_posix()
        unsafe_windows_part = any(
            ":" in part
            or part.endswith((" ", "."))
            or part.split(".", 1)[0].casefold() in _WINDOWS_RESERVED_NAMES
            for part in path.parts
        )
        if (
            not name
            or name.startswith(("/", "\\"))
            or "\\" in name
            or canonical_name != name
            or any(part in {"", ".", ".."} for part in path.parts)
            or unsafe_windows_part
        ):
            errors.append(f"unsafe member path: {name!r}")
        windows_key = unicodedata.normalize("NFC", canonical_name).casefold()
        prior = windows_seen.get(windows_key)
        if prior is not None and prior != name:
            errors.append(f"Windows-colliding members: {prior!r} and {name!r}")
        else:
            windows_seen[windows_key] = name
        for length in range(1, len(path.parts) + 1):
            raw_prefix = path.parts[:length]
            windows_prefix = tuple(
                unicodedata.normalize("NFC", part).casefold() for part in raw_prefix
            )
            prior_prefix = windows_prefixes.get(windows_prefix)
            if prior_prefix is not None and prior_prefix != raw_prefix:
                errors.append(
                    "Windows-colliding path components: "
                    f"{str(PurePosixPath(*prior_prefix))!r} and "
                    f"{str(PurePosixPath(*raw_prefix))!r}"
                )
            else:
                windows_prefixes[windows_prefix] = raw_prefix
    return errors


def _normalise_sdist(members: list[tarfile.TarInfo]) -> tuple[set[str], list[str]]:
    names = [member.name for member in members]
    errors = _archive_name_errors(names)
    roots = {PurePosixPath(name).parts[0] for name in names if PurePosixPath(name).parts}
    if len(roots) != 1:
        errors.append(f"sdist must have one top-level directory, found {sorted(roots)}")
        return set(), errors
    root = next(iter(roots))
    normalised: set[str] = set()
    for member in members:
        if member.issym() or member.islnk():
            errors.append(f"sdist link member is forbidden: {member.name}")
        elif not (member.isfile() or member.isdir()):
            errors.append(f"sdist special member is forbidden: {member.name}")
        if not member.isfile():
            continue
        parts = PurePosixPath(member.name).parts
        if parts and parts[0] == root and len(parts) > 1:
            normalised.add(PurePosixPath(*parts[1:]).as_posix())
    return normalised, errors


def _expected_runtime_inventory(root: Path) -> dict[str, str]:
    """Map every expected runtime member to how it came to be expected.

    Most of this set is discovered by globbing the working tree, which makes
    "expected" and "actual" the same measurement: a module deleted from the tree
    is simply never expected, and every file dropped into
    ``webapp/frontend/dist/assets`` becomes expected by existing.  Recording the
    provenance keeps the proof from presenting a self-derived set as a verified
    inventory -- see the ``runtime_inventory`` block of the emitted proof.
    """
    inventory: dict[str, str] = {}

    def record(name: str, provenance: str) -> None:
        # Externally constrained provenance always wins over a bare glob hit.
        if provenance == _PROVENANCE_WORKTREE and name in inventory:
            return
        if (
            provenance == _PROVENANCE_INDEX
            and inventory.get(name) == _PROVENANCE_REQUIRED
        ):
            return
        inventory[name] = provenance

    for relative in (
        "COLLECT_PARSE_V3_23_0.py",
        "cisco_toolkit/data/eol-bulletins.json",
        "cisco_toolkit/data/oui_registry.tsv.gz",
        "cisco_toolkit/data/port_registry.tsv.gz",
        "cisco_toolkit/data/registry_manifest.json",
        "cisco_toolkit/data/traffic-intents.example.json",
        "cisco_toolkit/blast_radius_explorer.html",
        "webapp/frontend/dist/index.html",
        "webapp/sample_data/sample_fleet.snapshot.json",
    ):
        record(relative, _PROVENANCE_REQUIRED)
    for path in (root / "cisco_toolkit").rglob("*.py"):
        record(path.relative_to(root).as_posix(), _PROVENANCE_WORKTREE)
    for path in (root / "webapp").glob("*.py"):
        record(path.relative_to(root).as_posix(), _PROVENANCE_WORKTREE)
    for path in (root / "webapp" / "backend").rglob("*.py"):
        record(path.relative_to(root).as_posix(), _PROVENANCE_WORKTREE)
    for path in (root / "webapp" / "frontend" / "dist" / "assets").glob("*"):
        if path.is_file():
            record(path.relative_to(root).as_posix(), _PROVENANCE_WORKTREE)
    index = root / "webapp" / "frontend" / "dist" / "index.html"
    try:
        index_data = _read_regular_bounded(index, _MAX_MEMBER_BYTES)
    except FileNotFoundError:
        index_data = None
    if index_data is not None:
        references, _ = _frontend_references(index_data)
        for reference in references:
            record(f"webapp/frontend/dist/{reference}", _PROVENANCE_INDEX)
    return inventory


def _runtime_inventory_proof(
    inventory: dict[str, str],
    tracked: set[str] | None,
) -> dict:
    """Describe how much of the expected runtime set is bound to anything.

    ``tracked`` is ``None`` when the tracked path set could not be measured; the
    coverage counts are then ``null`` rather than zero, because "not measured"
    must not read as "nothing outside the commit".  ``fully_bound_to_source_binding``
    is the verdict this feeds into
    ``source_binding.self_verified_against_this_worktree``; it is ``False``
    when coverage was not measured, so a missing input fails closed.
    """
    counts = Counter(inventory.values())
    proof: dict = {
        "members_expected": len(inventory),
        "required_by_verifier": counts.get(_PROVENANCE_REQUIRED, 0),
        "required_by_frontend_index": counts.get(_PROVENANCE_INDEX, 0),
        "self_derived_from_worktree_glob": counts.get(_PROVENANCE_WORKTREE, 0),
        "source_binding_coverage_measured": tracked is not None,
        "fully_bound_to_source_binding": False,
        "members_tracked_in_source_binding": None,
        "members_outside_source_binding": None,
        "prefixes_outside_source_binding": None,
    }
    if tracked is None:
        return proof
    outside = sorted(name for name in inventory if name not in tracked)
    proof["members_tracked_in_source_binding"] = len(inventory) - len(outside)
    proof["members_outside_source_binding"] = len(outside)
    proof["prefixes_outside_source_binding"] = sorted(
        {
            PurePosixPath(name).parent.as_posix()
            for name in outside
        }
    )
    # An empty inventory has nothing outside the commit only because it has
    # nothing in it; that is a measurement failure, not a bound release.
    proof["fully_bound_to_source_binding"] = bool(inventory) and not outside
    return proof


def _sdist_source_inventory_proof(
    expected_sdist_sources: set[str],
    runtime_inventory_proof: dict,
) -> dict:
    """Say how much of the sdist's EXPECTED set is self-derived.

    The sdist expected set is the runtime inventory plus two hardcoded groups
    (the packaging files and the retained official sources).  The runtime half is
    built by globbing ``cisco_toolkit/**/*.py``, ``webapp/**`` and the built SPA
    off disk, so for those members "expected" and "actual" are one measurement
    and their agreement is not a check.  Stating the split keeps the proof from
    presenting a tautology as a verified inventory.
    """
    self_derived = runtime_inventory_proof["self_derived_from_worktree_glob"]
    return {
        "members_expected": len(expected_sdist_sources),
        "self_derived_from_worktree_glob": self_derived,
        "externally_named_by_this_verifier": (
            len(expected_sdist_sources) - self_derived
        ),
        "self_derivation_note": (
            "self_derived_from_worktree_glob members are expected only because "
            "a glob found them on disk, so their presence in the archive proves "
            "agreement with this working tree and nothing more"
        ),
    }


def _privacy_violations(names: set[str], *, allow_sample_snapshot: bool = True) -> list[str]:
    violations: list[str] = []
    for name in sorted(names):
        path = PurePosixPath(name)
        if any(part in _FORBIDDEN_PARTS for part in path.parts):
            violations.append(name)
            continue
        lowered = name.lower()
        if lowered.endswith(_FORBIDDEN_SUFFIXES):
            violations.append(name)
            continue
        if lowered.endswith(".snapshot.json") and not (
            allow_sample_snapshot and name == "webapp/sample_data/sample_fleet.snapshot.json"
        ):
            violations.append(name)
    return violations


def _canonical_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).casefold()


def _canonical_marker(value: str) -> str:
    marker = value.strip().replace("'", '"')
    marker = re.sub(r"\s+", " ", marker)
    marker = re.sub(r"\s*(==|!=|<=|>=|~=|<|>)\s*", r" \1 ", marker)
    return marker.strip()


def _canonical_requirement(value: str) -> str:
    requirement, separator, marker = value.partition(";")
    match = re.fullmatch(
        r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)"
        r"(?:\[([A-Za-z0-9._,-]+)\])?"
        r"\s*(.*?)\s*",
        requirement,
    )
    if not match:
        raise ValueError(f"unsupported PEP 508 requirement: {value!r}")
    name = _canonical_name(match.group(1))
    extras = match.group(2)
    extra_text = ""
    if extras:
        normalised_extras = sorted(
            _canonical_name(item.strip()) for item in extras.split(",")
        )
        extra_text = f"[{','.join(normalised_extras)}]"
    specifier_text = match.group(3)
    specifiers: list[str] = []
    if specifier_text:
        for item in specifier_text.split(","):
            compact = re.sub(r"\s+", "", item)
            if not re.fullmatch(r"(?:===|==|!=|<=|>=|~=|<|>)[^\s,]+", compact):
                raise ValueError(
                    f"unsupported PEP 440 specifier in requirement: {value!r}"
                )
            specifiers.append(compact)
    canonical = name + extra_text + ",".join(sorted(specifiers))
    if separator:
        canonical += "; " + _canonical_marker(marker)
    return canonical


def _project_metadata_contract(root: Path) -> dict:
    pyproject_bytes = _read_regular_bounded(
        root / "pyproject.toml",
        _MAX_METADATA_BYTES,
    )
    try:
        document = tomllib.loads(pyproject_bytes.decode("utf-8", errors="strict"))
    except (UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"pyproject.toml is invalid: {exc}") from exc
    project = document.get("project")
    if not isinstance(project, dict):
        raise ValueError("pyproject.toml has no [project] table")
    if project.get("dynamic"):
        raise ValueError("dynamic project metadata is forbidden for releases")

    def scalar(name: str) -> str:
        value = project.get(name)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"pyproject.toml [project] has no scalar {name}")
        return value.strip()

    name = scalar("name")
    version = scalar("version")
    expected: dict[str, list[str]] = {
        "Name": [name],
        "Version": [version],
        "Summary": [scalar("description")],
        "Requires-Python": [scalar("requires-python")],
    }
    license_expression = project.get("license")
    if not isinstance(license_expression, str) or not license_expression.strip():
        raise ValueError("project.license must be a PEP 639 expression")
    expected["License-Expression"] = [license_expression.strip()]

    readme = project.get("readme")
    if not isinstance(readme, str) or not readme.strip():
        raise ValueError("project.readme must be one repository-relative path")
    readme_path = PurePosixPath(readme)
    if (
        readme_path.is_absolute()
        or any(part in {"", ".", ".."} for part in readme_path.parts)
    ):
        raise ValueError("project.readme path is unsafe")
    readme_bytes = _read_regular_bounded(
        root.joinpath(*readme_path.parts),
        _MAX_PROJECT_SOURCE_BYTES,
    )
    description = readme_bytes.decode("utf-8", errors="strict")
    content_types = {
        ".md": "text/markdown",
        ".rst": "text/x-rst",
        ".txt": "text/plain",
    }
    try:
        expected["Description-Content-Type"] = [
            content_types[readme_path.suffix.casefold()]
        ]
    except KeyError as exc:
        raise ValueError(f"unsupported project.readme suffix: {readme}") from exc

    keywords = project.get("keywords", [])
    if not isinstance(keywords, list) or any(
        not isinstance(item, str) or not item.strip() for item in keywords
    ):
        raise ValueError("project.keywords must be a list of non-empty strings")
    if keywords:
        expected["Keywords"] = [",".join(item.strip() for item in keywords)]

    authors = project.get("authors", [])
    if not isinstance(authors, list):
        raise ValueError("project.authors must be a list")
    author_names: list[str] = []
    author_emails: list[str] = []
    for author in authors:
        if not isinstance(author, dict):
            raise ValueError("project author records must be tables")
        author_name = author.get("name")
        author_email = author.get("email")
        if author_name is not None and not isinstance(author_name, str):
            raise ValueError("project author name must be text")
        if author_email is not None and not isinstance(author_email, str):
            raise ValueError("project author email must be text")
        if author_email:
            author_emails.append(
                f"{author_name} <{author_email}>" if author_name else author_email
            )
        elif author_name:
            author_names.append(author_name)
    if author_names:
        expected["Author"] = [", ".join(author_names)]
    if author_emails:
        expected["Author-email"] = [", ".join(author_emails)]

    classifiers = project.get("classifiers", [])
    if not isinstance(classifiers, list) or any(
        not isinstance(item, str) or not item.strip() for item in classifiers
    ):
        raise ValueError("project.classifiers must be a string list")
    if classifiers:
        expected["Classifier"] = [item.strip() for item in classifiers]

    urls = project.get("urls", {})
    if not isinstance(urls, dict) or any(
        not isinstance(label, str)
        or not isinstance(url, str)
        or not label.strip()
        or not url.strip()
        for label, url in urls.items()
    ):
        raise ValueError("project.urls must map non-empty text labels to URLs")
    if urls:
        expected["Project-URL"] = [
            f"{label}, {url}" for label, url in urls.items()
        ]

    license_files = project.get("license-files", [])
    if not isinstance(license_files, list) or any(
        not isinstance(item, str) or not item.strip() for item in license_files
    ):
        raise ValueError("project.license-files must be a string list")
    if license_files:
        expected["License-File"] = [item.strip() for item in license_files]

    dependencies = project.get("dependencies", [])
    if not isinstance(dependencies, list) or any(
        not isinstance(item, str) for item in dependencies
    ):
        raise ValueError("project.dependencies must be a string list")
    requires_dist = [_canonical_requirement(item) for item in dependencies]
    optional = project.get("optional-dependencies", {})
    if not isinstance(optional, dict):
        raise ValueError("project.optional-dependencies must be a table")
    provides_extra: list[str] = []
    for extra, requirements in optional.items():
        if (
            not isinstance(extra, str)
            or not isinstance(requirements, list)
            or any(not isinstance(item, str) for item in requirements)
        ):
            raise ValueError("optional dependency groups must be string lists")
        normalised_extra = _canonical_name(extra)
        provides_extra.append(normalised_extra)
        for requirement in requirements:
            canonical = _canonical_requirement(requirement)
            if ";" in canonical:
                base, marker = canonical.split(";", 1)
                canonical = (
                    f"{base}; {_canonical_marker(marker)} and "
                    f'extra == "{normalised_extra}"'
                )
            else:
                canonical += f'; extra == "{normalised_extra}"'
            requires_dist.append(canonical)
    if requires_dist:
        expected["Requires-Dist"] = requires_dist
    if provides_extra:
        expected["Provides-Extra"] = provides_extra

    scripts = project.get("scripts")
    if not isinstance(scripts, dict) or scripts != _EXPECTED_CONSOLE_SCRIPTS:
        raise ValueError("project.scripts differs from the release contract")
    return {
        "name": name,
        "version": version,
        "headers": expected,
        "description": description,
        "scripts": dict(scripts),
    }


def _metadata_signature(
    data: bytes,
    contract: dict,
    *,
    label: str,
) -> tuple[dict, list[str]]:
    errors: list[str] = []
    if len(data) > _MAX_METADATA_BYTES:
        return {}, [f"{label} exceeds the metadata byte limit"]
    try:
        message = BytesParser(policy=email_policy).parsebytes(data)
    except Exception as exc:  # email defects are reported, never trusted
        return {}, [f"{label} is unreadable: {exc}"]
    if message.defects:
        errors.append(f"{label} has parser defects: {message.defects!r}")
    values: dict[str, list[str]] = {}
    for header, value in message.raw_items():
        values.setdefault(header, []).append(str(value))
    for header in _METADATA_SINGLETONS:
        if len(values.get(header, [])) > 1:
            errors.append(f"{label} repeats singleton header {header}")
    metadata_versions = values.get("Metadata-Version", [])
    if metadata_versions != ["2.4"]:
        errors.append(
            f"{label} Metadata-Version differs: {metadata_versions!r} != ['2.4']"
        )
    expected_headers: dict[str, list[str]] = contract["headers"]
    # `Dynamic` is emitted by the BUILD BACKEND, not declared in pyproject, so it can never appear in
    # the contract derived from it -- yet it is standard and correct here. Core metadata spec: "In any
    # context other than a source distribution, `Dynamic` is for information only, and indicates that
    # the field value was calculated at wheel build time" (PEP 643, Metadata 2.2; `License-File` is
    # 2.4). setuptools 84.0.0 emits `Dynamic: license-file` for a 2.4 wheel whose License-File it
    # computed -- and 84.0.0 is the version THIS MODULE PINS via the Generator check, so rejecting it
    # made the verifier refuse its own pinned backend's output. Found by building for real: every
    # other check passed and this alone failed the release gate.
    #
    # Allowed as a NAME, still constrained by VALUE: each entry must name a field the backend may
    # legitimately compute, so this cannot become a hole through which arbitrary metadata rides in.
    # Widening `expected_names` alone would have been the lazy fix and would have accepted
    # `Dynamic: Requires-Dist`, which would mean the dependency set was decided at build time.
    expected_names = set(expected_headers) | {"Metadata-Version", "Dynamic"}
    dynamic_declared = [v.strip().lower() for v in values.get("Dynamic", [])]
    illegal_dynamic = sorted(set(dynamic_declared) - _BACKEND_COMPUTABLE_FIELDS)
    if illegal_dynamic:
        errors.append(
            f"{label} declares Dynamic for field(s) the backend must not compute: {illegal_dynamic}"
        )
    unexpected = sorted(set(values) - expected_names)
    missing = sorted(set(expected_headers) - set(values))
    if unexpected:
        errors.append(f"{label} has unexpected metadata headers: {unexpected}")
    if missing:
        errors.append(f"{label} is missing metadata headers: {missing}")

    signature: dict[str, list[str] | str] = {
        "Metadata-Version": metadata_versions,
    }
    for header, expected_values in expected_headers.items():
        actual_values = values.get(header, [])
        try:
            if header == "Requires-Dist":
                actual_normalised = [
                    _canonical_requirement(item) for item in actual_values
                ]
                expected_normalised = [
                    _canonical_requirement(item) for item in expected_values
                ]
            elif header == "Provides-Extra":
                actual_normalised = [
                    _canonical_name(item) for item in actual_values
                ]
                expected_normalised = [
                    _canonical_name(item) for item in expected_values
                ]
            elif header == "Keywords":
                actual_normalised = [
                    ",".join(
                        part.strip()
                        for part in actual_values[0].split(",")
                    )
                ] if actual_values else []
                expected_normalised = expected_values
            else:
                actual_normalised = actual_values
                expected_normalised = expected_values
        except ValueError as exc:
            errors.append(f"{label} {header} is invalid: {exc}")
            actual_normalised = actual_values
            expected_normalised = expected_values
        if Counter(actual_normalised) != Counter(expected_normalised):
            errors.append(
                f"{label} {header} differs: "
                f"{actual_normalised!r} != {expected_normalised!r}"
            )
        signature[header] = sorted(actual_normalised)

    payload_bytes = message.get_payload(decode=True)
    try:
        actual_description = (
            payload_bytes.decode("utf-8", errors="strict")
            if isinstance(payload_bytes, bytes)
            else str(message.get_payload())
        )
    except UnicodeDecodeError as exc:
        errors.append(f"{label} long description is not UTF-8: {exc}")
        actual_description = ""
    actual_description = actual_description.replace("\r\n", "\n").rstrip("\n")
    expected_description = contract["description"].replace("\r\n", "\n").rstrip("\n")
    if actual_description != expected_description:
        errors.append(f"{label} long description differs from project.readme")
    signature["description"] = actual_description
    return signature, errors


def _zip_preflight(infos: list[zipfile.ZipInfo]) -> list[str]:
    errors: list[str] = []
    if len(infos) > _MAX_ARCHIVE_MEMBERS:
        errors.append(
            f"wheel has {len(infos)} members; limit is {_MAX_ARCHIVE_MEMBERS}"
        )
    total = 0
    for info in infos:
        if info.flag_bits & 0x1:
            errors.append(f"wheel encrypted member is forbidden: {info.filename}")
        if info.file_size < 0 or info.compress_size < 0:
            errors.append(f"wheel member has an invalid size: {info.filename}")
            continue
        if info.file_size > _MAX_MEMBER_BYTES:
            errors.append(
                f"wheel member exceeds {_MAX_MEMBER_BYTES} bytes: {info.filename}"
            )
        total += info.file_size
        mode = info.external_attr >> 16
        if stat.S_ISLNK(mode):
            errors.append(f"wheel symlink member is forbidden: {info.filename}")
        elif mode and stat.S_IFMT(mode) not in {
            0,
            stat.S_IFREG,
            stat.S_IFDIR,
        }:
            errors.append(f"wheel special member is forbidden: {info.filename}")
    if total > _MAX_ARCHIVE_UNCOMPRESSED_BYTES:
        errors.append(
            "wheel uncompressed bytes exceed "
            f"{_MAX_ARCHIVE_UNCOMPRESSED_BYTES}"
        )
    return errors


def _zip_container_errors(data: bytes) -> list[str]:
    """Reject multi-disk/ZIP64/count bombs before ZipFile loads the directory."""
    signature = b"PK\x05\x06"
    minimum = 22
    search_start = max(0, len(data) - minimum - 65_535)
    position = len(data)
    record = None
    while True:
        position = data.rfind(signature, search_start, position)
        if position < 0:
            break
        if position + minimum <= len(data):
            candidate = struct.unpack_from("<4s4H2LH", data, position)
            comment_length = candidate[-1]
            if position + minimum + comment_length == len(data):
                record = candidate
                break
        if position == 0:
            break
    if record is None:
        return ["wheel has no terminal ZIP end-of-central-directory record"]

    (
        _,
        disk_number,
        directory_disk,
        entries_on_disk,
        total_entries,
        directory_bytes,
        directory_offset,
        _,
    ) = record
    errors: list[str] = []
    if disk_number != 0 or directory_disk != 0:
        errors.append("wheel multi-disk ZIP containers are forbidden")
    if entries_on_disk != total_entries:
        errors.append("wheel central-directory member counts disagree")
    if (
        total_entries == 0xFFFF
        or directory_bytes == 0xFFFFFFFF
        or directory_offset == 0xFFFFFFFF
    ):
        errors.append("wheel ZIP64 containers are forbidden")
    elif total_entries > _MAX_ARCHIVE_MEMBERS:
        errors.append(
            f"wheel declares {total_entries} members; "
            f"limit is {_MAX_ARCHIVE_MEMBERS}"
        )
    if directory_offset + directory_bytes != position:
        errors.append("wheel central-directory bounds are inconsistent")
    return errors


def _zip_read(
    archive: zipfile.ZipFile,
    info_by_name: dict[str, zipfile.ZipInfo],
    name: str,
    maximum: int = _MAX_MEMBER_BYTES,
) -> bytes:
    info = info_by_name[name]
    if info.file_size > maximum:
        raise ValueError(f"wheel member exceeds {maximum} bytes: {name}")
    data = archive.read(info)
    if len(data) != info.file_size:
        raise ValueError(f"wheel member size changed while reading: {name}")
    return data


def _tar_preflight(members: list[tarfile.TarInfo]) -> list[str]:
    errors: list[str] = []
    if len(members) > _MAX_ARCHIVE_MEMBERS:
        errors.append(
            f"sdist has {len(members)} members; limit is {_MAX_ARCHIVE_MEMBERS}"
        )
    total = 0
    for member in members:
        if member.size < 0:
            errors.append(f"sdist member has a negative size: {member.name}")
            continue
        if member.isfile():
            if member.size > _MAX_MEMBER_BYTES:
                errors.append(
                    f"sdist member exceeds {_MAX_MEMBER_BYTES} bytes: {member.name}"
                )
            total += member.size
    if total > _MAX_ARCHIVE_UNCOMPRESSED_BYTES:
        errors.append(
            "sdist uncompressed bytes exceed "
            f"{_MAX_ARCHIVE_UNCOMPRESSED_BYTES}"
        )
    return errors


def _tar_read(
    archive: tarfile.TarFile,
    member: tarfile.TarInfo,
    maximum: int = _MAX_MEMBER_BYTES,
) -> bytes:
    if not member.isfile():
        raise ValueError(f"sdist member is not a regular file: {member.name}")
    if member.size > maximum:
        raise ValueError(f"sdist member exceeds {maximum} bytes: {member.name}")
    stream = archive.extractfile(member)
    if stream is None:
        raise ValueError(f"sdist member is unreadable: {member.name}")
    with stream:
        data = stream.read(maximum + 1)
    if len(data) != member.size:
        raise ValueError(f"sdist member size changed while reading: {member.name}")
    return data


def _verify_wheel_record(
    archive: zipfile.ZipFile,
    info_by_name: dict[str, zipfile.ZipInfo],
    wheel_names: set[str],
    metadata_dir: str,
) -> tuple[list[str], dict]:
    """Verify the wheel RECORD, reporting how many members were really hashed.

    The counts are the measurement: rows that could not be read, or that RECORD
    never named, are not hashed, and a proof that says only ``true`` cannot
    distinguish a fully hashed wheel from one where nothing was hashed at all.

    The hashed count alone is still uninformative on an accepted wheel, because
    RECORD correctly does not hash itself, so the count is always the member
    total minus that one row.  The block therefore names the exemption and
    reports the remainder explicitly: ``members_neither_hashed_nor_exempt`` is
    the field that says something, and it is the count of members this pass left
    unhashed for any other reason.
    """
    errors: list[str] = []
    hashed = 0
    exempt = 0
    record_name = f"{metadata_dir}/RECORD"

    def measurement() -> dict:
        return {
            "members_total": len(wheel_names),
            "members_hashed": hashed,
            "members_exempt_record_self_reference": exempt,
            "members_neither_hashed_nor_exempt": len(wheel_names) - hashed - exempt,
        }

    if record_name not in wheel_names:
        return [f"wheel has no {record_name}"], measurement()
    try:
        rows = list(
            csv.reader(
                io.StringIO(
                    _zip_read(
                        archive,
                        info_by_name,
                        record_name,
                        _MAX_METADATA_BYTES,
                    ).decode("utf-8")
                ),
                strict=True,
            )
        )
    except (UnicodeDecodeError, csv.Error, ValueError) as exc:
        return [f"wheel RECORD is unreadable: {exc}"], measurement()

    recorded: set[str] = set()
    for row in rows:
        if len(row) != 3:
            errors.append(f"wheel RECORD row does not have three fields: {row!r}")
            continue
        name, encoded_hash, encoded_size = row
        if name in recorded:
            errors.append(f"wheel RECORD repeats {name}")
            continue
        recorded.add(name)
        if name not in wheel_names:
            errors.append(f"wheel RECORD names missing member {name}")
            continue
        if name == record_name:
            if encoded_hash or encoded_size:
                errors.append("wheel RECORD must not hash itself")
            else:
                exempt += 1
            continue
        try:
            data = _zip_read(archive, info_by_name, name)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if encoded_size != str(len(data)):
            errors.append(
                f"wheel RECORD size mismatch for {name}: {encoded_size!r} != {len(data)}"
            )
        if not encoded_hash.startswith("sha256="):
            errors.append(f"wheel RECORD lacks a sha256 hash for {name}")
            continue
        expected = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
        if encoded_hash[7:] != expected:
            errors.append(f"wheel RECORD sha256 mismatch for {name}")
        else:
            hashed += 1
    missing = sorted(wheel_names - recorded)
    if missing:
        errors.append(f"wheel RECORD omits members: {missing}")
    return errors, measurement()


def _top_level_declaration_errors(lines: list[str], label: str) -> list[str]:
    """Check one top_level.txt against the import roots this project installs.

    Shared by the sdist's egg-info copy and the wheel's dist-info copy so the two
    cannot drift: the wheel's copy was previously allowlisted by name and never
    read at all.
    """
    declared = set(lines)
    errors: list[str] = []
    if len(lines) != len(declared):
        errors.append(f"{label} top_level.txt repeats a package name")
    if declared != set(_EXPECTED_TOP_LEVEL_PACKAGES):
        errors.append(
            f"{label} top_level.txt differs: "
            f"{sorted(declared)} != {sorted(_EXPECTED_TOP_LEVEL_PACKAGES)}"
        )
    return errors


def _verify_wheel_metadata(
    archive: zipfile.ZipFile,
    info_by_name: dict[str, zipfile.ZipInfo],
    wheel_names: set[str],
    metadata_dir: str,
    contract: dict,
) -> tuple[list[str], dict]:
    errors: list[str] = []
    metadata_name = f"{metadata_dir}/METADATA"
    entry_name = f"{metadata_dir}/entry_points.txt"
    wheel_name = f"{metadata_dir}/WHEEL"
    top_level_name = f"{metadata_dir}/top_level.txt"
    for required in (metadata_name, entry_name, wheel_name, top_level_name):
        if required not in wheel_names:
            errors.append(f"wheel has no {required}")
    if errors:
        return errors, {}

    try:
        metadata_data = _zip_read(
            archive,
            info_by_name,
            metadata_name,
            _MAX_METADATA_BYTES,
        )
        signature, metadata_errors = _metadata_signature(
            metadata_data,
            contract,
            label="wheel METADATA",
        )
        errors.extend(metadata_errors)
    except ValueError as exc:
        signature = {}
        errors.append(str(exc))

    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read_string(
            _zip_read(
                archive,
                info_by_name,
                entry_name,
                _MAX_METADATA_BYTES,
            ).decode("utf-8")
        )
    except (UnicodeDecodeError, configparser.Error, ValueError) as exc:
        errors.append(f"wheel entry_points.txt is unreadable: {exc}")
        return errors, signature
    actual = dict(parser.items("console_scripts")) if parser.has_section("console_scripts") else {}
    if set(parser.sections()) != {"console_scripts"} or parser.defaults():
        errors.append(
            "wheel entry_points.txt contains unexpected sections or defaults"
        )
    if actual != _EXPECTED_CONSOLE_SCRIPTS:
        errors.append(
            "wheel console scripts differ: "
            + json.dumps(
                {"expected": _EXPECTED_CONSOLE_SCRIPTS, "actual": actual},
                sort_keys=True,
            )
        )

    try:
        top_level_lines = [
            line.strip()
            for line in _zip_read(
                archive,
                info_by_name,
                top_level_name,
                _MAX_METADATA_BYTES,
            ).decode("utf-8", errors="strict").splitlines()
            if line.strip()
        ]
    except (UnicodeDecodeError, ValueError) as exc:
        errors.append(f"wheel top_level.txt is unreadable: {exc}")
    else:
        errors.extend(_top_level_declaration_errors(top_level_lines, "wheel"))

    try:
        wheel_metadata = BytesParser(policy=email_policy).parsebytes(
            _zip_read(
                archive,
                info_by_name,
                wheel_name,
                _MAX_METADATA_BYTES,
            )
        )
        if wheel_metadata.defects:
            errors.append(
                f"wheel WHEEL has parser defects: {wheel_metadata.defects!r}"
            )
        wheel_values: dict[str, list[str]] = {}
        for header, value in wheel_metadata.raw_items():
            wheel_values.setdefault(header, []).append(str(value))
        for singleton in (
            "Wheel-Version",
            "Generator",
            "Root-Is-Purelib",
        ):
            if len(wheel_values.get(singleton, [])) != 1:
                errors.append(
                    f"wheel WHEEL must contain exactly one {singleton} header"
                )
        if wheel_values.get("Wheel-Version") != ["1.0"]:
            errors.append("wheel WHEEL has an unsupported Wheel-Version")
        if wheel_values.get("Generator") != ["setuptools (84.0.0)"]:
            errors.append("wheel WHEEL Generator is not the pinned build backend")
        if wheel_values.get("Root-Is-Purelib") != ["true"]:
            errors.append("wheel WHEEL must be purelib")
        if wheel_values.get("Tag") != ["py3-none-any"]:
            errors.append("wheel WHEEL tag must be exactly py3-none-any")
        if set(wheel_values) != {
            "Wheel-Version",
            "Generator",
            "Root-Is-Purelib",
            "Tag",
        }:
            errors.append(
                "wheel WHEEL contains unexpected headers: "
                f"{sorted(set(wheel_values) - {'Wheel-Version', 'Generator', 'Root-Is-Purelib', 'Tag'})}"
            )
    except ValueError as exc:
        errors.append(str(exc))
    return errors, signature


def _requires_txt_values(data: bytes) -> list[str]:
    try:
        lines = data.decode("utf-8", errors="strict").splitlines()
    except UnicodeDecodeError as exc:
        raise ValueError(f"sdist requires.txt is not UTF-8: {exc}") from exc
    result: list[str] = []
    extra: str | None = None
    section_marker: str | None = None
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            if not section:
                raise ValueError(
                    f"unsupported sdist requires.txt section: {line!r}"
                )
            if ":" in section:
                raw_extra, raw_marker = section.split(":", 1)
                raw_extra = raw_extra.strip()
                raw_marker = raw_marker.strip()
                if not raw_marker:
                    raise ValueError(
                        f"unsupported sdist requires.txt section: {line!r}"
                    )
                extra = _canonical_name(raw_extra) if raw_extra else None
                section_marker = _canonical_marker(raw_marker)
            else:
                extra = _canonical_name(section)
                section_marker = None
            continue
        requirement = _canonical_requirement(line)
        base, separator, requirement_marker = requirement.partition(";")
        markers: list[str] = []
        if separator:
            markers.append(_canonical_marker(requirement_marker))
        if section_marker:
            markers.append(section_marker)
        if extra:
            markers.append(f'extra == "{extra}"')
        if markers:
            requirement = f"{base}; {' and '.join(markers)}"
        result.append(requirement)
    return result


def _generated_setup_cfg_errors(data: bytes) -> list[str]:
    """Validate the version-tag config setuptools adds to every sdist."""
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read_string(data.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, configparser.Error) as exc:
        return [f"sdist generated setup.cfg is unreadable: {exc}"]
    if parser.defaults() or set(parser.sections()) != {"egg_info"}:
        return [
            "sdist generated setup.cfg contains unexpected sections or defaults"
        ]
    actual = dict(parser.items("egg_info", raw=True))
    expected = {"tag_build": "", "tag_date": "0"}
    if actual != expected:
        return [
            "sdist generated setup.cfg differs from setuptools defaults: "
            f"{actual!r} != {expected!r}"
        ]
    return []


def _verify_sdist_metadata(
    archive: tarfile.TarFile,
    members: dict[str, tarfile.TarInfo],
    sdist_names: set[str],
    contract: dict,
    wheel_signature: dict,
) -> tuple[list[str], dict]:
    """Verify sdist metadata, reporting how much equivalence was really checked.

    ``cross_checked_against_wheel_metadata`` is 0 whenever the wheel signature
    could not be built, which is exactly the case a hardcoded
    ``metadata_equivalence_verified: true`` used to hide.
    """
    errors: list[str] = []
    cross_checked = 0
    egg_info = (
        re.sub(r"[-_.]+", "_", contract["name"]).strip("_") + ".egg-info"
    )
    metadata_names = [
        "PKG-INFO",
        f"{egg_info}/PKG-INFO",
    ]
    signatures: list[tuple[str, dict]] = []
    for name in metadata_names:
        member = members.get(name)
        if member is None:
            errors.append(f"sdist has no {name}")
            continue
        try:
            signature, metadata_errors = _metadata_signature(
                _tar_read(archive, member, _MAX_METADATA_BYTES),
                contract,
                label=f"sdist {name}",
            )
        except ValueError as exc:
            errors.append(str(exc))
            continue
        errors.extend(metadata_errors)
        signatures.append((name, signature))
        if wheel_signature:
            cross_checked += 1
            if signature != wheel_signature:
                errors.append(f"sdist {name} metadata differs from wheel METADATA")
    if len(signatures) == 2 and signatures[0][1] != signatures[1][1]:
        errors.append("sdist root and egg-info PKG-INFO metadata differ")

    entry_name = f"{egg_info}/entry_points.txt"
    entry = members.get(entry_name)
    if entry is None:
        errors.append(f"sdist has no {entry_name}")
    else:
        parser = configparser.ConfigParser(interpolation=None)
        try:
            parser.read_string(
                _tar_read(archive, entry, _MAX_METADATA_BYTES).decode("utf-8")
            )
            actual = (
                dict(parser.items("console_scripts"))
                if parser.has_section("console_scripts")
                else {}
            )
        except (UnicodeDecodeError, configparser.Error, ValueError) as exc:
            errors.append(f"sdist entry_points.txt is unreadable: {exc}")
        else:
            if set(parser.sections()) != {"console_scripts"} or parser.defaults():
                errors.append(
                    "sdist entry_points.txt contains unexpected sections or defaults"
                )
            if actual != _EXPECTED_CONSOLE_SCRIPTS:
                errors.append(
                    "sdist console scripts differ: "
                    + json.dumps(
                        {
                            "expected": _EXPECTED_CONSOLE_SCRIPTS,
                            "actual": actual,
                        },
                        sort_keys=True,
                    )
                )

    requires_name = f"{egg_info}/requires.txt"
    requires = members.get(requires_name)
    if requires is None:
        errors.append(f"sdist has no {requires_name}")
    else:
        try:
            actual_requires = _requires_txt_values(
                _tar_read(archive, requires, _MAX_METADATA_BYTES)
            )
            expected_requires = [
                _canonical_requirement(item)
                for item in contract["headers"].get("Requires-Dist", [])
            ]
            if Counter(actual_requires) != Counter(expected_requires):
                errors.append(
                    "sdist requires.txt differs from project.dependencies: "
                    f"{actual_requires!r} != {expected_requires!r}"
                )
        except ValueError as exc:
            errors.append(str(exc))

    top_level_name = f"{egg_info}/top_level.txt"
    top_level = members.get(top_level_name)
    if top_level is None:
        errors.append(f"sdist has no {top_level_name}")
    else:
        try:
            top_level_lines = [
                line.strip()
                for line in _tar_read(
                    archive,
                    top_level,
                    _MAX_METADATA_BYTES,
                ).decode("utf-8", errors="strict").splitlines()
                if line.strip()
            ]
        except (UnicodeDecodeError, ValueError) as exc:
            errors.append(f"sdist top_level.txt is unreadable: {exc}")
        else:
            errors.extend(
                _top_level_declaration_errors(top_level_lines, "sdist")
            )

    sources_name = f"{egg_info}/SOURCES.txt"
    sources = members.get(sources_name)
    if sources is None:
        errors.append(f"sdist has no {sources_name}")
    else:
        try:
            source_lines = [
                line.strip().replace("\\", "/")
                for line in _tar_read(
                    archive,
                    sources,
                    _MAX_METADATA_BYTES,
                ).decode("utf-8", errors="strict").splitlines()
                if line.strip()
            ]
            source_inventory = set(source_lines)
        except (UnicodeDecodeError, ValueError) as exc:
            errors.append(f"sdist SOURCES.txt is unreadable: {exc}")
        else:
            if len(source_lines) != len(source_inventory):
                errors.append("sdist SOURCES.txt repeats a source path")
            generated_after_manifest = {"PKG-INFO", "setup.cfg"}
            if source_inventory != sdist_names - generated_after_manifest:
                errors.append(
                    "sdist SOURCES.txt does not equal archive inventory "
                    "before setuptools-generated root metadata"
                )

    setup_cfg = members.get("setup.cfg")
    if setup_cfg is None:
        errors.append("sdist has no generated setup.cfg")
    else:
        try:
            setup_cfg_data = _tar_read(
                archive,
                setup_cfg,
                _MAX_METADATA_BYTES,
            )
        except ValueError as exc:
            errors.append(str(exc))
        else:
            errors.extend(_generated_setup_cfg_errors(setup_cfg_data))

    dependency_links_name = f"{egg_info}/dependency_links.txt"
    dependency_links = members.get(dependency_links_name)
    if dependency_links is None:
        errors.append(f"sdist has no {dependency_links_name}")
    else:
        try:
            if _tar_read(
                archive,
                dependency_links,
                _MAX_METADATA_BYTES,
            ).strip():
                errors.append("sdist dependency_links.txt must be empty")
        except ValueError as exc:
            errors.append(str(exc))
    return errors, {
        "pkg_info_documents_parsed": len(signatures),
        "cross_checked_against_wheel_metadata": cross_checked,
    }


def verify_archives(
    dist_dir: str | os.PathLike[str],
    root: str | os.PathLike[str] = ".",
    *,
    source_commit: str,
    source_tree: str,
) -> dict:
    dist = Path(dist_dir).resolve()
    project_root = Path(root).resolve()
    claimed_source_commit = _validated_git_oid(source_commit, "source commit")
    claimed_source_tree = _validated_git_oid(source_tree, "source tree")
    # The inventory drives what is read off disk and compared byte for byte.  The
    # source binding is NOT settled here: its headline verdict has to cover the
    # member set of the archives that actually ship, which is not known until both
    # archives have been opened, so `_source_binding` is called once below with
    # those member sets in hand.
    runtime_inventory = _expected_runtime_inventory(project_root)
    wheels = sorted(dist.glob("*.whl"))
    sdists = sorted(dist.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        raise ValueError(
            f"expected exactly one wheel and one sdist, found {len(wheels)} wheel(s) "
            f"and {len(sdists)} sdist(s)"
        )

    contract: dict = {
        "name": "",
        "version": "",
        "headers": {},
        "description": "",
    }
    project_contract_errors: list[str] = []
    known_hostname_payload = b""
    try:
        contract = _project_metadata_contract(project_root)
        known_hostname_payload = _read_regular_bounded(
            project_root.joinpath(*_KNOWN_HOST_HASHES.parts),
            _MAX_METADATA_BYTES,
        )
        known_hostname_hashes = _parse_known_hostname_hashes(
            known_hostname_payload
        )
    except (OSError, UnicodeError, ValueError) as exc:
        project_contract_errors.append(str(exc))
        known_hostname_hashes = set()
    project_name = contract["name"]
    project_version = contract["version"]

    expected_runtime = set(runtime_inventory)
    expected_sdist_sources = (
        expected_runtime
        | _SDIST_SOURCE_FILES
        | _OFFICIAL_SOURCE_FILES
    )
    source_payloads: dict[str, bytes] = {}
    missing_project_sources: list[str] = []
    project_source_errors: list[str] = []
    source_total = 0
    for name in sorted(expected_sdist_sources):
        source = project_root.joinpath(*PurePosixPath(name).parts)
        try:
            payload = _read_regular_bounded(
                source,
                _MAX_PROJECT_SOURCE_BYTES,
            )
        except FileNotFoundError:
            missing_project_sources.append(name)
            continue
        except (OSError, ValueError) as exc:
            project_source_errors.append(f"{name}: {exc}")
            continue
        source_total += len(payload)
        if source_total > _MAX_PROJECT_TOTAL_BYTES:
            project_source_errors.append(
                "project source bytes exceed "
                f"{_MAX_PROJECT_TOTAL_BYTES}"
            )
            break
        source_payloads[name] = payload

    registry_source_chain_errors: list[str] = []
    registry_source_chains: dict[str, dict] = {}
    for pack_name in ("oui_registry.tsv.gz", "port_registry.tsv.gz"):
        pack_path = project_root / "cisco_toolkit" / "data" / pack_name
        try:
            source_chain = _stable_source_authority_proof(
                verify_retained_source_chain(
                    str(pack_path),
                    repository_root=project_root,
                )
            )
            registry_source_chains[pack_name] = source_chain
        except (OSError, ValueError, PackIntegrityError) as exc:
            registry_source_chain_errors.append(f"{pack_name}: {exc}")
    eol_source_chain: dict = {}
    eol_source_chain_errors: list[str] = []
    try:
        eol_source_chain = _stable_source_authority_proof(
            verify_retained_eol_source_chain(
                repository_root=project_root,
            )
        )
    except (OSError, ValueError, PackIntegrityError) as exc:
        eol_source_chain_errors.append(str(exc))

    expected_wheel_name = (
        f"{re.sub(r'[-.]+', '_', project_name)}-"
        f"{project_version}-py3-none-any.whl"
    )
    expected_sdist_name = (
        f"{re.sub(r'[-.]+', '_', project_name)}-{project_version}.tar.gz"
    )
    archive_filename_errors: list[str] = []
    if project_name and wheels[0].name != expected_wheel_name:
        archive_filename_errors.append(
            f"wheel filename {wheels[0].name!r} != {expected_wheel_name!r}"
        )
    if project_name and sdists[0].name != expected_sdist_name:
        archive_filename_errors.append(
            f"sdist filename {sdists[0].name!r} != {expected_sdist_name!r}"
        )

    wheel_names: set[str] = set()
    metadata_dirs: list[str] = []
    wheel_structure: list[str] = []
    wheel_metadata: list[str] = []
    wheel_record: list[str] = []
    wheel_signature: dict = {}
    frontend_reference_errors: list[str] = []
    wheel_source_mismatches: list[str] = []
    wheel_content_privacy: list[str] = []
    # Nulls, not zeroes: if the wheel never reaches the RECORD pass these counts
    # were not measured, and a 0 would read as "hashed nothing" instead.
    wheel_record_measurement: dict = {
        "members_total": None,
        "members_hashed": None,
        "members_exempt_record_self_reference": None,
        "members_neither_hashed_nor_exempt": None,
    }
    wheel_source_compared = 0
    wheel_license_compared = 0
    wheel_content_scanned = 0
    wheel_content_exempt = 0
    try:
        wheel_bytes = _read_regular_bounded(wheels[0], _MAX_ARCHIVE_BYTES)
        wheel_sha256 = hashlib.sha256(wheel_bytes).hexdigest()
        container_errors = _zip_container_errors(wheel_bytes)
        wheel_structure.extend(container_errors)
        if container_errors:
            raise ValueError("wheel container preflight failed")
        with zipfile.ZipFile(io.BytesIO(wheel_bytes)) as wheel_archive:
            all_wheel_infos = wheel_archive.infolist()
            wheel_structure.extend(_zip_preflight(all_wheel_infos))
            wheel_structure.extend(
                _archive_name_errors(
                    [info.filename for info in all_wheel_infos]
                )
            )
            wheel_infos = [
                info for info in all_wheel_infos if not info.is_dir()
            ]
            wheel_names = {info.filename for info in wheel_infos}
            info_by_name = {info.filename: info for info in wheel_infos}
            metadata_dirs = sorted(
                {
                    part
                    for name in wheel_names
                    for part in PurePosixPath(name).parts
                    if part.endswith(".dist-info")
                }
            )
            expected_metadata_dir = (
                f"{re.sub(r'[-.]+', '_', project_name)}-"
                f"{project_version}.dist-info"
            )
            if project_name and metadata_dirs != [expected_metadata_dir]:
                wheel_metadata.append(
                    "wheel dist-info directory differs: "
                    f"{metadata_dirs!r} != {[expected_metadata_dir]!r}"
                )
            if len(metadata_dirs) == 1 and not project_contract_errors:
                metadata_errors, wheel_signature = _verify_wheel_metadata(
                    wheel_archive,
                    info_by_name,
                    wheel_names,
                    metadata_dirs[0],
                    contract,
                )
                wheel_metadata.extend(metadata_errors)
                wheel_record, wheel_record_measurement = _verify_wheel_record(
                    wheel_archive,
                    info_by_name,
                    wheel_names,
                    metadata_dirs[0],
                )
            frontend_index = "webapp/frontend/dist/index.html"
            if frontend_index in info_by_name:
                try:
                    frontend_reference_errors = _frontend_reference_errors(
                        _zip_read(
                            wheel_archive,
                            info_by_name,
                            frontend_index,
                        ),
                        wheel_names,
                        frontend_index,
                    )
                except ValueError as exc:
                    frontend_reference_errors.append(str(exc))
            for name in sorted(expected_runtime & wheel_names):
                try:
                    archived = _zip_read(
                        wheel_archive,
                        info_by_name,
                        name,
                    )
                except ValueError as exc:
                    wheel_source_mismatches.append(f"{name}: {exc}")
                    continue
                wheel_source_compared += 1
                if archived != source_payloads.get(name):
                    wheel_source_mismatches.append(name)
            if len(metadata_dirs) == 1:
                # Every license document the wheel's own METADATA declares in
                # `License-File` must BE in the wheel and match the working tree.
                # This used to compare one hardcoded `licenses/LICENSE` only when
                # it happened to be present, so a wheel that declared
                # `License-File: LICENSE` and shipped no license at all was
                # accepted -- the sole trace was
                # `wheel_license_byte_compared_to_worktree` reading 0, a number
                # nothing in this module compares against anything.
                for declared_license in contract["headers"].get("License-File", []):
                    license_name = (
                        f"{metadata_dirs[0]}/licenses/{declared_license}"
                    )
                    if license_name not in info_by_name:
                        wheel_source_mismatches.append(
                            f"{license_name}: declared by METADATA License-File "
                            "and absent from the wheel"
                        )
                        continue
                    try:
                        archived_license = _zip_read(
                            wheel_archive,
                            info_by_name,
                            license_name,
                        )
                    except ValueError as exc:
                        wheel_source_mismatches.append(
                            f"{license_name}: {exc}"
                        )
                    else:
                        wheel_license_compared += 1
                        if archived_license != source_payloads.get(
                            declared_license
                        ):
                            wheel_source_mismatches.append(license_name)
            for name in sorted(wheel_names):
                try:
                    member_errors, scanned = _content_privacy_errors(
                        name,
                        _zip_read(
                            wheel_archive,
                            info_by_name,
                            name,
                        ),
                        known_hostname_hashes,
                    )
                except ValueError as exc:
                    wheel_content_privacy.append(str(exc))
                else:
                    wheel_content_privacy.extend(member_errors)
                    if scanned:
                        wheel_content_scanned += 1
                    else:
                        wheel_content_exempt += 1
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        wheel_bytes = b""
        wheel_sha256 = ""
        wheel_structure.append(f"wheel is unreadable: {exc}")

    sdist_names: set[str] = set()
    sdist_structure: list[str] = []
    sdist_source_mismatches: list[str] = []
    sdist_content_privacy: list[str] = []
    sdist_metadata: list[str] = []
    sdist_metadata_equivalence = {
        "pkg_info_documents_parsed": 0,
        "cross_checked_against_wheel_metadata": 0,
    }
    sdist_source_compared = 0
    sdist_content_scanned = 0
    sdist_content_exempt = 0
    try:
        sdist_bytes = _read_regular_bounded(sdists[0], _MAX_ARCHIVE_BYTES)
        sdist_sha256 = hashlib.sha256(sdist_bytes).hexdigest()
        with tarfile.open(fileobj=io.BytesIO(sdist_bytes), mode="r:gz") as sdist_archive:
            sdist_members: list[tarfile.TarInfo] = []
            for member in sdist_archive:
                sdist_members.append(member)
                if len(sdist_members) > _MAX_ARCHIVE_MEMBERS:
                    break
            sdist_structure.extend(_tar_preflight(sdist_members))
            normalised_names, normalise_errors = _normalise_sdist(
                sdist_members
            )
            sdist_names = normalised_names
            sdist_structure.extend(normalise_errors)
            sdist_file_members: dict[str, tarfile.TarInfo] = {}
            roots = {
                PurePosixPath(member.name).parts[0]
                for member in sdist_members
                if PurePosixPath(member.name).parts
            }
            expected_sdist_root = (
                f"{re.sub(r'[-.]+', '_', project_name)}-{project_version}"
            )
            if project_name and roots != {expected_sdist_root}:
                sdist_structure.append(
                    f"sdist root differs: {sorted(roots)} != {[expected_sdist_root]}"
                )
            if len(roots) == 1:
                sdist_root = next(iter(roots))
                for member in sdist_members:
                    parts = PurePosixPath(member.name).parts
                    if (
                        member.isfile()
                        and len(parts) > 1
                        and parts[0] == sdist_root
                    ):
                        relative = PurePosixPath(*parts[1:]).as_posix()
                        if relative in sdist_file_members:
                            sdist_structure.append(
                                f"duplicate normalised sdist member: {relative}"
                            )
                        else:
                            sdist_file_members[relative] = member
            for name in sorted(expected_sdist_sources & sdist_names):
                member = sdist_file_members.get(name)
                if member is None:
                    # Named in the inventory but with no readable member behind
                    # it: never silently skip, or the compared count silently
                    # drifts below the inventory it claims to cover.
                    sdist_source_mismatches.append(
                        f"{name}: sdist inventory has no readable file member"
                    )
                    continue
                try:
                    archived = _tar_read(sdist_archive, member)
                except ValueError as exc:
                    sdist_source_mismatches.append(f"{name}: {exc}")
                    continue
                sdist_source_compared += 1
                if archived != source_payloads.get(name):
                    sdist_source_mismatches.append(name)
            for name, member in sorted(sdist_file_members.items()):
                try:
                    member_errors, scanned = _content_privacy_errors(
                        name,
                        _tar_read(sdist_archive, member),
                        known_hostname_hashes,
                    )
                except ValueError as exc:
                    sdist_content_privacy.append(str(exc))
                else:
                    sdist_content_privacy.extend(member_errors)
                    if scanned:
                        sdist_content_scanned += 1
                    else:
                        sdist_content_exempt += 1
            if not project_contract_errors:
                sdist_metadata, sdist_metadata_equivalence = (
                    _verify_sdist_metadata(
                        sdist_archive,
                        sdist_file_members,
                        sdist_names,
                        contract,
                        wheel_signature,
                    )
                )
    except (OSError, ValueError, tarfile.TarError) as exc:
        sdist_bytes = b""
        sdist_sha256 = ""
        sdist_structure.append(f"sdist is unreadable: {exc}")

    missing_wheel = sorted(expected_runtime - wheel_names)
    missing_sdist = sorted(expected_sdist_sources - sdist_names)
    allowed_wheel = set(expected_runtime)
    if len(metadata_dirs) == 1:
        allowed_wheel.update(
            f"{metadata_dirs[0]}/{relative}"
            for relative in _WHEEL_METADATA_FILES
        )
        # Derived from the metadata contract's own License-File declaration, not
        # from a hardcoded `licenses/LICENSE` spelling.
        allowed_wheel.update(
            f"{metadata_dirs[0]}/licenses/{declared_license}"
            for declared_license in contract["headers"].get("License-File", [])
        )
    unexpected_wheel = sorted(wheel_names - allowed_wheel)
    allowed_sdist = (
        expected_sdist_sources | _expected_sdist_generated(project_name)
    )
    unexpected_sdist = sorted(sdist_names - allowed_sdist)
    wheel_privacy = _privacy_violations(wheel_names)
    sdist_privacy = _privacy_violations(sdist_names)

    # Both archives are open and classified, so the shipped member set is known
    # and the binding can be settled against the bytes that really ship.  An
    # unreadable archive leaves its member set empty, which makes the coverage
    # population empty and the headline verdict false -- fail closed.
    (
        source_binding,
        source_binding_errors,
        runtime_inventory_proof,
        shipped_coverage_proof,
    ) = _source_binding(
        project_root,
        claimed_source_commit,
        claimed_source_tree,
        runtime_inventory,
        (wheel_names, sdist_names),
    )

    source_changed_during_verification: list[str] = []
    for name, original in source_payloads.items():
        try:
            current = _read_regular_bounded(
                project_root.joinpath(*PurePosixPath(name).parts),
                _MAX_PROJECT_SOURCE_BYTES,
            )
        except (OSError, ValueError) as exc:
            source_changed_during_verification.append(f"{name}: {exc}")
            continue
        if current != original:
            source_changed_during_verification.append(name)
    try:
        final_runtime_inventory = _expected_runtime_inventory(project_root)
    except (OSError, ValueError) as exc:
        source_changed_during_verification.append(
            f"runtime source inventory recheck failed: {exc}"
        )
    else:
        if final_runtime_inventory != runtime_inventory:
            final_expected_runtime = set(final_runtime_inventory)
            added = sorted(final_expected_runtime - expected_runtime)
            removed = sorted(expected_runtime - final_expected_runtime)
            reclassified = sorted(
                name
                for name in set(final_runtime_inventory) & expected_runtime
                if final_runtime_inventory[name] != runtime_inventory[name]
            )
            source_changed_during_verification.append(
                "runtime source inventory changed: "
                f"added={added}, removed={removed}, "
                f"reclassified={reclassified}"
            )
    if known_hostname_payload:
        try:
            final_known_hostname_payload = _read_regular_bounded(
                project_root.joinpath(*_KNOWN_HOST_HASHES.parts),
                _MAX_METADATA_BYTES,
            )
        except (OSError, ValueError) as exc:
            source_changed_during_verification.append(
                f"{_KNOWN_HOST_HASHES.as_posix()}: {exc}"
            )
        else:
            if final_known_hostname_payload != known_hostname_payload:
                source_changed_during_verification.append(
                    _KNOWN_HOST_HASHES.as_posix()
                )

    errors = {
        "source_binding_errors": source_binding_errors,
        "archive_filename_errors": archive_filename_errors,
        "missing_wheel": missing_wheel,
        "missing_sdist": missing_sdist,
        "missing_project_sources": missing_project_sources,
        "project_source_errors": project_source_errors,
        "unexpected_wheel": unexpected_wheel,
        "unexpected_sdist": unexpected_sdist,
        "wheel_source_mismatches": wheel_source_mismatches,
        "sdist_source_mismatches": sdist_source_mismatches,
        "wheel_privacy_violations": wheel_privacy,
        "sdist_privacy_violations": sdist_privacy,
        "wheel_content_privacy_errors": wheel_content_privacy,
        "sdist_content_privacy_errors": sdist_content_privacy,
        "wheel_metadata_dirs": (
            []
            if len(metadata_dirs) == 1
            else metadata_dirs or ["absent"]
        ),
        "wheel_structure_errors": wheel_structure,
        "sdist_structure_errors": sdist_structure,
        "wheel_metadata_errors": wheel_metadata,
        "sdist_metadata_errors": sdist_metadata,
        "wheel_record_errors": wheel_record,
        "frontend_reference_errors": frontend_reference_errors,
        "project_contract_errors": project_contract_errors,
        "registry_source_chain_errors": registry_source_chain_errors,
        "eol_source_chain_errors": eol_source_chain_errors,
        "source_changed_during_verification": source_changed_during_verification,
    }
    if any(errors.values()):
        raise ValueError(json.dumps(errors, indent=2, sort_keys=True))

    source_manifest = hashlib.sha256()
    for name, payload in sorted(source_payloads.items()):
        source_manifest.update(name.encode("utf-8"))
        source_manifest.update(b"\0")
        source_manifest.update(hashlib.sha256(payload).digest())
        source_manifest.update(b"\0")
    return {
        # 6: the source binding's coverage set became the shipped archive member
        # set (it was the wheel's runtime inventory), the headline field was
        # renamed to say it is a self-check, and the untracked disclosure was
        # scoped to shipped paths so build and cache churn stops moving the proof.
        "verification_schema": 6,
        "project": project_name,
        "version": project_version,
        "source_binding": source_binding,
        "known_client_hostname_denylist_sha256": hashlib.sha256(
            known_hostname_payload
        ).hexdigest(),
        "wheel": wheels[0].name,
        "wheel_bytes": len(wheel_bytes),
        "wheel_sha256": wheel_sha256,
        "sdist": sdists[0].name,
        "sdist_bytes": len(sdist_bytes),
        "sdist_sha256": sdist_sha256,
        "wheel_members": len(wheel_names),
        "sdist_members": len(sdist_names),
        "source_manifest_sha256": source_manifest.hexdigest(),
        "console_scripts_verified": sorted(_EXPECTED_CONSOLE_SCRIPTS),
        "registry_source_chains": registry_source_chains,
        "eol_source_chain": eol_source_chain,
        # Every entry below is a count of work that was actually performed.  The
        # predecessors of this block were six literal `True`s, which made
        # --expected-json vacuous for exactly the keys a reader scans first.
        "measurements": {
            # `wheel_members_hashed_against_record` on its own says nothing: a
            # wheel this proof accepts always hashes every member except the one
            # RECORD may not hash, itself, so the count is total minus that row
            # by construction.  The exemption is therefore named and counted, and
            # `wheel_members_neither_hashed_nor_exempt` -- the members left
            # unhashed for any other reason -- is the field that carries
            # information.
            "record_hashes": {
                "wheel_members_hashed_against_record": (
                    wheel_record_measurement["members_hashed"]
                ),
                "wheel_members_exempt_record_self_reference": (
                    wheel_record_measurement["members_exempt_record_self_reference"]
                ),
                "wheel_members_neither_hashed_nor_exempt": (
                    wheel_record_measurement["members_neither_hashed_nor_exempt"]
                ),
                "wheel_members_total": wheel_record_measurement["members_total"],
            },
            "metadata_equivalence": {
                "wheel_metadata_fields_compared": len(wheel_signature),
                "sdist_pkg_info_documents_parsed": (
                    sdist_metadata_equivalence["pkg_info_documents_parsed"]
                ),
                "sdist_pkg_info_documents_cross_checked_against_wheel": (
                    sdist_metadata_equivalence[
                        "cross_checked_against_wheel_metadata"
                    ]
                ),
            },
            "source_bytes": {
                "wheel_members_byte_compared_to_worktree": wheel_source_compared,
                "wheel_license_byte_compared_to_worktree": wheel_license_compared,
                "sdist_members_byte_compared_to_worktree": sdist_source_compared,
                "worktree_sources_read": len(source_payloads),
            },
            "unexpected_members": {
                "wheel_members_classified": len(wheel_names),
                "wheel_allowlist_members": len(allowed_wheel),
                "sdist_members_classified": len(sdist_names),
                "sdist_allowlist_members": len(allowed_sdist),
            },
            "archive_content_privacy": {
                "wheel_members_content_scanned": wheel_content_scanned,
                "wheel_members_content_scan_exempt": wheel_content_exempt,
                "sdist_members_content_scanned": sdist_content_scanned,
                "sdist_members_content_scan_exempt": sdist_content_exempt,
                "content_marker_patterns_applied": len(
                    _client_marker_patterns()
                ),
                "known_hostname_digests_applied": len(known_hostname_hashes),
            },
            "privacy_boundary": {
                "wheel_member_names_checked": len(wheel_names),
                "sdist_member_names_checked": len(sdist_names),
                "forbidden_path_parts_applied": len(_FORBIDDEN_PARTS),
                "forbidden_suffixes_applied": len(_FORBIDDEN_SUFFIXES),
            },
            # The coverage set the headline verdict is settled against: the bytes
            # that really ship, both archives, with the build-generated members
            # counted and disclosed inside the denominator rather than dropped.
            "shipped_bytes_coverage": shipped_coverage_proof,
            "runtime_inventory": runtime_inventory_proof,
            "sdist_source_inventory": _sdist_source_inventory_proof(
                expected_sdist_sources,
                runtime_inventory_proof,
            ),
        },
    }


def _verify_expected_proof(result: dict, path: str | os.PathLike[str]) -> None:
    proof_path = Path(path)
    try:
        expected = _strict_json_bytes(
            _read_regular_bounded(proof_path, _MAX_PROOF_BYTES),
            str(proof_path),
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"trusted distribution proof is unreadable: {proof_path}: {exc}") from exc
    except ValueError as exc:
        raise ValueError(
            f"trusted distribution proof is invalid: {proof_path}: {exc}"
        ) from exc
    if expected != result:
        differing = sorted(
            key
            for key in set(expected) | set(result)
            if expected.get(key) != result.get(key)
        )
        raise ValueError(
            "release archives differ from the trusted distribution proof "
            f"{proof_path}; differing fields: {differing}"
        )


def _write_new_proof(path: str | os.PathLike[str], rendered: str) -> None:
    proof_path = Path(path)
    payload = (rendered + "\n").encode("utf-8")
    if len(payload) > _MAX_PROOF_BYTES:
        raise ValueError(
            f"distribution proof exceeds {_MAX_PROOF_BYTES} bytes"
        )
    with proof_path.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    if _read_regular_bounded(proof_path, _MAX_PROOF_BYTES) != payload:
        raise ValueError(f"distribution proof changed after write: {proof_path}")


def _proof_caveats(result: dict) -> list[str]:
    """State on stdout what the emitted proof did NOT establish.

    A reader who scans the JSON for red should not have to notice a nested
    ``verified: false`` to learn that the commit binding is only a label, or
    that part of the shipped runtime is bound to nothing but this working tree.
    """
    caveats: list[str] = []
    binding = result.get("source_binding", {})
    if not binding.get("self_verified_against_this_worktree"):
        caveats.append(
            "the source binding was NOT established, not even as a self-check: "
            f"{binding.get('unverified_reason') or 'reason not recorded'}. "
            "The archives were verified against the working tree at --root. "
            f"This is {binding.get('exit_code_enforcement') or 'advisory'}."
        )
    # Permanent, so it prints on every run: the strongest verdict this module can
    # reach is still a self-check, and a reader must not take it for more.
    caveats.append(
        "this proof is SELF-verification only -- "
        f"{binding.get('independence_limit') or _INDEPENDENCE_LIMIT}"
    )
    if binding.get("method") == _SOURCE_BINDING_GIT:
        caveats.append(
            "the claimed commit was compared against `git rev-parse HEAD` in "
            "the same work tree the archives were built from; every caller in "
            "this repository derives the claim from that tree, so the match "
            "confirms the caller quoted its own tree and does NOT establish "
            "which reviewed revision the tree is"
        )
    if binding.get("untracked_scan_measured") is False:
        caveats.append(
            "the set of paths git does not track could not be listed, so what "
            "the binding cannot see is NOT MEASURED, not empty"
        )
    elif binding.get("untracked_entries_covering_shipped_members"):
        caveats.append(
            f"{binding['untracked_entries_covering_shipped_members']} untracked "
            "path(s) hold shipped archive members and are bound to no commit: "
            f"{binding.get('untracked_prefixes_covering_shipped_members')}"
        )
    measurements = result.get("measurements", {})
    shipped = measurements.get("shipped_bytes_coverage", {})
    if not shipped.get("source_binding_coverage_measured"):
        caveats.append(
            "the shipped archive member set could not be compared against a "
            "tracked source set, so its coverage by the claimed commit is "
            "NOT MEASURED, not zero"
        )
    elif shipped.get("members_outside_source_binding"):
        caveats.append(
            f"{shipped['members_outside_source_binding']} of "
            f"{shipped.get('members_shipped_distinct')} shipped archive "
            "member(s) are outside the claimed commit: "
            f"{shipped.get('prefixes_outside_source_binding')}"
        )
    generated = shipped.get("members_build_generated_unbindable")
    if generated:
        caveats.append(
            f"{generated} of {shipped.get('members_shipped_distinct')} shipped "
            "member(s) are generated by the build backend and can belong to no "
            "commit; they are counted inside the coverage denominator, not "
            "excluded from it: "
            f"{shipped.get('prefixes_build_generated_unbindable')}"
        )
    inventory = measurements.get("runtime_inventory", {})
    if not inventory.get("source_binding_coverage_measured"):
        caveats.append(
            "the expected runtime inventory could not be compared against a "
            "tracked source set, so its coverage by the claimed commit is "
            "NOT MEASURED, not zero"
        )
    elif inventory.get("members_outside_source_binding"):
        caveats.append(
            f"{inventory['members_outside_source_binding']} expected runtime "
            "member(s) are outside the claimed commit and are expected only "
            "because they were found on disk: "
            f"{inventory.get('prefixes_outside_source_binding')}"
        )
    self_derived = inventory.get("self_derived_from_worktree_glob")
    if self_derived:
        sdist_inventory = measurements.get("sdist_source_inventory", {})
        caveats.append(
            f"{self_derived} of {inventory.get('members_expected')} expected "
            "runtime members were discovered by globbing this working tree; "
            "for those, 'expected' and 'actual' are the same measurement. The "
            "same members carry into the sdist expected set ("
            f"{sdist_inventory.get('self_derived_from_worktree_glob')} of "
            f"{sdist_inventory.get('members_expected')} there)"
        )
    return caveats


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dist_dir", nargs="?", default="dist")
    parser.add_argument("--root", default=".")
    parser.add_argument(
        "--source-commit",
        required=True,
        help=(
            "claimed Git commit object id for the verified source; resolved "
            "against a local repository at --root when one is present, and "
            "recorded as an unverified caller label when one is not"
        ),
    )
    parser.add_argument(
        "--source-tree",
        required=True,
        help=(
            "claimed Git tree object id for the verified source; resolved "
            "against a local repository at --root when one is present, and "
            "recorded as an unverified caller label when one is not"
        ),
    )
    parser.add_argument("--json-out")
    parser.add_argument(
        "--expected-json",
        help="refuse archives whose recomputed proof differs from this trusted release proof",
    )
    parser.add_argument(
        "--require-source-binding",
        action="store_true",
        help=(
            "exit "
            f"{_EXIT_UNVERIFIED_BINDING} when "
            "source_binding.self_verified_against_this_worktree is false. "
            "Off by default because the ordinary run against a downloaded "
            "archive has no repository to resolve; without it the binding is "
            "disclosure only and no exit code reflects it"
        ),
    )
    args = parser.parse_args(argv)
    try:
        result = verify_archives(
            args.dist_dir,
            args.root,
            source_commit=args.source_commit,
            source_tree=args.source_tree,
        )
        if args.expected_json:
            _verify_expected_proof(result, args.expected_json)
    except (OSError, ValueError, tarfile.TarError, zipfile.BadZipFile) as exc:
        print(f"distribution verification failed: {exc}")
        return 1
    for caveat in _proof_caveats(result):
        print(f"WARNING: {caveat}")
    rendered = json.dumps(result, indent=2, sort_keys=True)
    print(rendered)
    if args.json_out:
        try:
            _write_new_proof(args.json_out, rendered)
        except (OSError, ValueError) as exc:
            print(f"distribution proof could not be written: {exc}")
            return 1
    # The archives verified; only the binding is in question here.  Reported
    # separately from exit 1 so a caller can tell "the release is wrong" from
    # "the release is right but nothing ties it to a reviewed commit".
    if not result.get("source_binding", {}).get(
        "self_verified_against_this_worktree"
    ):
        if args.require_source_binding:
            print(
                "source binding not established and --require-source-binding "
                f"was given: exiting {_EXIT_UNVERIFIED_BINDING}"
            )
            return _EXIT_UNVERIFIED_BINDING
        print(
            "NOTE: the archives verified; the source binding above is "
            "ADVISORY and did not affect this exit code. Pass "
            "--require-source-binding to make it a control."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
