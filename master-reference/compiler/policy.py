"""Strict path, file-kind, language, and privacy classification policy.

Only tracked paths under the known repository surface are accepted.  The Git
census cannot reach machine-local Claude memory or the user's Obsidian Vault.
Tracked ``.claude/agent-memory`` files are ordinary repository history/cache
and are intentionally line-mapped; that path is not the machine-local store.
"""

from __future__ import annotations

import mimetypes
import re
from pathlib import PurePosixPath
from typing import Any


ALLOWED_TOP_LEVEL_DIRECTORIES = frozenset(
    {
        ".claude",
        ".design-sync",
        ".github",
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
        ".md",
        ".mjs",
        ".mts",
        ".ps1",
        ".py",
        ".sh",
        ".spec",
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
    ".md": "markdown",
    ".mjs": "javascript",
    ".mts": "typescript",
    ".ps1": "powershell",
    ".py": "python",
    ".sh": "shell",
    ".spec": "python",
    ".svg": "svg",
    ".toml": "toml",
    ".ts": "typescript",
    ".tsbuildinfo": "json",
    ".tsx": "tsx",
    ".txt": "text",
    ".yaml": "yaml",
    ".yml": "yaml",
}

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
    if name in {"license", ".gitignore", ".gitattributes", ".graphifyignore"}:
        return []
    return [f"extension_not_allowlisted:{ext or '<none>'}"]


def classify_file(path: str, git_mode: str) -> dict[str, Any]:
    errors = validate_path_allowlist(path)
    exposure, privacy_reasons = privacy_decision(path, git_mode)
    ext = _extension(path)
    name = PurePosixPath(path).name.lower()
    language = LANGUAGE_BY_EXTENSION.get(ext, "binary" if ext in BINARY_EXTENSIONS else "text")
    if name in {".gitignore", ".gitattributes", ".graphifyignore"}:
        language = "config"
    elif name == "license":
        language = "text"

    roles: set[str] = set()
    if language in SOURCE_LANGUAGES:
        roles.add("source")
    if language == "markdown" or name in {"license"}:
        roles.add("documentation")
    if language in {"json", "jsonl", "toml", "yaml", "csv", "ini", "config"}:
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
        "media_type": mimetypes.guess_type(path)[0] or "application/octet-stream",
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
    return name in {"package.json", "package-lock.json", "pyproject.toml", "setup.py"} or name.startswith(
        "requirements"
    )


def _is_dataset(path: str, language: str) -> bool:
    if language not in {"csv", "json", "jsonl", "toml", "yaml"}:
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
