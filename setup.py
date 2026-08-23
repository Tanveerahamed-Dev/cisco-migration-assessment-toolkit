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
    _ROOT / "cisco_toolkit" / "data" / "qcp-001.experimental.json",
    _ROOT / "cisco_toolkit" / "data" / "atlas-r1-executable-bundle.json",
    _ROOT / "cisco_toolkit" / "data" / "atlas-r1-source-bundle.json",
    _ROOT / "cisco_toolkit" / "data" / "atlas-r1-retrospective-after.json",
    _ROOT / "cisco_toolkit" / "data" / "atlas-r1-retrospective-before.json",
    _ROOT / "cisco_toolkit" / "data" / "atlas-r1-retrospective-comparison.json",
    _ROOT / "cisco_toolkit" / "data" / "atlas-r2-structural-tcb-census.v1.json",
    _ROOT / "cisco_toolkit" / "data" / "atlas-r2-dsl-prototype-denominator.v1.json",
    _ROOT / "cisco_toolkit" / "data" / "atlas-r2-dsl-prototype-input.v1.json",
    _ROOT / "cisco_toolkit" / "data" / "atlas-r2-dsl-prototype-pack.experimental.json",
    _ROOT / "cisco_toolkit" / "data" / "atlas-r2-dsl-prototype-program.v1.json",
    _ROOT / "cisco_toolkit" / "data" / "atlas-r2-dsl-prototype-tcb.v2.json",
    _ROOT / "cisco_toolkit" / "data" / "atlas-r2-dsl-prototype-measurements.v1.json",
    _ROOT / "cisco_toolkit" / "data" / "atlas-r2-runtime-inventory.reference.v1.json",
    _ROOT / "cisco_toolkit" / "data" / "atlas-r2-tcb-budget-proposal.v1.json",
    _ROOT / "cisco_toolkit" / "data" / "oui_registry.tsv.gz",
    _ROOT / "cisco_toolkit" / "data" / "port_registry.tsv.gz",
    _ROOT / "cisco_toolkit" / "data" / "eol-bulletins.json",
    _ROOT / "cisco_toolkit" / "data" / "traffic-intents.example.json",
    _ROOT / "cisco_toolkit" / "schemas" / "atlas-transition-contract-v1.schema.json",
    _ROOT / "cisco_toolkit" / "schemas" / "atlas-r2-structural-tcb-census-v1.schema.json",
    _ROOT / "cisco_toolkit" / "schemas" / "atlas-r2-execution-evidence-v1.schema.json",
    _ROOT / "cisco_toolkit" / "schemas" / "atlas-r2-tcb-budget-proposal-v1.schema.json",
    _ROOT / "cisco_toolkit" / "schemas" / "atlas-r2-transition-runtime-closure-v2.schema.json",
    _ROOT / "cisco_toolkit" / "schemas" / "atlas-r2-transition-workload-review-v1.schema.json",
    _ROOT / "cisco_toolkit" / "schemas" / "atlas-r2-windows-runtime-discovery-v1.schema.json",
    _ROOT / "cisco_toolkit" / "schemas" / "atlas-transition-runtime-inventory-v1.schema.json",
    _ROOT / "cisco_toolkit" / "transition_contract.py",
    _ROOT / "cisco_toolkit" / "transition_pack.py",
    _ROOT / "cisco_toolkit" / "transition_verifier.py",
    _ROOT / "cisco_toolkit" / "transition_legacy.py",
    _ROOT / "cisco_toolkit" / "transition_dsl.py",
    _ROOT / "cisco_toolkit" / "transition_tcb_review.py",
    _ROOT / "cisco_toolkit" / "transition_runtime_closure.py",
    _ROOT / "cisco_toolkit" / "transition_runtime_discovery.py",
    _ROOT / "cisco_toolkit" / "transition_runtime_inventory.py",
    _ROOT / "cisco_toolkit" / "transition_workload_review.py",
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
        + ". Restore or generate every listed runtime asset before packaging."
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
