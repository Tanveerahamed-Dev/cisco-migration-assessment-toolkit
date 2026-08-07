"""Small build guard: a published AssessHub entry point must include its runtime UI."""

import hashlib
import re
from pathlib import Path

from setuptools import setup

_ROOT = Path(__file__).resolve().parent
_REQUIRED_RUNTIME_ASSETS = (
    _ROOT / "webapp" / "frontend" / "dist" / "index.html",
    _ROOT / "webapp" / "sample_data" / "sample_fleet.snapshot.json",
    _ROOT / "cisco_toolkit" / "data" / "registry_manifest.json",
    _ROOT / "cisco_toolkit" / "data" / "oui_registry.tsv.gz",
    _ROOT / "cisco_toolkit" / "data" / "port_registry.tsv.gz",
    _ROOT / "cisco_toolkit" / "data" / "eol-bulletins.json",
    _ROOT / "reference-data" / "official-sources" / "cisco" / "eol-bulletins.json",
)
_missing = [str(path.relative_to(_ROOT)) for path in _REQUIRED_RUNTIME_ASSETS if not path.is_file()]
_frontend_index = _ROOT / "webapp" / "frontend" / "dist" / "index.html"
if _frontend_index.is_file():
    _index_text = _frontend_index.read_text(encoding="utf-8")
    _asset_references = {
        match.group(1).lstrip("/")
        for match in re.finditer(
            r"""(?:src|href)\s*=\s*["']([^"']+)["']""",
            _index_text,
            flags=re.IGNORECASE,
        )
        if match.group(1).lstrip("/").startswith("assets/")
    }
    if not _asset_references:
        _missing.append("webapp/frontend/dist/index.html (no local asset references)")
    _missing.extend(
        f"webapp/frontend/dist/{reference}"
        for reference in sorted(_asset_references)
        if not (_frontend_index.parent / reference).is_file()
    )
if _missing:
    raise RuntimeError(
        "refusing to build an incomplete distribution; missing runtime assets: "
        + ", ".join(_missing)
        + ". Build the AssessHub frontend before packaging."
    )

_runtime_eol_evidence = _ROOT / "cisco_toolkit" / "data" / "eol-bulletins.json"
_retained_eol_evidence = (
    _ROOT / "reference-data" / "official-sources" / "cisco" / "eol-bulletins.json"
)
_expected_eol_sha256 = (
    "7683b29e66d3e5b39d89407e60a5f08ffbf8ef9f19ab029279ffc9d0861349c3"
)
_runtime_eol_bytes = _runtime_eol_evidence.read_bytes()
if (
    _runtime_eol_bytes != _retained_eol_evidence.read_bytes()
    or hashlib.sha256(_runtime_eol_bytes).hexdigest() != _expected_eol_sha256
):
    raise RuntimeError(
        "refusing to build with divergent Cisco EoL evidence; "
        "cisco_toolkit/data/eol-bulletins.json must be the exact code-pinned copy "
        "of reference-data/official-sources/cisco/eol-bulletins.json"
    )

setup()
