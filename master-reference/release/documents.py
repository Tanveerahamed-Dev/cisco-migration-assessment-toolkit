"""Pure renderers for release documents and the self-contained reference."""

from __future__ import annotations

import base64
import hashlib
import html
from collections import Counter
from typing import Any, Iterable

from .compiler_bundle import CompilerBundle
from .content_bundle import ContentBundle
from .model import canonical_json


def capabilities(content: ContentBundle) -> list[dict[str, Any]]:
    return [
        {**entry, "domain_ref": domain["id"]}
        for domain in content.capabilities["domains"]
        for entry in domain["entries"]
    ]


def opportunities(content: ContentBundle) -> list[dict[str, Any]]:
    return list(content.governance["opportunity_portfolio"]["items"])


def _line(value: object) -> str:
    return " ".join(str(value if value is not None else "").replace("|", "\\|").split())


def _bullets(values: Iterable[object]) -> str:
    rows = [f"- {_line(value)}" for value in values]
    return "\n".join(rows) if rows else "- None declared."


def machine_reference(
    bundle: CompilerBundle,
    content: ContentBundle,
    sbom: dict[str, Any],
    release_status: str,
) -> dict[str, Any]:
    caps = capabilities(content)
    state_counts = Counter(str(item.get("state", "unknown")) for item in caps)
    return {
        "schema_version": "1.0.0",
        "kind": "atlas-master-reference",
        "status": release_status,
        "source_binding": {
            "source_commit": bundle.source_commit,
            "head_tree_oid": bundle.manifest["head_tree_oid"],
            "index_digest": bundle.manifest["index_digest"],
            "source_tree_digest": bundle.source_tree_digest,
            "tracked_worktree_dirty": False,
            "compiler_manifest_sha256": hashlib.sha256(canonical_json(bundle.manifest)).hexdigest(),
        },
        "completeness": bundle.completeness,
        "repository": {
            "record_counts": {name: item["record_count"] for name, item in sorted(bundle.manifest["groups"].items())},
            "graphify": bundle.manifest["graphify_metadata"],
        },
        "knowledge": {
            "core": content.core,
            "capability_catalog": content.capabilities,
            "delivery_governance": content.governance,
            "open_horizon_register": content.horizon,
        },
        "summaries": {
            "capability_state_counts": dict(sorted(state_counts.items())),
            "gap_count": len(content.governance["gaps"]),
            "decision_count": len(content.governance["decision_queue"]),
            "opportunity_count": len(opportunities(content)),
            "horizon_signal_count": len(content.horizon["signals"]),
            "sbom_component_count": len(sbom["components"]),
        },
        "truth_limits": [
            "Catalog inclusion is not an implementation claim.",
            "Synthetic evidence is not field validation.",
            "Graphify extraction is not runtime truth.",
            "Python dependency declarations are not a transitive lock resolution.",
            "This release contains no raw Vault, client, device, credential, or machine-local memory content.",
        ],
    }


def owner_handbook(
    bundle: CompilerBundle,
    content: ContentBundle,
    pdf_status: str,
    release_status: str,
) -> str:
    caps = capabilities(content)
    states = Counter(str(item.get("state", "unknown")) for item in caps)
    gaps = Counter(str(item.get("priority", "unprioritized")) for item in content.governance["gaps"])
    outcomes = content.core.get("outcomes", [])
    decisions = content.governance["decision_queue"]
    acceptance = bundle.completeness.get("acceptance_gates", [])
    failed_acceptance = [
        str(item.get("name")) for item in acceptance if item.get("passed") is not True
    ]
    decision_sections = "\n".join(
        "\n".join(
            [
                f"### `{item['id']}` — {_line(item['title'])}",
                "",
                f"- Status: `{item['status']}`",
                f"- Authority: {_line(item['authority'])}",
                f"- Current recommendation: {_line(item['current_recommendation'])}",
                "",
            ]
        )
        for item in decisions
    )
    return f"""# Atlas Owner Handbook

## Release identity

- Source commit: `{bundle.source_commit}`
- Source-tree digest: `{bundle.source_tree_digest}`
- Structural compiler invariants: `passed`
- Semantic acceptance: `{len(acceptance) - len(failed_acceptance)}/{len(acceptance)} passed`
- Tracked worktree at compilation: `clean`
- Release status: `{release_status}`
- Independent verification verdict: `BLOCK`
- Master Reference PDF gate: `{pdf_status}`

This handbook is a decision-oriented entry point into the exact repository
projection above. It is not a second source of truth. Follow cited owner paths,
compiler records, and the release manifest when a summary and an owner differ.

Semantic gates still blocking approval: `{_line(', '.join(failed_acceptance) or 'none')}`.

## Purpose and protected boundaries

{_line(content.core.get('scope'))}

{_bullets(item.get('statement') if isinstance(item, dict) else item for item in content.core.get('non_goals', []))}

Protected constraints remain non-waivable in this output: no device writes, no
raw Vault/client ingestion, no runtime external AI or analytics, no advisory
content promoted to evidence, and no public publication without explicit owner
authority.

## Nine outcome contracts

| Outcome | Success signal |
|---|---|
{chr(10).join(f"| `{item['id']}` — {_line(item['title'])} | {_line(item['success_signal'])} |" for item in outcomes)}

## Capability truth

The closed catalog has **{len(caps)}** capability cells across
**{len(content.capabilities['domains'])}** declared domains. State is a truth
classification, not a score.

| State | Cells |
|---|---:|
{chr(10).join(f'| `{state}` | {count} |' for state, count in sorted(states.items()))}

## Gap queue

There are **{len(content.governance['gaps'])}** explicit gaps.

| Priority | Gaps |
|---|---:|
{chr(10).join(f'| `{priority}` | {count} |' for priority, count in sorted(gaps.items()))}

Start with the capability/gap report. Each gap retains its problem, disposition,
next actions, acceptance evidence, and human owner role.

## Decisions requiring human authority

{decision_sections}

## How to use this release

1. Read `atlas-reference.json` for the canonical machine projection.
2. Use `source-symbol-index.json` to locate any tracked path or symbol.
3. Use `capability-gap-report.md` to distinguish current, partial, missing,
   gated, excluded, and unknown scope.
4. Use `decisions-opportunities.md` for transparent human prioritization.
5. Instantiate `enhancement-brief-template.md` before changing a capability.
6. Verify every file against `release-manifest.json` before relying on it.
7. Treat `master-reference.pdf` as absent unless the PDF gate says supplied.

## Evidence interpretation

- Covered does not mean correct.
- Missing evidence does not mean zero or clean.
- Advisory and horizon material cannot prove current product support.
- Unknown remains unknown until owned evidence changes its state.
- Unsigned previews are review artifacts, not verified releases.
"""


def engineering_dossier(
    bundle: CompilerBundle,
    content: ContentBundle,
    sbom: dict[str, Any],
    pdf_status: str,
    release_status: str,
) -> str:
    counts = {name: item["record_count"] for name, item in sorted(bundle.manifest["groups"].items())}
    parsing = bundle.completeness.get("parsing", {})
    graph = bundle.completeness.get("graphify", {})
    acceptance = bundle.completeness.get("acceptance_gates", [])
    failed_acceptance = [str(item.get("name")) for item in acceptance if item.get("passed") is not True]
    return f"""# Atlas Engineering Dossier

## Exact-source contract

| Property | Value |
|---|---|
| Source commit | `{bundle.source_commit}` |
| HEAD tree object | `{bundle.manifest['head_tree_oid']}` |
| Git index digest | `{bundle.manifest['index_digest']}` |
| Source-tree digest | `{bundle.source_tree_digest}` |
| Compiler schema | `{bundle.manifest['schema_version']}` |
| Release status | `{release_status}` |
| PDF gate | `{pdf_status}` |
| Semantic acceptance | `{len(acceptance) - len(failed_acceptance)}/{len(acceptance)} passed` |
| Independent verdict | `BLOCK` |

The release builder re-read every compiler chunk named by the manifest and
validated its byte length, SHA-256, envelope binding, record count, per-chunk
record digest, and aggregate group digest. A dirty compiler projection is
refused.

Structural accounting is not Level 2-4 semantic proof. Blocking semantic gates:
`{_line(', '.join(failed_acceptance) or 'none')}`.

## Whole-repository accounting

| Record group | Records |
|---|---:|
{chr(10).join(f'| `{name}` | {count} |' for name, count in counts.items())}

Compiler parsing status: `{_line(parsing.get('status_counts', {}))}`.
Lines with explicit unresolved reasons:
`{parsing.get('lines_with_explicit_unresolved_reasons', 'unknown')}`.

## Static and graph projection

- Graph status: `{graph.get('status', 'unknown')}`
- Graph available: `{graph.get('available', False)}`
- Graph stale: `{graph.get('stale', 'unknown')}`
- Projected nodes: `{graph.get('projected_nodes', 0)}`
- Projected edges: `{graph.get('projected_edges', 0)}`

Graphify remains a static/extracted view and cannot establish runtime truth.
Synthetic runtime receipts must remain independently labelled.

## Supply chain

The CycloneDX 1.5 BOM contains **{len(sbom['components'])}** component records.
NPM direct and transitive components come from the two repository package-lock
v3 files. Python components are exact declarations from `pyproject.toml` and
requirements files, explicitly labelled `declared-unlocked`; no transitive
Python resolution or vulnerability result is fabricated.

## Reproducibility class

- Canonical JSON: UTF-8, sorted keys, compact separators, terminal LF.
- Archives: lexically sorted entries, 1980-01-01 timestamps, mode 0644,
  deterministic DEFLATE level 9.
- No build time, host name, absolute path, environment package inventory, or
  network result enters deterministic outputs.
- Compiler chunks and curated contracts are copied byte-for-byte into the
  preservation pack.
- Signing consumes an owner-supplied Ed25519 key outside the repository; this
  builder creates and stores no private keys.

## Privacy boundary

Only compiler-manifest-referenced files, four curated content contracts, two
NPM lockfiles, `pyproject.toml`, and three requirements files are read. Symlink
components and path traversal are refused. Source text already classified safe
by the compiler is retained only inside its preservation projection; handbook,
HTML, and machine summary outputs do not reproduce whole source files.

## Known gates and honest limitations

- PDF status is `{pdf_status}`; no PDF claim exists without supplied renderer output.
- The release remains unsigned until an independent owner signs the exact
  `release-manifest.json` bytes.
- Signature verification proves integrity and key possession, not correctness,
  human approval, public authority, field validation, or vulnerability absence.
- SBOM vulnerability status requires a separate, freshness-bound advisory scan.
- No release output changes assessment truth or writes a device, Vault, or
  client evidence store.
"""


def source_symbol_index(bundle: CompilerBundle) -> dict[str, Any]:
    files = []
    for item in bundle.records.get("files", []):
        files.append(
            {
                key: item.get(key)
                for key in (
                    "id",
                    "path",
                    "git_mode",
                    "language",
                    "roles",
                    "privacy_exposure",
                    "parse_status",
                    "parser",
                    "parser_mode",
                    "size_bytes",
                    "content_digest",
                    "line_count",
                    "nonblank_line_count",
                    "documentation_status",
                    "unresolved_reasons",
                )
                if key in item
            }
        )
    symbols = list(bundle.records.get("symbols", []))
    return {
        "schema_version": "1.0.0",
        "source_commit": bundle.source_commit,
        "source_tree_digest": bundle.source_tree_digest,
        "files": sorted(files, key=lambda item: str(item.get("path", ""))),
        "symbols": sorted(symbols, key=lambda item: str(item.get("id", ""))),
        "routes": sorted(bundle.records.get("routes", []), key=lambda item: str(item.get("id", ""))),
        "components": sorted(bundle.records.get("components", []), key=lambda item: str(item.get("id", ""))),
        "tests": sorted(bundle.records.get("tests", []), key=lambda item: str(item.get("id", ""))),
        "workflows": sorted(bundle.records.get("workflows", []), key=lambda item: str(item.get("id", ""))),
        "datasets": sorted(bundle.records.get("datasets", []), key=lambda item: str(item.get("id", ""))),
        "binaries": sorted(bundle.records.get("binaries", []), key=lambda item: str(item.get("id", ""))),
        "line_mapping": {
            "record_count": bundle.manifest["groups"]["lines"]["record_count"],
            "records_digest": bundle.manifest["groups"]["lines"]["records_digest"],
            "location": "preservation-pack/compiler/chunks/lines/",
        },
        "safe_source_text": {
            "record_count": bundle.manifest["groups"]["source_text"]["record_count"],
            "records_digest": bundle.manifest["groups"]["source_text"]["records_digest"],
            "location": "preservation-pack/compiler/chunks/source_text/",
        },
    }


def source_symbol_markdown(index: dict[str, Any]) -> str:
    files = index["files"]
    symbols = index["symbols"]
    header = f"""# Whole-Repository Source and Symbol Index

- Source commit: `{index['source_commit']}`
- Source-tree digest: `{index['source_tree_digest']}`
- Tracked files: **{len(files)}**
- Symbols: **{len(symbols)}**
- Line records: **{index['line_mapping']['record_count']}**
- Safe source records: **{index['safe_source_text']['record_count']}**

Exact line and safe-source envelopes live in the preservation pack. This
human index intentionally does not duplicate every source line.

## Files

| Path | Language | Exposure | Parse status | Nonblank lines |
|---|---|---|---|---:|
"""
    rows = [
        f"| `{_line(item.get('path'))}` | `{_line(item.get('language'))}` | `{_line(item.get('privacy_exposure'))}` | `{_line(item.get('parse_status'))}` | {item.get('nonblank_line_count', '')} |"
        for item in files
    ]
    symbol_rows = [
        f"| `{_line(item.get('id'))}` | `{_line(item.get('name') or item.get('qualified_name'))}` | `{_line(item.get('path'))}` | `{_line(item.get('kind'))}` |"
        for item in symbols
    ]
    return header + "\n".join(rows) + "\n\n## Symbols\n\n| Stable ID | Name | Path | Kind |\n|---|---|---|---|\n" + "\n".join(symbol_rows) + "\n"


def capability_gap_report(content: ContentBundle) -> str:
    gap_by_id = {item["id"]: item for item in content.governance["gaps"]}
    sections = [
        "# Capability and Gap Report",
        "",
        "Catalog presence means classified scope, not implementation. Only `current` with cited owners is an end-to-end support claim for its stated scope.",
        "",
    ]
    for domain in content.capabilities["domains"]:
        sections.extend([f"## `{domain['id']}`", "", "| Capability | State | Current scope | Owners | Gaps |", "|---|---|---|---|---|"])
        for item in domain["entries"]:
            sections.append(
                f"| `{item['id']}` — {_line(item['title'])} | `{item['state']}` | {_line(item.get('current_scope'))} | {_line(', '.join(item.get('owner_refs', [])))} | {_line(', '.join(item.get('gap_refs', [])))} |"
            )
        sections.append("")
    sections.extend(["# Gap dossiers", ""])
    for gap in sorted(gap_by_id.values(), key=lambda item: (item["priority"], item["id"])):
        sections.extend(
            [
                f"## `{gap['id']}` — {_line(gap['title'])}",
                "",
                f"- Priority: `{gap['priority']}`",
                f"- Disposition: `{gap['disposition']}`",
                f"- Owner role: {_line(gap['owner_role'])}",
                "",
                _line(gap["problem"]),
                "",
                "### Next actions",
                "",
                _bullets(gap.get("next_actions", [])),
                "",
                "### Acceptance evidence",
                "",
                _bullets(gap.get("acceptance_evidence", [])),
                "",
            ]
        )
    return "\n".join(sections) + "\n"


def decisions_opportunities(content: ContentBundle) -> str:
    sections = [
        "# Decisions and Opportunities",
        "",
        "Opportunity axes are transparent discussion inputs. They are not combined into a hidden score, and they do not override dependencies, safety gates, or human authority.",
        "",
        "## Decision queue",
        "",
    ]
    for item in content.governance["decision_queue"]:
        sections.extend(
            [
                f"### `{item['id']}` — {_line(item['title'])}",
                "",
                f"- Status: `{item['status']}`",
                f"- Authority: {_line(item['authority'])}",
                f"- Current recommendation: {_line(item['current_recommendation'])}",
                f"- Gap references: {_line(', '.join(item.get('gap_refs', [])))}",
                "",
                "Options:",
                "",
                _bullets(item.get("options", [])),
                "",
                "Evidence needed:",
                "",
                _bullets(item.get("evidence_needed", [])),
                "",
            ]
        )
    sections.extend(["## Opportunity portfolio", ""])
    for item in opportunities(content):
        axes = ", ".join(f"{name}={value}" for name, value in sorted(item["axes"].items()))
        sections.extend(
            [
                f"### `{item['id']}` — {_line(item['title'])}",
                "",
                f"- Horizon: `{item['horizon']}`",
                f"- Gaps: {_line(', '.join(item.get('gap_refs', [])))}",
                f"- Axes: `{axes}`",
                f"- Notes: {_line(item.get('axis_notes'))}",
                "",
            ]
        )
    return "\n".join(sections) + "\n"


def enhancement_brief(content: ContentBundle, gap_id: str | None) -> str:
    gap = next((item for item in content.governance["gaps"] if item["id"] == gap_id), None)
    if gap_id and gap is None:
        raise ValueError(f"unknown gap id: {gap_id}")
    title = f" for `{gap['id']}`" if gap else ""
    current = _line(gap["problem"]) if gap else "[Cite current symbol/owner behavior and repository evidence.]"
    actions = _bullets(gap["next_actions"]) if gap else "- [Candidate action]"
    acceptance = _bullets(gap["acceptance_evidence"]) if gap else "- [Executable acceptance evidence]"
    return f"""# Enhancement Brief{title}

## Binding

- Baseline commit: `[exact commit]`
- Source-tree digest: `[compiler digest]`
- Desired outcome: `[measurable owner outcome]`
- Authority: `[human owner and expiry]`
- Protected constraints: no device writes; no raw Vault/client ingestion; no self-approval; no unsupported publication.

## Current behavior

{current}

### Current owners and symbols

- `[owner id → path/symbol/range]`

### Evidence and uncertainty

- Observed evidence: `[receipt IDs]`
- Synthetic-only evidence: `[receipt IDs]`
- Unknown or stale: `[explicit reasons]`

## Alternatives

1. Do nothing — `[impact and trigger to reconsider]`
2. Smallest safe vertical slice — `[scope]`
3. Broader program — `[scope and why it may be premature]`

## Candidate next actions

{actions}

## Dependency closure

- Affected files and symbols: `[stable IDs]`
- Claims and owners: `[stable IDs]`
- GUI and artifacts: `[routes/writers]`
- Architecture/invariants: `[IDs and required contract changes]`
- Migrations/upcasters: `[if applicable]`

## Tests and gates

{acceptance}

- Counterexample/negative tests: `[cases]`
- Privacy/security scan: `[receipt]`
- Independent verifier: `[different human/agent]`
- Exact clean source rebuild: `[receipt]`

## Rollback and residual limitations

- Kill/rollback conditions: `[conditions]`
- Recovery path: `[deterministic steps]`
- Still unsupported after this slice: `[explicit list]`
- Outcome review/PIR: `[measure, owner, effective time]`
"""


def agent_pack(bundle: CompilerBundle, content: ContentBundle) -> str:
    constraints = [item.get("statement") for item in content.governance.get("invariants", [])]
    return f"""# Atlas Agent Pack

## Immutable task-envelope baseline

```json
{{
  "baseline_commit": "{bundle.source_commit}",
  "source_tree_digest": "{bundle.source_tree_digest}",
  "objective": "[bounded objective]",
  "allowed_owners": ["[owner id]"],
  "allowed_paths": ["[path prefix]"],
  "allowed_actions": ["read", "edit", "test"],
  "prohibited_actions": ["device-write", "vault-write", "client-data-ingest", "public-publish"],
  "required_tests": ["[command]"],
  "authority": "[human authority]",
  "expires": "[ISO-8601 instant]"
}}
```

An agent must stop when the baseline is stale, the requested owner/path falls
outside the envelope, or a protected constraint would be crossed.

## Completion receipt

```json
{{
  "baseline_commit": "{bundle.source_commit}",
  "result_tree": "[exact tree]",
  "diff_digest": "[sha256]",
  "changed_owners": ["[owner id]"],
  "manifest_delta": ["[record delta]"],
  "commands": [{{"command": "[exact command]", "exit_code": 0}}],
  "artifacts": [{{"path": "[path]", "sha256": "[digest]"}}],
  "conflicts": [],
  "exceptions": [],
  "external_actions": []
}}
```

## Non-negotiable invariants

{_bullets(constraints)}

## Query order

1. Read the current owner named by `docs/ssot.md`.
2. Resolve the path/symbol through `source-symbol-index.json`.
3. Follow compiler line, call, claim, test, and consumer records in the
   preservation pack.
4. Keep current and historical documents distinct.
5. Abstain when evidence is missing; never turn absence into health.
"""


def self_contained_html(bundle: CompilerBundle, content: ContentBundle) -> bytes:
    caps = capabilities(content)
    states = Counter(str(item.get("state", "unknown")) for item in caps)
    search_script = """(()=>{const q=document.querySelector('#q');const rows=[...document.querySelectorAll('[data-search]')];const apply=()=>{const s=q.value.trim().toLowerCase();for(const r of rows)r.hidden=!!s&&!r.dataset.search.includes(s)};q.addEventListener('input',apply)})();"""
    script_hash = base64.b64encode(hashlib.sha256(search_script.encode()).digest()).decode()
    capability_rows = "".join(
        f'<tr data-search="{html.escape((_line(item["id"]) + " " + _line(item["title"]) + " " + _line(item["state"]) + " " + _line(item["domain_ref"])).lower(), quote=True)}"><td><code>{html.escape(item["id"])}</code><br>{html.escape(_line(item["title"]))}</td><td><span class="state {html.escape(item["state"])}">{html.escape(item["state"])}</span></td><td>{html.escape(_line(item.get("current_scope")))}</td><td>{html.escape(", ".join(item.get("gap_refs", [])))}</td></tr>'
        for item in caps
    )
    gap_cards = "".join(
        f'<details data-search="{html.escape((_line(item["id"]) + " " + _line(item["title"]) + " " + _line(item["problem"])).lower(), quote=True)}"><summary><code>{html.escape(item["id"])}</code> · {html.escape(_line(item["title"]))} <b>{html.escape(item["priority"])}</b></summary><p>{html.escape(_line(item["problem"]))}</p><p><strong>Disposition:</strong> {html.escape(item["disposition"])} · <strong>Owner:</strong> {html.escape(_line(item["owner_role"]))}</p></details>'
        for item in content.governance["gaps"]
    )
    outcomes = "".join(
        f'<article><small>{html.escape(item["id"])}</small><h3>{html.escape(_line(item["title"]))}</h3><p>{html.escape(_line(item["success_signal"]))}</p></article>'
        for item in content.core["outcomes"]
    )
    state_cards = "".join(f'<li><b>{count}</b><span>{html.escape(state)}</span></li>' for state, count in sorted(states.items()))
    css = """
:root{color-scheme:dark;--bg:#07111a;--panel:#0d1d29;--line:#254253;--text:#e8f2f7;--muted:#9db5c3;--mint:#58e6b2;--amber:#ffc568;font:16px/1.55 ui-sans-serif,system-ui,sans-serif}*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 90% 0,#16334b 0,transparent 35rem),var(--bg);color:var(--text)}header,main,footer{max-width:1180px;margin:auto;padding:2rem}header{padding-top:4rem}.eyebrow{color:var(--mint);letter-spacing:.14em;text-transform:uppercase;font-size:.75rem}h1{font-size:clamp(2.5rem,7vw,5rem);line-height:.95;max-width:13ch;margin:.4rem 0 1rem}h2{margin-top:3.5rem}p{max-width:76ch;color:var(--muted)}code{color:#bfe8ff}input{width:100%;padding:1rem;border:1px solid var(--line);border-radius:.7rem;background:#07131d;color:var(--text);font:inherit;position:sticky;top:.5rem;z-index:2}.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(8rem,1fr));gap:.75rem;padding:0;list-style:none}.stats li,article,details{border:1px solid var(--line);background:color-mix(in srgb,var(--panel),transparent 10%);border-radius:.8rem;padding:1rem}.stats b{display:block;font-size:2rem}.stats span{color:var(--muted)}.outcomes{display:grid;grid-template-columns:repeat(auto-fit,minmax(15rem,1fr));gap:.75rem}article h3{margin:.4rem 0}table{border-collapse:collapse;width:100%;font-size:.9rem}th,td{padding:.8rem;border-bottom:1px solid var(--line);vertical-align:top;text-align:left}th{position:sticky;top:4.2rem;background:var(--bg)}.table{overflow:auto;max-height:70vh;border:1px solid var(--line);border-radius:.8rem}.state{display:inline-block;padding:.15rem .5rem;border-radius:1rem;border:1px solid var(--line)}.state.current{color:var(--mint)}.state.missing,.state.unknown{color:var(--amber)}details{margin:.6rem 0}summary{cursor:pointer;color:var(--text)}[hidden]{display:none!important}footer{border-top:1px solid var(--line);color:var(--muted);margin-top:4rem}@media(max-width:600px){header,main,footer{padding:1.2rem}th:nth-child(3),td:nth-child(3){min-width:20rem}}@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important}}@media print{:root{color-scheme:light;--bg:#fff;--panel:#fff;--line:#bbb;--text:#111;--muted:#333}input{display:none}.table{max-height:none;overflow:visible}th{position:static}details{break-inside:avoid}details>*{display:block!important}}
""".strip()
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow,noarchive"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'sha256-{script_hash}'; img-src data:; connect-src 'none'; font-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"><title>Atlas Master Reference · {bundle.source_commit[:12]}</title><style>{css}</style></head>
<body><header><div class="eyebrow">Exact-source executive navigation · blocked unsigned preview</div><h1>Orient to the system. Follow the evidence bundle for completeness.</h1><p>Repository commit <code>{bundle.source_commit}</code><br>Source-tree digest <code>{bundle.source_tree_digest}</code></p><p>This self-contained page is the decision-oriented entry point, not the complete Source Explorer. The adjacent offline ZIP carries every safe line/source/symbol compiler record.</p></header><main>
<section aria-labelledby="truth"><h2 id="truth">Capability truth</h2><ul class="stats">{state_cards}</ul><p>{len(caps)} classified cells across {len(content.capabilities['domains'])} declared domains. Inclusion is not an implementation claim.</p></section>
<section aria-labelledby="outcomes"><h2 id="outcomes">Outcome contracts</h2><div class="outcomes">{outcomes}</div></section>
<label for="q"><h2>Search catalog and gaps</h2></label><input id="q" type="search" autocomplete="off" placeholder="Capability, protocol, design, gap…">
<section aria-labelledby="catalog"><h2 id="catalog">Complete capability catalog</h2><div class="table"><table><thead><tr><th>Capability</th><th>State</th><th>Current scope</th><th>Gap</th></tr></thead><tbody>{capability_rows}</tbody></table></div></section>
<section aria-labelledby="gaps"><h2 id="gaps">Gap dossiers</h2>{gap_cards}</section>
<section><h2>Integrity and limits</h2><p>This HTML contains no external asset, request, analytics, persistence, client evidence, Vault content, or runtime AI. Verify its SHA-256 through the adjacent release manifest. It remains a blocked unsigned preview; structural accounting, the complete machine projection, independent review, and publication authority are separate gates.</p></section>
</main><footer>Atlas Master Reference · source {bundle.source_commit[:12]} · deterministic offline HTML</footer><script>{search_script}</script></body></html>"""
    return page.encode("utf-8")
