"""Deterministic, source-bound Atlas Master Reference PDF rendering.

The PDF is a human navigation and decision artifact.  It deliberately does not
embed source text: the compiler's content-hashed source chunks remain the owner
for line-level inspection.  This module consumes already validated
``CompilerBundle`` and ``ContentBundle`` objects, or loads them through the
strict release readers, and renders only accounting metadata and curated
repository-owned knowledge.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import shutil
import subprocess
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

from reportlab import Version as REPORTLAB_VERSION
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfdoc import PDFName, PDFString
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    BaseDocTemplate,
    CondPageBreak,
    Flowable,
    Frame,
    KeepTogether,
    LongTable,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.tableofcontents import TableOfContents

from governance.architecture import validate_contract

from .compiler_bundle import CompilerBundle, load_compiler_bundle
from .content_bundle import ContentBundle, load_content_bundle
from .model import canonical_json, sha256_bytes


_NAVY = colors.HexColor("#07131E")
_NAVY_2 = colors.HexColor("#0D2030")
_INK = colors.HexColor("#17212B")
_MUTED = colors.HexColor("#526575")
_LINE = colors.HexColor("#D5DFE6")
_PAPER = colors.HexColor("#F7FAFC")
_CYAN = colors.HexColor("#16C5D7")
_AMBER = colors.HexColor("#F5B942")
_RED = colors.HexColor("#B83B4A")
_GREEN = colors.HexColor("#1B7F65")
_WHITE = colors.white
_PAGE_WIDTH, _PAGE_HEIGHT = A4
_LEFT = 17 * mm
_RIGHT = 17 * mm
_TOP = 20 * mm
_BOTTOM = 17 * mm
_FRAME_WIDTH = _PAGE_WIDTH - _LEFT - _RIGHT


@dataclass(frozen=True)
class PdfReportResult:
    """Stable receipt for a generated report."""

    path: Path
    sha256: str
    bytes: int
    page_count: int
    source_commit: str
    source_tree_digest: str
    input_digest: str
    reportlab_version: str
    independent_verification_verdict: str


@dataclass(frozen=True)
class PdfInspection:
    """Machine checks that complement, but never replace, visual review."""

    path: Path
    page_count: int
    title: str
    author: str
    subject: str
    keywords: str
    source_commit_present: bool
    source_tree_digest_present: bool


def _ascii(value: object) -> str:
    """Return deterministic ReportLab-safe text using the built-in fonts."""

    text = str(value if value is not None else "")
    replacements = {
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2212": "-",
        "\u2192": "->",
        "\u2190": "<-",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2026": "...",
        "\u00a0": " ",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def _plain(value: object) -> str:
    return " ".join(_ascii(value).split())


def _markup(value: object) -> str:
    return html.escape(_plain(value), quote=True)


def _items(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_plain(item) for item in value if _plain(item)]


def _state_color(state: str) -> colors.Color:
    return {
        "current": _GREEN,
        "partial": colors.HexColor("#9A6810"),
        "missing": _RED,
        "gated": colors.HexColor("#7357A8"),
        "excluded": _MUTED,
        "unknown": colors.HexColor("#6F5B4B"),
        "pass": _GREEN,
        "passed": _GREEN,
        "blocked": _RED,
        "fail": _RED,
        "failed": _RED,
    }.get(state.lower(), _MUTED)


def _styles() -> dict[str, ParagraphStyle]:
    sample = getSampleStyleSheet()
    body = ParagraphStyle(
        "AtlasBody",
        parent=sample["BodyText"],
        fontName="Helvetica",
        fontSize=8.7,
        leading=12,
        textColor=_INK,
        spaceAfter=5,
        splitLongWords=True,
        allowWidows=False,
        allowOrphans=False,
    )
    return {
        "body": body,
        "small": ParagraphStyle(
            "AtlasSmall",
            parent=body,
            fontSize=7.3,
            leading=9.4,
            textColor=_MUTED,
            spaceAfter=3,
        ),
        "bullet": ParagraphStyle(
            "AtlasBullet",
            parent=body,
            leftIndent=11,
            firstLineIndent=-7,
            spaceAfter=3,
        ),
        "micro": ParagraphStyle(
            "AtlasMicro",
            parent=body,
            fontSize=6.2,
            leading=7.7,
            textColor=_MUTED,
            spaceAfter=0,
        ),
        "mono": ParagraphStyle(
            "AtlasMono",
            parent=body,
            fontName="Courier",
            fontSize=6.6,
            leading=8.3,
            textColor=_INK,
            splitLongWords=True,
            spaceAfter=0,
        ),
        "h1": ParagraphStyle(
            "AtlasHeading1",
            parent=sample["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=18,
            leading=21,
            textColor=_NAVY,
            spaceBefore=10,
            spaceAfter=9,
            keepWithNext=True,
        ),
        "h2": ParagraphStyle(
            "AtlasHeading2",
            parent=sample["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=12.5,
            leading=15,
            textColor=_NAVY_2,
            spaceBefore=9,
            spaceAfter=5,
            keepWithNext=True,
        ),
        "h3": ParagraphStyle(
            "AtlasHeading3",
            parent=sample["Heading3"],
            fontName="Helvetica-Bold",
            fontSize=9.4,
            leading=12,
            textColor=_INK,
            spaceBefore=7,
            spaceAfter=3,
            keepWithNext=True,
        ),
        "cover_kicker": ParagraphStyle(
            "AtlasCoverKicker",
            parent=body,
            fontName="Helvetica-Bold",
            fontSize=8,
            leading=10,
            tracking=1.4,
            textColor=_CYAN,
            alignment=TA_LEFT,
        ),
        "cover_title": ParagraphStyle(
            "AtlasCoverTitle",
            parent=body,
            fontName="Helvetica-Bold",
            fontSize=30,
            leading=33,
            textColor=_WHITE,
            alignment=TA_LEFT,
            spaceAfter=12,
        ),
        "cover_subtitle": ParagraphStyle(
            "AtlasCoverSubtitle",
            parent=body,
            fontSize=11,
            leading=15,
            textColor=colors.HexColor("#C7D6E0"),
        ),
        "cover_meta": ParagraphStyle(
            "AtlasCoverMeta",
            parent=body,
            fontName="Courier",
            fontSize=7.2,
            leading=10,
            textColor=_WHITE,
        ),
        "callout": ParagraphStyle(
            "AtlasCallout",
            parent=body,
            fontSize=8.4,
            leading=11.4,
            textColor=_INK,
        ),
        "toc": ParagraphStyle(
            "AtlasTOC",
            parent=body,
            fontSize=9,
            leading=13,
            leftIndent=0,
            firstLineIndent=0,
        ),
        "toc2": ParagraphStyle(
            "AtlasTOC2",
            parent=body,
            fontSize=8,
            leading=11,
            leftIndent=14,
            firstLineIndent=0,
            textColor=_MUTED,
        ),
        "table_head": ParagraphStyle(
            "AtlasTableHead",
            parent=body,
            fontName="Helvetica-Bold",
            fontSize=7.2,
            leading=9,
            textColor=_WHITE,
            spaceAfter=0,
        ),
        "table": ParagraphStyle(
            "AtlasTable",
            parent=body,
            fontSize=7.1,
            leading=9,
            spaceAfter=0,
        ),
        "table_mono": ParagraphStyle(
            "AtlasTableMono",
            parent=body,
            fontName="Courier",
            fontSize=6.2,
            leading=7.7,
            splitLongWords=True,
            spaceAfter=0,
        ),
        "center": ParagraphStyle(
            "AtlasCenter",
            parent=body,
            alignment=TA_CENTER,
        ),
    }


class _InvariantCanvas(canvas.Canvas):
    def __init__(self, *args: Any, metadata: dict[str, str], **kwargs: Any) -> None:
        kwargs["invariant"] = 1
        kwargs["pageCompression"] = 1
        super().__init__(*args, **kwargs)
        self.setTitle(metadata["title"])
        self.setAuthor(metadata["author"])
        self.setSubject(metadata["subject"])
        self.setKeywords(metadata["keywords"])
        self.setCreator(metadata["creator"])
        self._doc.Catalog.Lang = PDFString("en-US")
        self._doc.Catalog.PageMode = PDFName("UseOutlines")


class _AtlasDocTemplate(BaseDocTemplate):
    def __init__(
        self,
        filename: str,
        *,
        source_commit: str,
        metadata: dict[str, str],
        **kwargs: Any,
    ) -> None:
        super().__init__(
            filename,
            pagesize=A4,
            leftMargin=_LEFT,
            rightMargin=_RIGHT,
            topMargin=_TOP,
            bottomMargin=_BOTTOM,
            title=metadata["title"],
            author=metadata["author"],
            subject=metadata["subject"],
            keywords=metadata["keywords"],
            creator=metadata["creator"],
            **kwargs,
        )
        self.source_commit = source_commit
        self._bookmark_counts: dict[str, int] = {}
        frame = Frame(
            self.leftMargin,
            self.bottomMargin,
            self.width,
            self.height,
            id="atlas-body",
            leftPadding=0,
            rightPadding=0,
            topPadding=0,
            bottomPadding=0,
        )
        self.addPageTemplates([PageTemplate(id="atlas", frames=[frame], onPage=self._draw_page)])

    def beforeDocument(self) -> None:  # noqa: N802 - ReportLab hook name
        self._bookmark_counts = {}

    def _draw_page(self, canv: canvas.Canvas, doc: BaseDocTemplate) -> None:
        canv.saveState()
        if doc.page > 1:
            canv.setStrokeColor(_LINE)
            canv.setLineWidth(0.45)
            canv.line(_LEFT, _PAGE_HEIGHT - 13 * mm, _PAGE_WIDTH - _RIGHT, _PAGE_HEIGHT - 13 * mm)
            canv.setFillColor(_MUTED)
            canv.setFont("Helvetica-Bold", 6.7)
            canv.drawString(_LEFT, _PAGE_HEIGHT - 10.2 * mm, "ATLAS / MASTER REFERENCE")
            canv.setFont("Courier", 6.2)
            canv.drawRightString(
                _PAGE_WIDTH - _RIGHT,
                _PAGE_HEIGHT - 10.2 * mm,
                f"SOURCE {self.source_commit[:12]}",
            )
        canv.setStrokeColor(_LINE)
        canv.setLineWidth(0.45)
        canv.line(_LEFT, 11.5 * mm, _PAGE_WIDTH - _RIGHT, 11.5 * mm)
        canv.setFillColor(_MUTED)
        canv.setFont("Helvetica", 6.5)
        canv.drawString(
            _LEFT,
            7.5 * mm,
            "PRIVATE / READ-ONLY / CLIENT-DATA INGESTION PROHIBITED",
        )
        canv.drawRightString(_PAGE_WIDTH - _RIGHT, 7.5 * mm, f"Page {doc.page}")
        canv.restoreState()

    def afterFlowable(self, flowable: Flowable) -> None:  # noqa: N802 - ReportLab hook name
        if not isinstance(flowable, Paragraph):
            return
        levels = {"AtlasHeading1": 0, "AtlasHeading2": 1}
        level = levels.get(flowable.style.name)
        if level is None:
            return
        title = flowable.getPlainText()
        stem = hashlib.sha256(f"{level}:{title}".encode("utf-8")).hexdigest()[:16]
        occurrence = self._bookmark_counts.get(stem, 0)
        self._bookmark_counts[stem] = occurrence + 1
        key = f"atlas-{stem}-{occurrence}"
        self.canv.bookmarkPage(key)
        self.canv.addOutlineEntry(title, key, level=level, closed=level > 0)
        self.notify("TOCEntry", (level, title, self.page, key))


def _paragraph(value: object, style: ParagraphStyle) -> Paragraph:
    return Paragraph(_markup(value), style)


def _rich(value: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(value, style)


def _heading(value: object, style: ParagraphStyle) -> Paragraph:
    return Paragraph(_markup(value), style)


def _callout(title: str, body: str, styles: dict[str, ParagraphStyle], *, color: colors.Color = _CYAN) -> Table:
    content = _rich(
        f"<b>{_markup(title)}</b><br/>{_markup(body)}",
        styles["callout"],
    )
    table = Table([["", content]], colWidths=[3.2 * mm, _FRAME_WIDTH - 3.2 * mm], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, 0), color),
                ("BACKGROUND", (1, 0), (1, 0), _PAPER),
                ("BOX", (0, 0), (-1, -1), 0.5, _LINE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (0, 0), 0),
                ("RIGHTPADDING", (0, 0), (0, 0), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                ("LEFTPADDING", (1, 0), (1, 0), 9),
                ("RIGHTPADDING", (1, 0), (1, 0), 9),
            ]
        )
    )
    return table


def _table(
    headers: Sequence[str],
    rows: Sequence[Sequence[object]],
    widths: Sequence[float],
    styles: dict[str, ParagraphStyle],
    *,
    monospace_columns: Iterable[int] = (),
) -> LongTable:
    if len(headers) != len(widths) or any(len(row) != len(headers) for row in rows):
        raise ValueError("table shape does not match headers")
    if sum(widths) > _FRAME_WIDTH + 0.01:
        raise ValueError("table widths exceed the document frame")
    mono = set(monospace_columns)
    data: list[list[Paragraph]] = [
        [_paragraph(header, styles["table_head"]) for header in headers]
    ]
    for row in rows:
        data.append(
            [
                _paragraph(value, styles["table_mono"] if column in mono else styles["table"])
                for column, value in enumerate(row)
            ]
        )
    table = LongTable(
        data,
        colWidths=list(widths),
        repeatRows=1,
        hAlign="LEFT",
        splitByRow=1,
        spaceAfter=7,
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), _NAVY_2),
                ("TEXTCOLOR", (0, 0), (-1, 0), _WHITE),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [_WHITE, _PAPER]),
                ("GRID", (0, 0), (-1, -1), 0.35, _LINE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def _bullet_lines(values: Iterable[object], styles: dict[str, ParagraphStyle]) -> list[Flowable]:
    rows: list[Flowable] = []
    for value in values:
        clean = _plain(value)
        if clean:
            rows.append(_paragraph(f"- {clean}", styles["bullet"]))
    if not rows:
        rows.append(_paragraph("None declared.", styles["small"]))
    return rows


def _load_json_object(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    value = json.loads(raw.decode("utf-8", errors="strict"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _load_architecture(
    content: ContentBundle,
    architecture_path: Path | None,
    architecture_bytes: bytes | None = None,
) -> tuple[dict[str, Any] | None, str]:
    if architecture_bytes is not None:
        if architecture_path is not None:
            raise ValueError("choose architecture_path or architecture_bytes, not both")
        try:
            value = json.loads(architecture_bytes.decode("utf-8", errors="strict"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("architecture bytes are not valid UTF-8 JSON") from exc
        if not isinstance(value, dict):
            raise ValueError("architecture contract is not an object")
        if value.get("schema_version") != "2.0.0":
            raise ValueError("architecture contract has an unsupported schema")
        errors = validate_contract(value)
        if errors:
            raise ValueError(f"architecture contract is invalid: {'; '.join(errors)}")
        return value, sha256_bytes(architecture_bytes)
    candidate = architecture_path
    if candidate is None:
        discovered = content.root.parent / "governance" / "architecture.json"
        if discovered.is_file():
            candidate = discovered
    if candidate is None:
        return None, "not supplied"
    candidate = candidate.resolve(strict=True)
    raw = candidate.read_bytes()
    try:
        value = json.loads(raw.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("architecture contract is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("architecture contract is not an object")
    if value.get("schema_version") != "2.0.0":
        raise ValueError("architecture contract has an unsupported schema")
    errors = validate_contract(value)
    if errors:
        raise ValueError(f"architecture contract is invalid: {'; '.join(errors)}")
    return value, sha256_bytes(raw)


def _load_release_context(release_dir: Path | None, bundle: CompilerBundle) -> dict[str, Any] | None:
    if release_dir is None:
        return None
    root = release_dir.resolve(strict=True)
    manifest = _load_json_object(root / "release-manifest.json")
    binding = manifest.get("source_binding")
    if not isinstance(binding, dict):
        raise ValueError("release manifest has no source binding")
    if binding.get("source_commit") != bundle.source_commit or binding.get("source_tree_digest") != bundle.source_tree_digest:
        raise ValueError("release directory does not match the compiler source binding")
    inventory_path = root / "artifact-inventory.json"
    inventory = _load_json_object(inventory_path) if inventory_path.is_file() else None
    if inventory is not None and (
        inventory.get("source_commit") != bundle.source_commit
        or inventory.get("source_tree_digest") != bundle.source_tree_digest
    ):
        raise ValueError("artifact inventory does not match the compiler source binding")
    sbom_path = root / "bom.cdx.json"
    sbom = _load_json_object(sbom_path) if sbom_path.is_file() else None
    return {"manifest": manifest, "inventory": inventory, "sbom": sbom}


def _validate_bindings(bundle: CompilerBundle) -> None:
    if bundle.manifest.get("status") != "complete":
        raise ValueError("compiler bundle is not complete")
    if bundle.manifest.get("tracked_worktree_dirty") is not False:
        raise ValueError("PDF requires an exact clean compiler projection")
    if bundle.completeness.get("source_commit") != bundle.source_commit:
        raise ValueError("completeness ledger commit differs from compiler manifest")
    if bundle.completeness.get("source_tree_digest") != bundle.source_tree_digest:
        raise ValueError("completeness ledger tree differs from compiler manifest")
    invariants = _items(bundle.completeness.get("invariants"))
    if not invariants or any(item.get("passed") is not True for item in invariants):
        raise ValueError("PDF requires all hard completeness invariants to pass")


def _input_digest(
    bundle: CompilerBundle,
    content: ContentBundle,
    architecture: dict[str, Any] | None,
    release_context: dict[str, Any] | None,
) -> str:
    value = {
        "compiler_manifest": bundle.manifest,
        "completeness": bundle.completeness,
        "curated": {
            "core": content.core,
            "capabilities": content.capabilities,
            "governance": content.governance,
            "horizon": content.horizon,
        },
        "architecture": architecture,
        "release_manifest": release_context["manifest"] if release_context else None,
        "artifact_inventory": release_context["inventory"] if release_context else None,
    }
    return sha256_bytes(canonical_json(value))


def _cover(
    bundle: CompilerBundle,
    content: ContentBundle,
    input_digest: str,
    styles: dict[str, ParagraphStyle],
) -> list[Flowable]:
    as_of = _plain(content.core.get("as_of") or content.core.get("catalog_version") or "undated")
    acceptance = _items(bundle.completeness.get("acceptance_gates"))
    failed = [item for item in acceptance if item.get("passed") is not True]
    status = f"BLOCK - {len(failed)} semantic acceptance gate(s) open; independent verification pending"
    hero = Table(
        [
            [_paragraph("ATLAS / WHOLE-REPOSITORY ACCOUNTING", styles["cover_kicker"])],
            [_paragraph("Master Reference", styles["cover_title"])],
            [
                _paragraph(
                    "A source-bound owner, engineering, assurance, and enhancement reference. "
                    "Structural completeness is shown separately from behavioral proof.",
                    styles["cover_subtitle"],
                )
            ],
            [Spacer(1, 13 * mm)],
            [_paragraph(f"INDEPENDENT VERIFICATION VERDICT: {status}", styles["cover_kicker"])],
            [
                _rich(
                    f"Source commit&nbsp;&nbsp;{_markup(bundle.source_commit)}<br/>"
                    f"Source tree&nbsp;&nbsp;&nbsp;&nbsp;{_markup(bundle.source_tree_digest)}<br/>"
                    f"Input digest&nbsp;&nbsp;&nbsp;{_markup(input_digest)}<br/>"
                    f"Catalog as-of&nbsp;&nbsp;{_markup(as_of)}",
                    styles["cover_meta"],
                )
            ],
        ],
        colWidths=[_FRAME_WIDTH],
        rowHeights=[None, None, None, 17 * mm, None, None],
        hAlign="LEFT",
    )
    hero.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), _NAVY),
                ("BOX", (0, 0), (-1, -1), 0.8, _NAVY_2),
                ("LEFTPADDING", (0, 0), (-1, -1), 15),
                ("RIGHTPADDING", (0, 0), (-1, -1), 15),
                ("TOPPADDING", (0, 0), (-1, -1), 9),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    return [Spacer(1, 19 * mm), hero, Spacer(1, 12 * mm), _callout(
        "Reading contract",
        "This PDF is a navigational projection, not a second source of truth. It intentionally omits raw source text. "
        "Use the content-hashed Source Explorer for line-level content, and treat every BLOCKED or unknown state as real.",
        styles,
        color=_AMBER,
    ), PageBreak()]


def _contents(styles: dict[str, ParagraphStyle]) -> list[Flowable]:
    toc = TableOfContents()
    toc.levelStyles = [styles["toc"], styles["toc2"]]
    return [
        _heading("Contents", styles["h1"]),
        _paragraph(
            "The bookmarks and table of contents are generated from this exact document. Major sections and domain dossiers are linkable in compatible readers.",
            styles["body"],
        ),
        Spacer(1, 4 * mm),
        toc,
        PageBreak(),
    ]


def _source_and_truth(
    bundle: CompilerBundle,
    content: ContentBundle,
    architecture_digest: str,
    input_digest: str,
    styles: dict[str, ParagraphStyle],
) -> list[Flowable]:
    story: list[Flowable] = [
        _heading("1. Source identity and truth contract", styles["h1"]),
        _callout(
            "Exact-source boundary",
            "The tracked Git tree is the project universe. Hard census invariants passing does not mean behavioral explanations, runtime traces, field evidence, or Level 4 human review are complete.",
            styles,
        ),
        Spacer(1, 3 * mm),
    ]
    source_rows = [
        ("Source commit", bundle.source_commit),
        ("HEAD tree object", bundle.manifest.get("head_tree_oid", "unknown")),
        ("Git index digest", bundle.manifest.get("index_digest", "unknown")),
        ("Source-tree digest", bundle.source_tree_digest),
        ("Tracked worktree", "clean" if bundle.manifest.get("tracked_worktree_dirty") is False else "dirty"),
        ("Compiler schema", bundle.manifest.get("schema_version", "unknown")),
        ("Architecture contract", architecture_digest),
        ("PDF input digest", input_digest),
        ("Renderer", f"ReportLab {REPORTLAB_VERSION}; invariant mode"),
    ]
    story.append(_table(("Binding", "Value"), source_rows, (43 * mm, _FRAME_WIDTH - 43 * mm), styles, monospace_columns=(1,)))
    truth = content.core.get("truth_contract", {})
    if isinstance(truth, dict):
        story.append(_heading("Truth rules", styles["h2"]))
        for key, value in sorted(truth.items()):
            story.append(_rich(f"<b>{_markup(key.replace('_', ' ').title())}:</b> {_markup(value)}", styles["body"]))
    story.extend(
        [
            _heading("Purpose and protected boundary", styles["h2"]),
            _paragraph(content.core.get("scope", "No scope declared."), styles["body"]),
            _paragraph(
                "Policy boundary: raw Vault pages and machine-local agent memory are outside the compiler corpus; restricted and binary payloads remain opaque. High-confidence allowlisted-text and generated-output scans found no matching credential patterns, while contextual, encoded, client/device, and container review remains pending. The reference is private, read-only, offline-capable, and cannot mutate the assessed estate.",
                styles["body"],
            ),
        ]
    )
    non_goals = _items(content.core.get("non_goals"))
    if non_goals:
        block: list[Flowable] = [_heading("Non-goals", styles["h2"])]
        block.extend(
            _bullet_lines(
                (item.get("statement", item.get("title", item.get("id"))) for item in non_goals),
                styles,
            )
        )
        story.append(KeepTogether(block))
    return story


def _completeness(bundle: CompilerBundle, styles: dict[str, ParagraphStyle]) -> list[Flowable]:
    ledger = bundle.completeness
    census = ledger.get("census", {}) if isinstance(ledger.get("census"), dict) else {}
    parsing = ledger.get("parsing", {}) if isinstance(ledger.get("parsing"), dict) else {}
    semantic = ledger.get("semantic_accounting", {}) if isinstance(ledger.get("semantic_accounting"), dict) else {}
    graph = ledger.get("graphify", {}) if isinstance(ledger.get("graphify"), dict) else {}
    privacy = ledger.get("privacy", {}) if isinstance(ledger.get("privacy"), dict) else {}
    story: list[Flowable] = [
        _heading("2. Whole-repository completeness ledger", styles["h1"]),
        _callout(
            "Honest verdict",
            "The compiler may pass hard structural invariants while semantic acceptance remains blocked. This report preserves that distinction and never upgrades Level 1 mapping into Level 4 understanding.",
            styles,
            color=_AMBER,
        ),
        Spacer(1, 3 * mm),
    ]
    story.append(
        _table(
            ("Measure", "Actual"),
            [
                ("Tracked files", census.get("tracked_files", len(bundle.records.get("files", [])))),
                ("Classified files", census.get("classified_files", "unknown")),
                ("Safe full-exposure files", census.get("full_exposure_files", "unknown")),
                ("Metadata-only files", census.get("metadata_only_files", "unknown")),
                ("Expected nonblank safe lines", parsing.get("expected_nonblank_lines", "unknown")),
                ("Source line records", parsing.get("line_records", len(bundle.records.get("lines", [])))),
                ("Lines with explicit uncertainty", parsing.get("lines_with_explicit_unresolved_reasons", "unknown")),
                ("Symbol dossiers", semantic.get("symbol_dossiers", "unknown")),
                ("Critical/public symbols", semantic.get("critical_or_public_symbols", "unknown")),
                ("Critical Level 4 reviews", semantic.get("critical_level_four_reviews", "unknown")),
            ],
            (60 * mm, _FRAME_WIDTH - 60 * mm),
            styles,
        )
    )
    story.append(_heading("Machine record groups", styles["h2"]))
    group_rows = [
        (name, receipt.get("record_count", "unknown"))
        for name, receipt in sorted(bundle.manifest.get("groups", {}).items())
        if isinstance(receipt, dict)
    ]
    story.append(_table(("Record group", "Records"), group_rows, (90 * mm, _FRAME_WIDTH - 90 * mm), styles))
    story.append(_heading("Hard structural invariants", styles["h2"]))
    invariant_rows = [
        (
            item.get("name", "unnamed"),
            "PASS" if item.get("passed") is True else "FAIL",
            item.get("expected", ""),
            item.get("actual", ""),
        )
        for item in _items(ledger.get("invariants"))
    ]
    story.append(
        _table(
            ("Invariant", "Status", "Expected", "Actual"),
            invariant_rows,
            (84 * mm, 22 * mm, 28 * mm, _FRAME_WIDTH - 134 * mm),
            styles,
        )
    )
    acceptance = _items(ledger.get("acceptance_gates"))
    story.append(_heading("Semantic acceptance gates", styles["h2"]))
    if acceptance:
        acceptance_rows = [
            (
                item.get("name", "unnamed"),
                "PASS" if item.get("passed") is True else "BLOCKED",
                item.get("expected", ""),
                item.get("actual", ""),
            )
            for item in acceptance
        ]
        story.append(
            _table(
                ("Gate", "Status", "Expected", "Actual"),
                acceptance_rows,
                (84 * mm, 22 * mm, 28 * mm, _FRAME_WIDTH - 134 * mm),
                styles,
            )
        )
    else:
        story.append(_callout("BLOCKED", "No semantic acceptance gates were emitted by this compiler bundle.", styles, color=_RED))
    story.append(_heading("Semantic depth", styles["h2"]))
    line_depths = semantic.get("line_explanation_depth_counts", {})
    symbol_depths = semantic.get("symbol_explanation_depth_counts", {})
    depth_rows = []
    for depth in range(5):
        depth_rows.append(
            (
                f"Level {depth}",
                line_depths.get(str(depth), 0) if isinstance(line_depths, dict) else "unknown",
                symbol_depths.get(str(depth), 0) if isinstance(symbol_depths, dict) else "unknown",
                (
                    "inventoried" if depth == 0 else
                    "structurally mapped" if depth == 1 else
                    "behaviorally explained" if depth == 2 else
                    "verified by executable evidence" if depth == 3 else
                    "independently human-reviewed critical logic"
                ),
            )
        )
    story.append(
        _table(
            ("Depth", "Lines", "Symbols", "Meaning"),
            depth_rows,
            (22 * mm, 22 * mm, 24 * mm, _FRAME_WIDTH - 68 * mm),
            styles,
        )
    )
    story.append(_heading("Graphify projection", styles["h2"]))
    story.append(
        _table(
            ("Property", "Value"),
            [(key, value) for key, value in sorted(graph.items()) if not isinstance(value, (dict, list))],
            (58 * mm, _FRAME_WIDTH - 58 * mm),
            styles,
        )
    )
    story.append(_paragraph(
        "Graphify is structural advisory evidence. Extracted or inferred edges never become runtime truth without conformance evidence.",
        styles["small"],
    ))
    story.append(_heading("Privacy boundary", styles["h2"]))
    story.append(
        _table(
            ("Boundary", "Disposition"),
            [(key.replace("_", " "), value) for key, value in sorted(privacy.items())],
            (62 * mm, _FRAME_WIDTH - 62 * mm),
            styles,
        )
    )
    return story


def _outcomes(content: ContentBundle, styles: dict[str, ParagraphStyle]) -> list[Flowable]:
    outcomes = _items(content.core.get("outcomes"))
    story: list[Flowable] = [PageBreak(), _heading("3. Product purpose and outcomes", styles["h1"])]
    if not outcomes:
        story.append(_paragraph("No outcome contracts were declared.", styles["body"]))
        return story
    for item in outcomes:
        story.append(CondPageBreak(35 * mm))
        story.append(_heading(f"{item.get('id', 'outcome')} - {item.get('title', 'Untitled outcome')}", styles["h2"]))
        for key in ("promise", "success_signal", "owner", "scope", "limitations"):
            if item.get(key) is not None:
                story.append(_rich(f"<b>{_markup(key.replace('_', ' ').title())}:</b> {_markup(item[key])}", styles["body"]))
    return story


def _capabilities(content: ContentBundle, styles: dict[str, ParagraphStyle]) -> list[Flowable]:
    domains = _items(content.capabilities.get("domains"))
    entries = [entry for domain in domains for entry in _items(domain.get("entries"))]
    counts = Counter(_plain(entry.get("state", "unknown")) for entry in entries)
    story: list[Flowable] = [
        PageBreak(),
        _heading("4. Closed Capability Catalog", styles["h1"]),
        _callout(
            "Finite denominator",
            _plain(content.capabilities.get("denominator_rule", "Catalog inclusion is a classification, not a support promise.")),
            styles,
        ),
        Spacer(1, 3 * mm),
        _table(
            ("State", "Cells", "Interpretation"),
            [
                (state, count, "Truth classification; never an aggregate score")
                for state, count in sorted(counts.items())
            ],
            (38 * mm, 25 * mm, _FRAME_WIDTH - 63 * mm),
            styles,
        ),
    ]
    for domain in domains:
        domain_id = _plain(domain.get("id", "domain.unknown"))
        story.extend([PageBreak(), _heading(domain_id, styles["h2"])])
        domain_entries = _items(domain.get("entries"))
        story.append(_paragraph(
            f"Declared cells: {len(domain_entries)}. Every cell remains linked to current owners or an explicit gap/disposition.",
            styles["small"],
        ))
        for entry in domain_entries:
            story.append(CondPageBreak(31 * mm))
            state = _plain(entry.get("state", "unknown"))
            title = f"{entry.get('id', 'capability.unknown')} - {entry.get('title', 'Untitled capability')} [{state.upper()}]"
            story.append(_heading(title, styles["h3"]))
            story.append(_paragraph(entry.get("current_scope", "No bounded scope statement."), styles["body"]))
            refs: list[str] = []
            owners = _strings(entry.get("owner_refs"))
            gaps = _strings(entry.get("gap_refs"))
            if owners:
                refs.append(f"Owners: {', '.join(owners)}")
            if gaps:
                refs.append(f"Gaps: {', '.join(gaps)}")
            if refs:
                story.append(_paragraph(" | ".join(refs), styles["small"]))
            bar = Table([[""]], colWidths=[_FRAME_WIDTH], rowHeights=[1.4])
            bar.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), _state_color(state)), ("LINEBELOW", (0, 0), (-1, -1), 0, _WHITE)]))
            story.append(bar)
    return story


def _governance(content: ContentBundle, styles: dict[str, ParagraphStyle]) -> list[Flowable]:
    gaps = _items(content.governance.get("gaps"))
    decisions = _items(content.governance.get("decision_queue"))
    portfolio = content.governance.get("opportunity_portfolio", {})
    opportunities = _items(portfolio.get("items")) if isinstance(portfolio, dict) else []
    priorities = Counter(_plain(item.get("priority", "unprioritized")) for item in gaps)
    story: list[Flowable] = [
        PageBreak(),
        _heading("5. Delivery governance, gaps, and decisions", styles["h1"]),
        _table(
            ("Queue", "Count", "Meaning"),
            [
                ("Gaps", len(gaps), "Incomplete or explicitly excluded work with a disposition"),
                ("Decisions", len(decisions), "Human authority queue; recommendations do not self-approve"),
                ("Opportunities", len(opportunities), "Transparent multi-axis candidates; no opaque aggregate score"),
            ],
            (42 * mm, 22 * mm, _FRAME_WIDTH - 64 * mm),
            styles,
        ),
        _heading("Gap priority distribution", styles["h2"]),
        _table(
            ("Priority", "Gaps"),
            [(key, value) for key, value in sorted(priorities.items())],
            (60 * mm, _FRAME_WIDTH - 60 * mm),
            styles,
        ),
        _heading("Complete gap register", styles["h2"]),
    ]
    for gap in gaps:
        block = [
            _heading(f"{gap.get('id', 'gap.unknown')} - {gap.get('title', 'Untitled gap')}", styles["h3"]),
            _rich(
                f"<b>Priority:</b> {_markup(gap.get('priority', 'unprioritized'))} &nbsp; "
                f"<b>Disposition:</b> {_markup(gap.get('disposition', 'unknown'))} &nbsp; "
                f"<b>Owner:</b> {_markup(gap.get('owner_role', 'unassigned'))}",
                styles["small"],
            ),
            _paragraph(gap.get("problem", "No problem statement."), styles["body"]),
            _rich("<b>Smallest next actions</b>", styles["body"]),
        ]
        block.extend(_bullet_lines(_strings(gap.get("next_actions")), styles))
        block.append(_rich("<b>Acceptance evidence</b>", styles["body"]))
        block.extend(_bullet_lines(_strings(gap.get("acceptance_evidence")), styles))
        story.append(KeepTogether(block))
    story.append(_heading("Human decision queue", styles["h2"]))
    for decision in decisions:
        block = [
            _heading(
                f"{decision.get('id', 'decision.unknown')} - {decision.get('title', 'Untitled decision')}",
                styles["h3"],
            )
        ]
        for key in ("status", "authority", "current_recommendation"):
            block.append(
                _rich(
                    f"<b>{_markup(key.replace('_', ' ').title())}:</b> "
                    f"{_markup(decision.get(key, 'unknown'))}",
                    styles["body"],
                )
            )
        block.append(_rich("<b>Options</b>", styles["body"]))
        block.extend(_bullet_lines(_strings(decision.get("options")), styles))
        block.append(_rich("<b>Evidence needed</b>", styles["body"]))
        block.extend(_bullet_lines(_strings(decision.get("evidence_needed")), styles))
        story.append(KeepTogether(block))
    story.append(_heading("Opportunity portfolio", styles["h2"]))
    if isinstance(portfolio, dict) and portfolio.get("ranking_rule"):
        story.append(_callout("Ranking rule", _plain(portfolio["ranking_rule"]), styles))
    for opportunity in opportunities:
        story.append(CondPageBreak(35 * mm))
        story.append(_heading(f"{opportunity.get('id', 'opportunity.unknown')} - {opportunity.get('title', 'Untitled opportunity')}", styles["h3"]))
        axes = opportunity.get("axes", {})
        axes_text = ", ".join(f"{key}={value}" for key, value in sorted(axes.items())) if isinstance(axes, dict) else "not declared"
        story.append(_paragraph(
            f"Horizon: {opportunity.get('horizon', 'unknown')} | Axes: {axes_text} | Gaps: {', '.join(_strings(opportunity.get('gap_refs'))) or 'none'}",
            styles["small"],
        ))
        if opportunity.get("axis_notes"):
            story.append(_paragraph(opportunity["axis_notes"], styles["body"]))
    return story


def _architecture_and_invariants(
    content: ContentBundle,
    architecture: dict[str, Any] | None,
    styles: dict[str, ParagraphStyle],
) -> list[Flowable]:
    story: list[Flowable] = [PageBreak(), _heading("6. Architecture and protected invariants", styles["h1"])]
    if architecture is None:
        story.append(_callout("Architecture contract unavailable", "No validated architecture.json was supplied. This is an explicit limitation, not an empty architecture.", styles, color=_RED))
    else:
        components = _items(architecture.get("components"))
        story.append(_heading("Components and trust zones", styles["h2"]))
        story.append(
            _table(
                ("Component", "Layer", "Trust zone", "Owned paths"),
                [
                    (
                        item.get("id", "unknown"),
                        item.get("layer", ""),
                        item.get("trust_zone", "unknown"),
                        ", ".join(_strings(item.get("paths"))),
                    )
                    for item in components
                ],
                (39 * mm, 15 * mm, 35 * mm, _FRAME_WIDTH - 89 * mm),
                styles,
                monospace_columns=(0, 3),
            )
        )
        story.append(_heading("Runtime phases", styles["h2"]))
        story.append(
            _table(
                ("Order", "Phase", "Required"),
                [
                    (item.get("order", ""), item.get("id", "unknown"), "yes" if item.get("required") is True else "no")
                    for item in _items(architecture.get("runtime_phases"))
                ],
                (22 * mm, 86 * mm, _FRAME_WIDTH - 108 * mm),
                styles,
            )
        )
        story.append(_heading("Forbidden dependencies", styles["h2"]))
        forbidden = _items(architecture.get("forbidden_edges"))
        story.append(
            _table(
                ("From", "To", "Reason"),
                [
                    (item.get("from", "unknown"), item.get("to", "unknown"), item.get("reason", "No reason declared."))
                    for item in forbidden
                ],
                (38 * mm, 38 * mm, _FRAME_WIDTH - 76 * mm),
                styles,
                monospace_columns=(0, 1),
            )
        )
        story.append(_paragraph(
            f"Allowed dependency edges declared: {len(architecture.get('allowed_edges', []))}. Edge semantics: {architecture.get('edge_semantics', 'not declared')}.",
            styles["small"],
        ))
    invariants = _items(content.governance.get("invariants"))
    story.append(_heading("Invariant catalog", styles["h2"]))
    if invariants:
        for invariant in invariants:
            block = [_heading(f"{invariant.get('id', 'invariant.unknown')}", styles["h3"])]
            for key in ("statement", "intent", "scope", "formal_rule", "residual_risk"):
                if invariant.get(key) is not None:
                    block.append(
                        _rich(
                            f"<b>{_markup(key.replace('_', ' ').title())}:</b> {_markup(invariant[key])}",
                            styles["body"],
                        )
                    )
            owners = _strings(invariant.get("owner_refs"))
            if owners:
                block.append(_paragraph(f"Owners: {', '.join(owners)}", styles["small"]))
            story.append(KeepTogether(block))
    else:
        story.append(_paragraph("No curated invariants were emitted.", styles["body"]))
    return story


def _source_explorer(bundle: CompilerBundle, styles: dict[str, ParagraphStyle]) -> list[Flowable]:
    counts = {name: item.get("record_count", 0) for name, item in bundle.manifest.get("groups", {}).items() if isinstance(item, dict)}
    routes = [
        ("/source", "Complete tracked file tree, classification, depth, and uncertainty"),
        ("/source/[path]", "Content-hashed safe line view with semantic breadcrumbs"),
        ("/symbol/[id]", "Symbol purpose, callers, callees, effects, proof, and impact"),
        ("/data/[id]", "Structured dataset schema, provenance, denominator, and consumers"),
        ("/test/[id]", "Proof dossier, fixture provenance, asserted invariants, and limits"),
        ("/workflow/[id]", "Trigger, permissions, steps, artifacts, secrets boundary, and failure effects"),
    ]
    return [
        _heading("7. Whole-repository Source Explorer", styles["h1"]),
        _callout(
            "Why source text is not printed here",
            "The PDF preserves repository accounting without duplicating hundreds of thousands of source lines. Safe source is loaded only from content-hashed per-file chunks; restricted content remains opaque. This keeps the document usable and avoids a second, stale source corpus.",
            styles,
            color=_AMBER,
        ),
        Spacer(1, 3 * mm),
        _table(("Route", "Question answered"), routes, (48 * mm, _FRAME_WIDTH - 48 * mm), styles, monospace_columns=(0,)),
        _heading("Line and symbol traversal", styles["h2"]),
        _paragraph(
            "A line link resolves its containing syntax unit, symbol, owner, behavior group, inputs and outputs, influenced claims, callers and dependencies, tests, runtime-trace state, GUI or artifact consumers, security/privacy effect, historical status, explanation depth, and unresolved reasons.",
            styles["body"],
        ),
        _paragraph(
            "Impact traversal is evidence-bounded. Missing runtime or coverage data is shown as not collected or structural-only; it is never inferred as verified.",
            styles["body"],
        ),
        _heading("Explorer denominators", styles["h2"]),
        _table(
            ("Entity", "Records"),
            [(name, counts.get(name, 0)) for name in ("files", "lines", "symbols", "routes", "components", "tests", "workflows", "datasets", "binaries", "dependencies", "claims")],
            (70 * mm, _FRAME_WIDTH - 70 * mm),
            styles,
        ),
    ]


def _release_section(
    bundle: CompilerBundle,
    release_context: dict[str, Any] | None,
    styles: dict[str, ParagraphStyle],
) -> list[Flowable]:
    story: list[Flowable] = [PageBreak(), _heading("8. Release, export, and preservation", styles["h1"])]
    if release_context is None:
        story.append(_callout(
            "Release context not supplied",
            "This PDF is bound to the validated compiler and curated content. It was generated before or independently of an emitted release directory, so artifact receipts and signing state must be read from the eventual release-manifest.json.",
            styles,
            color=_AMBER,
        ))
        story.append(_paragraph("Independent verification verdict: BLOCK. Signature, visual review, and publication authority are not established by PDF generation.", styles["body"]))
        return story
    manifest = release_context["manifest"]
    inventory = release_context.get("inventory")
    sbom = release_context.get("sbom")
    story.append(
        _table(
            ("Property", "Value"),
            [
                ("Release status", manifest.get("release_status", "unknown")),
                ("Publication status", manifest.get("publication_status", "unknown")),
                ("Independent verification", manifest.get("independent_verification_verdict", "BLOCK")),
                ("Source commit", bundle.source_commit),
                ("Source-tree digest", bundle.source_tree_digest),
                ("SBOM components", len(sbom.get("components", [])) if isinstance(sbom, dict) else "not supplied"),
            ],
            (56 * mm, _FRAME_WIDTH - 56 * mm),
            styles,
            monospace_columns=(1,),
        )
    )
    gates = manifest.get("gates", {})
    if isinstance(gates, dict):
        story.append(_heading("Executable release gates", styles["h2"]))
        story.append(_table(
            ("Gate", "State"),
            [(key, value) for key, value in sorted(gates.items())],
            (83 * mm, _FRAME_WIDTH - 83 * mm),
            styles,
        ))
    artifacts = _items(inventory.get("artifacts")) if isinstance(inventory, dict) else []
    story.append(_heading("Artifact inventory", styles["h2"]))
    if artifacts:
        story.append(_table(
            ("Path", "Role", "Bytes", "SHA-256"),
            [
                (item.get("path", "unknown"), item.get("role", "unknown"), item.get("bytes", ""), item.get("sha256", "unknown"))
                for item in artifacts
            ],
            (54 * mm, 33 * mm, 20 * mm, _FRAME_WIDTH - 107 * mm),
            styles,
            monospace_columns=(0, 3),
        ))
    else:
        story.append(_paragraph("No validated artifact inventory was supplied.", styles["body"]))
    story.append(_heading("Signing and preservation boundary", styles["h2"]))
    story.extend(_bullet_lines([
        "Unsigned builds remain previews; a PDF digest is not an owner signature.",
        "An offline owner-controlled Ed25519 private key must remain outside the repository.",
        "Public publication requires separate explicit authority even after cryptographic verification.",
        "Preservation includes source, schemas/upcasters, manifest/ledger, signatures, offline viewer, dependency caches, fixtures, and recovery instructions.",
    ], styles))
    return story


def _horizon(content: ContentBundle, styles: dict[str, ParagraphStyle]) -> list[Flowable]:
    horizon = content.horizon
    signals = _items(horizon.get("signals"))
    watches = _items(horizon.get("watch_families"))
    story: list[Flowable] = [
        PageBreak(),
        _heading("9. Open-world Horizon Register", styles["h1"]),
        _callout(
            "Advisory only",
            _plain(horizon.get("promise", "Horizon content never proves current support and never mutates assessment truth.")),
            styles,
            color=_AMBER,
        ),
        Spacer(1, 3 * mm),
        _paragraph(horizon.get("support_claim", "No support claim."), styles["small"]),
        _heading("Watch families", styles["h2"]),
    ]
    for watch in watches:
        story.append(CondPageBreak(29 * mm))
        story.append(_heading(f"{watch.get('id', 'watch.unknown')} - {watch.get('name', 'Untitled watch family')}", styles["h3"]))
        story.append(_paragraph(watch.get("authority_scope", "No authority scope declared."), styles["body"]))
        story.append(_paragraph(
            f"Cadence: {watch.get('review_cadence', 'not declared')} | Content role: {watch.get('content_role', 'advisory')} | Engine ingestion: {watch.get('engine_ingestion', 'none')}",
            styles["small"],
        ))
        if watch.get("source_url"):
            story.append(_paragraph(f"Primary source: {watch['source_url']}", styles["mono"]))
    story.extend([PageBreak(), _heading("Tracked horizon signals", styles["h2"])])
    if signals:
        for signal in signals:
            story.append(CondPageBreak(28 * mm))
            story.append(_heading(f"{signal.get('id', 'signal.unknown')} - {signal.get('title', 'Untitled signal')}", styles["h3"]))
            summary_parts = []
            for key in ("disposition", "maturity", "status", "next_review"):
                if signal.get(key) is not None:
                    summary_parts.append(f"{key.replace('_', ' ')}: {signal[key]}")
            if summary_parts:
                story.append(_paragraph(" | ".join(summary_parts), styles["small"]))
            for key in ("why_it_matters", "current_assessment", "rationale", "promotion_gate"):
                if signal.get(key) is not None:
                    story.append(_rich(f"<b>{_markup(key.replace('_', ' ').title())}:</b> {_markup(signal[key])}", styles["body"]))
    else:
        story.append(_paragraph("No horizon signals were emitted. The unknown bucket still remains open by contract.", styles["body"]))
    return story


def _limitations(
    bundle: CompilerBundle,
    content: ContentBundle,
    release_context: dict[str, Any] | None,
    styles: dict[str, ParagraphStyle],
) -> list[Flowable]:
    failed = [item for item in _items(bundle.completeness.get("acceptance_gates")) if item.get("passed") is not True]
    limits = [
        "Structural line mapping is not behavioral or human-reviewed understanding.",
        "Coverage percentages and static reachability are not correctness proof.",
        "Graphify extraction or inference is not runtime truth.",
        "Synthetic evidence is not field validation.",
        "Catalog inclusion is not an implementation claim.",
        "Missing evidence is never rendered as zero, healthy, or not applicable.",
        "The PDF intentionally contains no raw source text and is not a substitute for Source Explorer.",
        "Deterministic bytes require the same validated inputs and compatible ReportLab/toolchain version.",
        "Visual review, assistive-technology review, signature, and publication authority remain separate gates.",
    ]
    if release_context:
        limits.extend(_strings(release_context["manifest"].get("honest_limits")))
    story: list[Flowable] = [
        PageBreak(),
        _heading("10. Limitations and acceptance disposition", styles["h1"]),
        _callout(
            "Final document verdict: BLOCK",
            "This generated reference is a review artifact. It cannot self-approve its semantic explanations, visual quality, accessibility, signature, or publication authority.",
            styles,
            color=_RED,
        ),
        Spacer(1, 3 * mm),
        _heading("Open semantic gates", styles["h2"]),
    ]
    if failed:
        for item in failed:
            story.append(_rich(
                f"<b>BLOCKED - {_markup(item.get('name', 'unnamed gate'))}</b>: expected {_markup(item.get('expected', 'unknown'))}; actual {_markup(item.get('actual', 'unknown'))}.",
                styles["body"],
            ))
    else:
        story.append(_paragraph(
            "No failed compiler semantic gate is recorded, but independent PDF, security, accessibility, release-signing, and publication reviews still prevent self-approval.",
            styles["body"],
        ))
    story.append(_heading("Standing truth limits", styles["h2"]))
    story.extend(_bullet_lines(dict.fromkeys(limits), styles))
    story.append(_heading("Independent review required", styles["h2"]))
    story.extend(_bullet_lines([
        "File/line census and exclusion challenge.",
        "Authority, claim, and current-versus-historical reconciliation.",
        "Architecture conformance and forbidden-edge challenge.",
        "Protocol/design breadth and capability-gap honesty.",
        "Security, privacy, accessibility, and performance review.",
        "Offline/export receipts, signing, agent-envelope, and recovery exercises.",
    ], styles))
    story.append(Spacer(1, 6 * mm))
    story.append(_paragraph(
        f"End of source-bound Master Reference for commit {bundle.source_commit}. Unknowns remain explicit.",
        styles["small"],
    ))
    return story


def build_master_reference_pdf(
    bundle: CompilerBundle,
    content: ContentBundle,
    output_path: Path,
    *,
    release_dir: Path | None = None,
    architecture_path: Path | None = None,
    architecture_bytes: bytes | None = None,
) -> PdfReportResult:
    """Render a deterministic PDF from validated inputs without source text.

    Existing outputs and in-progress files are never overwritten.  The result
    remains a non-releaseable review artifact until independent visual review,
    semantic acceptance, signing, and publication gates clear elsewhere.
    """

    _validate_bindings(bundle)
    architecture, architecture_digest = _load_architecture(
        content,
        architecture_path,
        architecture_bytes,
    )
    release_context = _load_release_context(release_dir, bundle)
    digest = _input_digest(bundle, content, architecture, release_context)
    output_path = output_path.resolve()
    if output_path.exists():
        raise FileExistsError(f"PDF output already exists: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(f".{output_path.name}.building")
    if temporary.exists():
        raise FileExistsError(f"PDF build path already exists: {temporary}")

    styles = _styles()
    metadata = {
        "title": "Atlas Master Reference - Whole-Repository Accounting",
        "author": "Atlas repository",
        "subject": f"Source commit {bundle.source_commit}; source-tree digest {bundle.source_tree_digest}; independent verification BLOCK",
        "keywords": "Atlas, master reference, whole repository, source bound, read only, non-releaseable",
        "creator": f"Atlas deterministic PDF renderer / ReportLab {REPORTLAB_VERSION}",
    }
    story: list[Flowable] = []
    story.extend(_cover(bundle, content, digest, styles))
    story.extend(_contents(styles))
    story.extend(_source_and_truth(bundle, content, architecture_digest, digest, styles))
    story.extend(_completeness(bundle, styles))
    story.extend(_outcomes(content, styles))
    story.extend(_capabilities(content, styles))
    story.extend(_governance(content, styles))
    story.extend(_architecture_and_invariants(content, architecture, styles))
    story.extend(_source_explorer(bundle, styles))
    story.extend(_release_section(bundle, release_context, styles))
    story.extend(_horizon(content, styles))
    story.extend(_limitations(bundle, content, release_context, styles))

    document = _AtlasDocTemplate(
        str(temporary),
        source_commit=bundle.source_commit,
        metadata=metadata,
    )
    canvasmaker = lambda *args, **kwargs: _InvariantCanvas(*args, metadata=metadata, **kwargs)  # noqa: E731
    try:
        document.multiBuild(story, canvasmaker=canvasmaker)
        raw = temporary.read_bytes()
        if not raw.startswith(b"%PDF-"):
            raise RuntimeError("ReportLab did not produce a PDF")
        os.replace(temporary, output_path)
    finally:
        if temporary.exists():
            temporary.unlink()

    inspection = inspect_pdf_report(
        output_path,
        expected_commit=bundle.source_commit,
        expected_tree_digest=bundle.source_tree_digest,
    )
    raw = output_path.read_bytes()
    return PdfReportResult(
        path=output_path,
        sha256=sha256_bytes(raw),
        bytes=len(raw),
        page_count=inspection.page_count,
        source_commit=bundle.source_commit,
        source_tree_digest=bundle.source_tree_digest,
        input_digest=digest,
        reportlab_version=str(REPORTLAB_VERSION),
        independent_verification_verdict="BLOCK",
    )


def generate_master_reference_pdf(
    compiler_root: Path,
    content_root: Path,
    output_path: Path,
    *,
    release_dir: Path | None = None,
    architecture_path: Path | None = None,
) -> PdfReportResult:
    """Strict path-oriented entry point used by release orchestration."""

    bundle = load_compiler_bundle(compiler_root)
    content = load_content_bundle(content_root)
    return build_master_reference_pdf(
        bundle,
        content,
        output_path,
        release_dir=release_dir,
        architecture_path=architecture_path,
    )


def inspect_pdf_report(
    pdf_path: Path,
    *,
    expected_commit: str,
    expected_tree_digest: str,
) -> PdfInspection:
    """Verify PDF structure, metadata, and exact-source binding with pypdf."""

    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - explicit environment error
        raise RuntimeError("pypdf is required to inspect the Master Reference PDF") from exc

    pdf_path = pdf_path.resolve(strict=True)
    raw = pdf_path.read_bytes()
    if not raw.startswith(b"%PDF-"):
        raise ValueError("file does not have a PDF header")
    reader = PdfReader(str(pdf_path))
    if not reader.pages:
        raise ValueError("PDF has no pages")
    metadata = reader.metadata or {}
    title = _plain(metadata.get("/Title", ""))
    author = _plain(metadata.get("/Author", ""))
    subject = _plain(metadata.get("/Subject", ""))
    keywords = _plain(metadata.get("/Keywords", ""))
    commit_present = expected_commit in subject
    tree_present = expected_tree_digest in subject
    if title != "Atlas Master Reference - Whole-Repository Accounting":
        raise ValueError("PDF title metadata is absent or unexpected")
    if author != "Atlas repository":
        raise ValueError("PDF author metadata is absent or unexpected")
    if not commit_present or not tree_present:
        raise ValueError("PDF metadata is not bound to the expected source")
    return PdfInspection(
        path=pdf_path,
        page_count=len(reader.pages),
        title=title,
        author=author,
        subject=subject,
        keywords=keywords,
        source_commit_present=commit_present,
        source_tree_digest_present=tree_present,
    )


def render_pdf_for_visual_qa(
    pdf_path: Path,
    output_dir: Path,
    *,
    dpi: int = 144,
) -> tuple[Path, ...]:
    """Render every page to PNG using Poppler without modifying the PDF.

    ``output_dir`` must be absent or empty so visual evidence from another build
    cannot be mistaken for the current document.  The caller must inspect the
    returned PNGs; successful rendering alone is not visual approval.
    """

    if not 72 <= dpi <= 300:
        raise ValueError("visual QA DPI must be between 72 and 300")
    pdf_path = pdf_path.resolve(strict=True)
    output_dir = output_dir.resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"visual QA directory must be empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    executable = shutil.which("pdftoppm")
    if executable is None:
        raise RuntimeError("pdftoppm is required for visual PDF QA")
    # The Codex Windows runtime exposes a .cmd shim.  Some distributions of
    # that shim cannot resolve their nested executable when launched by
    # subprocess, so prefer the bounded native target when it is present.
    executable_path = Path(executable).resolve()
    if executable_path.suffix.lower() in {".cmd", ".bat"}:
        for parent in executable_path.parents[:5]:
            native = parent / "native" / "poppler" / "Library" / "bin" / "pdftoppm.exe"
            if native.is_file():
                executable_path = native
                break
    prefix = output_dir / "atlas-master-reference"
    args = [str(executable_path), "-r", str(dpi), "-png", str(pdf_path), str(prefix)]
    if executable_path.suffix.lower() in {".cmd", ".bat"}:
        command = [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/s", "/c", subprocess.list2cmdline(args)]
    else:
        command = args
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        detail = _plain(completed.stderr or completed.stdout or "unknown Poppler error")
        raise RuntimeError(f"pdftoppm failed: {detail}")
    rendered = tuple(sorted(output_dir.glob("atlas-master-reference-*.png")))
    if not rendered:
        raise RuntimeError("pdftoppm produced no page images")
    return rendered
