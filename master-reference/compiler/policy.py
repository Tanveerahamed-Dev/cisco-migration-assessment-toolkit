"""Strict path, file-kind, language, and privacy classification policy.

Only tracked paths under the known repository surface are accepted.  The Git
census cannot reach machine-local Claude memory or the user's Obsidian Vault.
Tracked ``.claude/agent-memory`` files are ordinary repository history/cache
and are intentionally line-mapped; that path is not the machine-local store.
"""

from __future__ import annotations

import mimetypes
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any


ALLOWED_TOP_LEVEL_DIRECTORIES = frozenset(
    {
        ".claude",
        ".design-sync",
        ".github",
        "atlas-scope",
        "cisco_toolkit",
        "docs",
        "master-reference",
        "portable",
        "reference-data",
        "research_lane",
        "tests",
        "tools",
        "webapp",
    }
)

BLOCKED_COMPONENTS = frozenset(
    {
        ".git",
        ".cache",
        ".vinext",
        ".wrangler",
        "backups",
        "captures",
        "collections",
        "node_modules",
        "private-inputs",
        "raw",
        "secrets",
        "vault",
        "venv",
        ".venv",
    }
)

ROOT_TEXT_NAMES = frozenset(
    {
        ".gitattributes",
        ".gitignore",
        ".graphifyignore",
        ".mcp.json",
        "AGENTS.md",
        "CHANGELOG.md",
        "CLAUDE.md",
        "COLLECT_PARSE_V3_23_0.md",
        "COLLECT_PARSE_V3_23_0.py",
        "IMPROVEMENT_AND_GREENFIELD_PLANS.md",
        "LICENSE",
        "MANIFEST.in",
        "README.md",
        "SECURITY.md",
        "conftest.py",
        "devices.example.json",
        "embed_qbank.py",
        "mypy.ini",
        "ollama_judge.py",
        "ollama_recall.py",
        "ollama_retrieval_judge.py",
        "pyproject.toml",
        "pytest.ini",
        "questionnaire.json",
        "requirements-dev.txt",
        "requirements.sample.json",
        "requirements.txt",
        "ruff.toml",
        "setup.py",
    }
)

SPECIAL_CONFIG_NAMES = frozenset(
    {
        ".gitattributes",
        ".gitignore",
        ".graphifyignore",
    }
)
SPECIAL_CONFIG_PATHS = frozenset({"master-reference/public/_headers"})

TEXT_EXTENSIONS = frozenset(
    {
        ".css",
        ".csv",
        ".html",
        ".in",
        ".ini",
        ".js",
        ".jsx",
        ".cjs",
        ".cts",
        ".json",
        ".jsonc",
        ".jsonl",
        ".lock",
        ".md",
        ".mjs",
        ".mts",
        ".ps1",
        ".py",
        ".sh",
        ".spec",
        ".sql",
        ".svg",
        ".toml",
        ".ts",
        ".tsbuildinfo",
        ".tsx",
        ".txt",
        ".yaml",
        ".yml",
    }
)

BINARY_EXTENSIONS = frozenset(
    {
        ".docx",
        ".gz",
        ".ico",
        ".jpeg",
        ".jpg",
        ".pdf",
        ".png",
        ".pptx",
        ".webp",
        ".woff",
        ".woff2",
        ".xlsx",
        ".zip",
    }
)

LANGUAGE_BY_EXTENSION = {
    ".css": "css",
    ".csv": "csv",
    ".html": "html",
    ".in": "manifest",
    ".ini": "ini",
    ".js": "javascript",
    ".jsx": "jsx",
    ".cjs": "javascript",
    ".cts": "typescript",
    ".json": "json",
    ".jsonc": "jsonc",
    ".jsonl": "jsonl",
    ".lock": "text",
    ".md": "markdown",
    ".mjs": "javascript",
    ".mts": "typescript",
    ".ps1": "powershell",
    ".py": "python",
    ".sh": "shell",
    ".spec": "python",
    ".sql": "sql",
    ".svg": "svg",
    ".toml": "toml",
    ".ts": "typescript",
    ".tsbuildinfo": "json",
    ".tsx": "tsx",
    ".txt": "text",
    ".yaml": "yaml",
    ".yml": "yaml",
}

# TypeScript reads every project configuration file (``tsconfig.json`` and the
# ``tsconfig.<role>.json`` / ``jsconfig*.json`` files a project splits it into,
# referenced through ``extends``/``references``/``-p``) with its JSON-with-
# comments reader, so comments and trailing commas are legal there.  The name,
# not a list of paths, is what makes such a file JSONC; strict JSON parsing of
# one that happens to carry no comment is coincidence, not its format.
JSONC_CONFIG_NAME_RE = re.compile(r"^[jt]sconfig(?:[._-][^/]*)?\.json$")

SOURCE_LANGUAGES = frozenset(
    {
        "css",
        "html",
        "javascript",
        "jsx",
        "powershell",
        "python",
        "shell",
        "svg",
        "typescript",
        "tsx",
    }
)

CURRENT_OWNER_DOCS = frozenset(
    {
        "AGENTS.md",
        "CLAUDE.md",
        "README.md",
        "SECURITY.md",
        "docs/quality/learnings.md",
        "docs/ssot.md",
        "master-reference/README.md",
    }
)

HISTORICAL_NAME_RE = re.compile(
    r"(?:^|[-_])(19|20)\d{2}[-_]\d{2}[-_]\d{2}(?:[-_.]|$)|"
    r"(?:handoff|closeout|review-findings|session-summary|historical)",
    re.IGNORECASE,
)
PLAN_NAME_RE = re.compile(r"(?:^|[-_])(plan|roadmap|remaining-work)(?:[-_.]|$)", re.IGNORECASE)

WORKFLOW_PREFIX = ".github/workflows/"
SAFE_DATA_PREFIXES = (
    ".design-sync/",
    ".github/",
    "cisco_toolkit/data/",
    "docs/",
    "master-reference/",
    "reference-data/",
    "tests/",
    "webapp/sample_data/",
)
SAFE_ROOT_DATA = frozenset({"devices.example.json", "questionnaire.json", "requirements.sample.json"})


CENSUS_DEPTH_FULL = "full"
CENSUS_DEPTH_IDENTITY = "identity"
CENSUS_DEPTHS = (CENSUS_DEPTH_FULL, CENSUS_DEPTH_IDENTITY)
CENSUS_DEPTH_POLICY_OWNER = "master-reference/compiler/policy.py::CENSUS_DEPTH_DECLARATIONS"
# Record groups an identity-depth file still emits.  ``binaries`` only applies
# to a binary path, which is metadata-only at every depth.
IDENTITY_DEPTH_RETAINED_GROUPS = ("binaries", "files", "imports")
# Record groups the compiler's line/parse pipeline withholds for an
# identity-depth file.  Together with the retained groups, the Graphify
# secondary projection, and the path-free claim groups this is the whole
# compiler record-group universe (reconciled by the compiler at import time).
IDENTITY_DEPTH_DEFERRED_GROUPS = (
    "calls",
    "components",
    "configs",
    "datasets",
    "dependencies",
    "documents",
    "lines",
    "manifests",
    "markdown",
    "routes",
    "source_text",
    "structural_entities",
    "structured",
    "symbols",
    "tests",
    "workflows",
)


@dataclass(frozen=True)
class CensusDepthDeclaration:
    """One reviewed path prefix whose census is deliberately shallower than full."""

    prefix: str
    census_depth: str
    reason: str
    block_category: str
    follow_up_owner: str


# CENSUS DEPTH -- the ONE owner of every deferred prefix.
#
# Every tracked file is censused at ``full`` depth (file record, exact source
# text, one record per nonblank line, symbols, calls, structured values, GUI
# dossiers) unless its path starts with a prefix declared here.  A declared
# prefix is censused at ``identity`` depth: the file record (path, Git blob
# OID, content digest, size, language/role classification, architecture
# disposition) and its static import edges are still emitted, and the full
# privacy decision -- strict UTF-8/NUL/control-density text safety plus the
# forbidden-content scan -- still reads the file's complete bytes.  Only the
# per-line, per-symbol, call, structured-value, source-text and dossier
# projections are withheld.
#
# Why this exists: admitting the 400-file ``atlas-scope/`` application took
# the compiler output from roughly 1.87 GB to 2.74 GB (atlas-scope alone about
# 868 MB of per-line, symbol, source-text, call and dossier records).  That
# breaks the 32 MiB compiler-chunk bound, the 2 GiB expanded-projection and
# bounded privacy-scan budgets, and the 248 MiB Sites deployment ceiling -- all
# safety gates or an external platform limit that must not be raised.  The
# owner recorded the decision to defer line projection for this prefix until a
# compact per-line record encoding exists (the follow-up owner below).
#
# Deferral is never presented as coverage: each declaration names a release
# BLOCK category that the compiler ledger, the failed
# ``every_tracked_text_file_line_censused`` acceptance gate, the release
# manifest and every rendered coverage surface carry while any file is
# censused at identity depth.  ``tests/compiler/test_census_depth.py`` pins
# this tuple: growing it without a reviewed receipt fails that test.
CENSUS_DEPTH_DECLARATIONS: tuple[CensusDepthDeclaration, ...] = (
    CensusDepthDeclaration(
        prefix="atlas-scope/",
        census_depth=CENSUS_DEPTH_IDENTITY,
        reason="line_projection_deferred:size_ceiling",
        block_category="census_depth_identity_line_projection_deferred",
        follow_up_owner="master-reference/compiler: compact per-line record encoding",
    ),
)


def validate_census_depth_declarations(
    declarations: tuple[CensusDepthDeclaration, ...] = CENSUS_DEPTH_DECLARATIONS,
) -> list[str]:
    """Return every reason a declaration cannot stand as a reviewed deferral."""

    errors: list[str] = []
    seen: set[str] = set()
    for declaration in declarations:
        prefix = declaration.prefix
        path = PurePosixPath(prefix.rstrip("/")) if prefix.endswith("/") else None
        if (
            path is None
            or not path.parts
            or path.is_absolute()
            or ".." in path.parts
            or path.as_posix() + "/" != prefix
            or path.parts[0] not in ALLOWED_TOP_LEVEL_DIRECTORIES
        ):
            errors.append(f"census_depth_prefix_invalid:{prefix}")
        if any(prefix.startswith(other) or other.startswith(prefix) for other in seen):
            errors.append(f"census_depth_prefix_overlaps:{prefix}")
        seen.add(prefix)
        if declaration.census_depth != CENSUS_DEPTH_IDENTITY:
            errors.append(f"census_depth_value_invalid:{prefix}")
        if not re.fullmatch(r"[a-z][a-z0-9_]*:[a-z][a-z0-9_]*", declaration.reason):
            errors.append(f"census_depth_reason_invalid:{prefix}")
        if not re.fullmatch(r"census_depth_[a-z0-9_]+", declaration.block_category):
            errors.append(f"census_depth_block_category_invalid:{prefix}")
        if not declaration.follow_up_owner.strip():
            errors.append(f"census_depth_follow_up_owner_missing:{prefix}")
    return errors


def census_depth_declaration(path: str) -> CensusDepthDeclaration | None:
    """Return the declaration that defers ``path``, or ``None`` for full depth."""

    matches = [item for item in CENSUS_DEPTH_DECLARATIONS if path.startswith(item.prefix)]
    if len(matches) > 1:
        raise ValueError(f"census depth declarations overlap for {path}")
    return matches[0] if matches else None


def census_depth_decision(path: str) -> tuple[str, str | None]:
    """Return ``(census_depth, reason)`` for one tracked path."""

    declaration = census_depth_declaration(path)
    if declaration is None:
        return CENSUS_DEPTH_FULL, None
    return declaration.census_depth, declaration.reason


def census_depth_declaration_receipts() -> list[dict[str, Any]]:
    """Serializable declarations, in prefix order, for ledgers and validators."""

    return [
        {
            "prefix": item.prefix,
            "census_depth": item.census_depth,
            "reason": item.reason,
            "block_category": item.block_category,
            "follow_up_owner": item.follow_up_owner,
        }
        for item in sorted(CENSUS_DEPTH_DECLARATIONS, key=lambda row: row.prefix)
    ]


def _components(path: str) -> tuple[str, ...]:
    return tuple(part.lower() for part in PurePosixPath(path).parts)


def privacy_decision(path: str, git_mode: str) -> tuple[str, list[str]]:
    """Return exposure (`full`, `metadata_only`) and explicit reasons."""

    parts = _components(path)
    blocked = sorted(set(parts) & BLOCKED_COMPONENTS)
    if blocked:
        return "metadata_only", [f"blocked_path_component:{part}" for part in blocked]
    if git_mode in {"120000", "160000"}:
        return "metadata_only", ["symlink_or_gitlink_not_followed"]
    if _extension(path) in BINARY_EXTENSIONS:
        return "metadata_only", ["binary_payload_requires_format_aware_privacy_review"]
    return "full", []


def _extension(path: str) -> str:
    lower = path.lower()
    if lower.endswith(".d.ts"):
        return ".ts"
    return PurePosixPath(lower).suffix


def _is_license_name(name: str) -> bool:
    return name == "license" or name.endswith("-license")


def validate_path_allowlist(path: str) -> list[str]:
    p = PurePosixPath(path)
    if p.is_absolute() or ".." in p.parts or not p.parts:
        return ["unsafe_repository_path"]
    if len(p.parts) == 1:
        if path in ROOT_TEXT_NAMES:
            return []
        ext = _extension(path)
        if ext in TEXT_EXTENSIONS or ext in BINARY_EXTENSIONS:
            return []
        return ["unclassified_root_path"]
    if p.parts[0] not in ALLOWED_TOP_LEVEL_DIRECTORIES:
        return [f"top_level_not_allowlisted:{p.parts[0]}"]
    ext = _extension(path)
    name = p.name.lower()
    if ext in TEXT_EXTENSIONS or ext in BINARY_EXTENSIONS:
        return []
    if _is_license_name(name) or name in SPECIAL_CONFIG_NAMES or path in SPECIAL_CONFIG_PATHS:
        return []
    return [f"extension_not_allowlisted:{ext or '<none>'}"]


def classify_file(path: str, git_mode: str) -> dict[str, Any]:
    errors = validate_path_allowlist(path)
    exposure, privacy_reasons = privacy_decision(path, git_mode)
    ext = _extension(path)
    name = PurePosixPath(path).name.lower()
    language = LANGUAGE_BY_EXTENSION.get(ext, "binary" if ext in BINARY_EXTENSIONS else "text")
    if name in SPECIAL_CONFIG_NAMES or path in SPECIAL_CONFIG_PATHS:
        language = "config"
    elif _is_license_name(name):
        language = "text"
    elif JSONC_CONFIG_NAME_RE.match(name):
        language = "jsonc"

    roles: set[str] = set()
    if language in SOURCE_LANGUAGES:
        roles.add("source")
    if language == "markdown" or _is_license_name(name):
        roles.add("documentation")
    # JSONC is JSON with comments: structured data, never executable source.
    if language in {"json", "jsonc", "jsonl", "toml", "yaml", "csv", "ini", "config"}:
        roles.add("structured_data")
    if path.startswith(WORKFLOW_PREFIX):
        roles.add("workflow")
    if _is_manifest(path):
        roles.add("manifest")
    if _is_dependency_file(path):
        roles.add("dependency")
    if _is_test(path):
        roles.add("test")
    if _is_dataset(path, language):
        roles.add("dataset")
    if language == "binary":
        roles.add("binary")
    if not roles:
        roles.add("config" if language in {"config", "text", "manifest"} else "source")

    return {
        "language": language,
        "roles": sorted(roles),
        "privacy_exposure": exposure,
        "privacy_reasons": privacy_reasons,
        "classification_errors": errors,
        "media_type": (
            "text/plain"
            if path in SPECIAL_CONFIG_PATHS or language in {"text", "sql"}
            else mimetypes.guess_type(path)[0] or "application/octet-stream"
        ),
    }


def _is_test(path: str) -> bool:
    p = PurePosixPath(path)
    return "tests" in p.parts or p.name.startswith("test_") or ".test." in p.name or ".spec." in p.name


def _is_manifest(path: str) -> bool:
    name = PurePosixPath(path).name.lower()
    return name in {
        "manifest.in",
        "package-lock.json",
        "package.json",
        "pyproject.toml",
        "hosting.json",
        "wrangler.json",
        "wrangler.jsonc",
    } or name.endswith("manifest.json")


def _is_dependency_file(path: str) -> bool:
    name = PurePosixPath(path).name.lower()
    return (
        name in {"package.json", "package-lock.json", "pyproject.toml", "setup.py"}
        or name.startswith("requirements")
        or name.endswith(".lock")
    )


def _is_dataset(path: str, language: str) -> bool:
    if language not in {"csv", "json", "jsonl", "sql", "toml", "yaml"}:
        return False
    if path in SAFE_ROOT_DATA:
        return True
    return path.startswith(SAFE_DATA_PREFIXES) and any(
        token in path.lower() for token in ("data", "fixture", "sample", "quality", "registry", "question", "corpus")
    )


def documentation_status(path: str, first_lines: list[str]) -> tuple[str, list[str]]:
    """Conservative status classification with owner and explicit ADR-status precedence."""

    lower = path.lower()
    name = PurePosixPath(path).name
    header = "\n".join(first_lines[:80]).lower()
    if lower.startswith(".claude/agent-memory/"):
        return "repository_memory_cache", ["tracked_repository_history_not_machine_local_claude_memory"]
    if path in CURRENT_OWNER_DOCS:
        return "current_owner", ["registered_current_owner"]
    if lower.startswith("docs/decisions/") and name[:4].isdigit():
        if re.search(r"status[^\n]{0,30}\baccepted\b", header):
            return "accepted_decision", ["accepted_status_in_adr_header"]
        if re.search(r"status[^\n]{0,30}\bproposed\b", header):
            return "proposed_decision", ["proposed_status_in_adr_header"]
        if re.search(r"status[^\n]{0,30}\b(?:rejected|declined)\b", header):
            return "rejected_decision", ["rejected_status_in_adr_header"]
        if re.search(r"status[^\n]{0,30}\b(?:superseded|deprecated)\b", header):
            return "superseded_decision", ["superseded_status_in_adr_header"]
        return "decision_requires_revalidation", ["adr_status_not_recognized"]
    if HISTORICAL_NAME_RE.search(lower):
        return "historical", ["dated_or_historical_name"]
    if PLAN_NAME_RE.search(lower) or "plan" in name.lower():
        return "requires_revalidation", ["plan_is_not_current_queue"]

    if any(marker in header for marker in ("historical record", "superseded", "status: closed", "**closed")):
        return "historical", ["explicit_historical_marker"]
    if "status: current" in header or "**current" in header:
        return "current_declared", ["explicit_current_marker_not_owner_precedence"]
    return "reference", ["no_current_owner_or_historical_marker"]
