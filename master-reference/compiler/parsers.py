"""Deterministic, offline parsers used by the repository compiler."""

from __future__ import annotations

import ast
import configparser
import csv
import io
import json
import re
import shlex
import tomllib
from collections import Counter
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any

from .model import digest_object, sha256_bytes, stable_id, text_preview


MAX_TEXT_BYTES = 32 * 1024 * 1024
MAX_STRUCTURED_RECORDS = 500_000
MIN_UNSAFE_CONTROL_LIMIT = 32


class ParseFailure(RuntimeError):
    """A current parser could not account for a file it owns."""


@dataclass
class ParseResult:
    parser: str
    parser_mode: str = "semantic"
    line_context: dict[int, dict[str, Any]] = field(default_factory=dict)
    symbols: list[dict[str, Any]] = field(default_factory=list)
    imports: list[dict[str, Any]] = field(default_factory=list)
    calls: list[dict[str, Any]] = field(default_factory=list)
    markdown: list[dict[str, Any]] = field(default_factory=list)
    structured: list[dict[str, Any]] = field(default_factory=list)
    routes: list[dict[str, Any]] = field(default_factory=list)
    components: list[dict[str, Any]] = field(default_factory=list)
    tests: list[dict[str, Any]] = field(default_factory=list)
    workflows: list[dict[str, Any]] = field(default_factory=list)
    dependencies: list[dict[str, Any]] = field(default_factory=list)
    unresolved_reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "parser": self.parser,
            "parser_mode": self.parser_mode,
            "line_context": self.line_context,
            "symbols": self.symbols,
            "imports": self.imports,
            "calls": self.calls,
            "markdown": self.markdown,
            "structured": self.structured,
            "routes": self.routes,
            "components": self.components,
            "tests": self.tests,
            "workflows": self.workflows,
            "dependencies": self.dependencies,
            "unresolved_reasons": sorted(set(self.unresolved_reasons)),
        }


def safe_decode_text(data: bytes, path: str) -> str:
    if len(data) > MAX_TEXT_BYTES:
        raise ParseFailure(f"{path}: text file exceeds {MAX_TEXT_BYTES} bytes")
    if b"\x00" in data:
        raise ParseFailure(f"{path}: NUL byte in allowlisted text file")
    try:
        text = data.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError as exc:
        raise ParseFailure(f"{path}: not strict UTF-8 ({exc})") from exc
    unsafe_controls = [
        (offset, ord(char)) for offset, char in enumerate(text) if ord(char) < 32 and char not in "\n\r\t\f"
    ]
    control_limit = max(MIN_UNSAFE_CONTROL_LIMIT, len(text) // 1_000)
    if len(unsafe_controls) > control_limit:
        offset, code = unsafe_controls[0]
        raise ParseFailure(
            f"{path}: binary-like control density ({len(unsafe_controls)} controls; "
            f"first U+{code:04X} at character {offset})"
        )
    return text


def nonblank_line_records(
    path: str,
    file_id: str,
    language: str,
    text: str,
    contexts: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        context = contexts.get(number) or {}
        unresolved = list(context.get("unresolved_reasons") or [])
        if not context.get("syntax_kind"):
            unresolved.append("no_parser_node_for_nonblank_line")
        raw = line.encode("utf-8")
        records.append(
            {
                "id": stable_id("line", path, number),
                "file_id": file_id,
                "path": path,
                "line": number,
                "language": language,
                "syntax_kind": context.get("syntax_kind") or "unresolved_text",
                "containing_symbol": context.get("containing_symbol"),
                "depth": int(context.get("depth") or 0),
                "text_digest": sha256_bytes(raw),
                "text_bytes": len(raw),
                "text_preview": text_preview(line),
                "unresolved_reasons": sorted(set(unresolved)),
            }
        )
    return records


def _location(node: ast.AST) -> dict[str, int | None]:
    return {
        "start_line": getattr(node, "lineno", None),
        "start_column": getattr(node, "col_offset", None),
        "end_line": getattr(node, "end_lineno", None),
        "end_column": getattr(node, "end_col_offset", None),
    }


def _py_expr_name(node: ast.AST | None) -> str:
    if node is None:
        return ""
    try:
        return ast.unparse(node)[:500]
    except Exception:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            base = _py_expr_name(node.value)
            return f"{base}.{node.attr}" if base else node.attr
        return node.__class__.__name__


def _node_source(text: str, node: ast.AST, *, include_decorators: bool = True) -> str:
    """Return the exact complete source lines owned by an AST node.

    Stable IDs deliberately do not use this value.  Digests do, so edits to a
    symbol body, comments inside its range, decorators, or trailing source on
    an owned line invalidate the content receipt without changing identity.
    """

    start = getattr(node, "lineno", None)
    end = getattr(node, "end_lineno", start)
    if not isinstance(start, int) or not isinstance(end, int):
        return ast.dump(node, include_attributes=False)
    if include_decorators:
        decorator_lines = [
            getattr(item, "lineno", start)
            for item in getattr(node, "decorator_list", [])
            if isinstance(getattr(item, "lineno", None), int)
        ]
        if decorator_lines:
            start = min(start, *decorator_lines)
    lines = text.splitlines(keepends=True)
    return "".join(lines[max(0, start - 1) : min(len(lines), end)])


def _assigned_names(node: ast.AST) -> list[str]:
    """Return every statically named binding in an assignment target."""

    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, (ast.Tuple, ast.List)):
        return [name for item in node.elts for name in _assigned_names(item)]
    return []


def _python_assertion_records(node: ast.AST, text: str) -> list[dict[str, Any]]:
    """Inventory syntactically visible assertions within one test symbol.

    This is intentionally structural: helper assertions and runtime failures
    are not inferred, and their absence is disclosed on the group record.
    """

    assertions: list[dict[str, Any]] = []
    for candidate in ast.walk(node):
        kind: str | None = None
        if isinstance(candidate, ast.Assert):
            kind = "assert_statement"
        elif isinstance(candidate, ast.Call):
            callee = _py_expr_name(candidate.func)
            leaf = callee.rsplit(".", 1)[-1]
            if leaf.startswith("assert") or callee in {
                "pytest.raises",
                "pytest.warns",
                "pytest.deprecated_call",
                "pytest.approx",
            }:
                kind = f"assertion_call:{callee}"
        if kind is None:
            continue
        assertions.append(
            {
                "kind": kind,
                "range": _location(candidate),
                "digest": sha256_bytes(_node_source(text, candidate, include_decorators=False).encode("utf-8")),
            }
        )
    return sorted(
        assertions,
        key=lambda row: (
            int((row["range"] or {}).get("start_line") or 0),
            int((row["range"] or {}).get("start_column") or 0),
            str(row["kind"]),
        ),
    )


def parse_python(path: str, file_id: str, text: str) -> ParseResult:
    try:
        tree = ast.parse(text, filename=path, type_comments=True)
    except (SyntaxError, ValueError) as exc:
        raise ParseFailure(f"{path}: Python AST parse failed: {exc}") from exc

    result = ParseResult(parser="python_ast")
    best_depth: dict[int, int] = {}
    symbol_occurrences: Counter[tuple[str, str]] = Counter()

    def append_symbol(
        *,
        node: ast.AST,
        name: str,
        qualified_name: str,
        kind: str,
        exported: bool,
        documentation: str = "",
        parameters: list[dict[str, Any]] | None = None,
        return_annotation: str | None = None,
        decorators: list[str] | None = None,
        entity_type: str | None = None,
        unresolved_reasons: list[str] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        occurrence_key = (qualified_name, kind)
        occurrence = symbol_occurrences[occurrence_key]
        symbol_occurrences[occurrence_key] += 1
        record: dict[str, Any] = {
            "id": stable_id("symbol", path, qualified_name, kind, occurrence),
            "file_id": file_id,
            "path": path,
            "name": name,
            "qualified_name": qualified_name,
            "kind": kind,
            "language": "python",
            "depth": max(0, qualified_name.count(".")),
            "range": _location(node),
            "decorators": decorators or [],
            "documentation": documentation[:4_000],
            "parameters": parameters or [],
            "return_annotation": return_annotation,
            "exported": exported,
            "digest": sha256_bytes(_node_source(text, node).encode("utf-8")),
            "entity_type": entity_type or f"python_{kind}",
            "extraction_disposition": "structurally_extracted",
            "unresolved_reasons": sorted(set(unresolved_reasons or [])),
        }
        if extra:
            record.update(extra)
        result.symbols.append(record)
        return record

    def visit(
        node: ast.AST,
        depth: int,
        stack: tuple[str, ...],
        scope_kinds: tuple[str, ...],
    ) -> None:
        is_symbol = isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        symbol_name = getattr(node, "name", "") if is_symbol else ""
        qualified = ".".join((*stack, symbol_name)) if symbol_name else ".".join(stack)
        current_stack = (*stack, symbol_name) if symbol_name else stack
        start = getattr(node, "lineno", None)
        end = getattr(node, "end_lineno", start)
        if start and end:
            for line_no in range(start, end + 1):
                if depth >= best_depth.get(line_no, -1):
                    best_depth[line_no] = depth
                    result.line_context[line_no] = {
                        "syntax_kind": node.__class__.__name__,
                        "containing_symbol": ".".join(stack) or None,
                        "depth": depth,
                        "unresolved_reasons": [],
                    }

        if is_symbol:
            kind = (
                "class"
                if isinstance(node, ast.ClassDef)
                else ("async_function" if isinstance(node, ast.AsyncFunctionDef) else "function")
            )
            decorators = [_py_expr_name(item) for item in getattr(node, "decorator_list", [])]
            parameters: list[dict[str, Any]] = []
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                arguments = node.args
                for argument in (*arguments.posonlyargs, *arguments.args):
                    parameters.append(
                        {
                            "name": argument.arg,
                            "kind": "positional",
                            "annotation": _py_expr_name(argument.annotation) or None,
                        }
                    )
                if arguments.vararg:
                    parameters.append(
                        {
                            "name": arguments.vararg.arg,
                            "kind": "variadic_positional",
                            "annotation": _py_expr_name(arguments.vararg.annotation) or None,
                        }
                    )
                for argument in arguments.kwonlyargs:
                    parameters.append(
                        {
                            "name": argument.arg,
                            "kind": "keyword_only",
                            "annotation": _py_expr_name(argument.annotation) or None,
                        }
                    )
                if arguments.kwarg:
                    parameters.append(
                        {
                            "name": arguments.kwarg.arg,
                            "kind": "variadic_keyword",
                            "annotation": _py_expr_name(arguments.kwarg.annotation) or None,
                        }
                    )
            append_symbol(
                node=node,
                name=symbol_name,
                qualified_name=qualified,
                kind=kind,
                exported=not symbol_name.startswith("_"),
                documentation=ast.get_docstring(node, clean=False) or "",
                parameters=parameters,
                return_annotation=(
                    _py_expr_name(node.returns) or None
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    else None
                ),
                decorators=decorators,
            )
            if symbol_name.startswith("test") and ("tests/" in path or path.startswith("tests/")):
                assertions = _python_assertion_records(node, text)
                assertion_group_id = stable_id(
                    "test", path, qualified, "assertion-group", node.lineno, node.col_offset
                )
                result.tests.append(
                    {
                        "id": stable_id("test", path, qualified, node.lineno, node.col_offset),
                        "file_id": file_id,
                        "path": path,
                        "name": qualified,
                        "framework": "pytest",
                        "range": _location(node),
                        "entity_type": "test_case",
                        "assertion_group_id": assertion_group_id,
                        "assertion_count": len(assertions),
                        "extraction_disposition": "structurally_extracted",
                        "unresolved_reasons": [],
                    }
                )
                result.tests.append(
                    {
                        "id": assertion_group_id,
                        "file_id": file_id,
                        "path": path,
                        "name": f"{qualified}::assertions",
                        "framework": "python_ast",
                        "range": _location(node),
                        "entity_type": "test_assertion_group",
                        "assertion_count": len(assertions),
                        "assertions": assertions,
                        "extraction_disposition": "structurally_extracted",
                        "unresolved_reasons": (
                            []
                            if assertions
                            else ["no_static_assertion_found_helper_or_runtime_failure_possible"]
                        ),
                    }
            )
            for decorator in getattr(node, "decorator_list", []):
                if not isinstance(decorator, ast.Call):
                    continue
                # Click/Typer also permits a command decorator without a
                # positional route-like argument.
                decorator_name = _py_expr_name(decorator.func)
                verb = _py_expr_name(decorator.func)
                route = decorator.args[0] if decorator.args else None
                if (
                    verb.rsplit(".", 1)[-1].lower()
                    in {"get", "post", "put", "patch", "delete", "options", "head", "route", "websocket"}
                    and isinstance(route, ast.Constant)
                    and isinstance(route.value, str)
                ):
                    result.routes.append(
                        {
                            "id": stable_id("route", "python", path, verb, route.value, qualified, decorator.lineno),
                            "file_id": file_id,
                            "path": path,
                            "route": route.value,
                            "method": verb.rsplit(".", 1)[-1].upper(),
                            "handler": qualified,
                            "framework": "fastapi_or_decorator",
                            "range": _location(decorator),
                        }
                    )
                if decorator_name.rsplit(".", 1)[-1].lower() in {"command", "group"}:
                    command_name = symbol_name.replace("_", "-")
                    for keyword in decorator.keywords:
                        if keyword.arg == "name" and isinstance(keyword.value, ast.Constant) and isinstance(
                            keyword.value.value, str
                        ):
                            command_name = keyword.value.value
                    append_symbol(
                        node=decorator,
                        name=command_name,
                        qualified_name=f"{qualified}::cli:{command_name}",
                        kind="cli_command",
                        exported=True,
                        entity_type="python_cli_command",
                        unresolved_reasons=["decorator_command_framework_not_runtime_resolved"],
                        extra={
                            "handler": qualified,
                            "framework_candidate": decorator_name,
                            "extraction_disposition": "structural_candidate",
                        },
                    )

        assignment_targets: list[ast.AST] = []
        annotation: ast.AST | None = None
        if isinstance(node, ast.Assign):
            assignment_targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            assignment_targets = [node.target]
            annotation = node.annotation
        if assignment_targets and not any(kind in {"function", "async_function"} for kind in scope_kinds):
            for target in assignment_targets:
                for assigned_name in _assigned_names(target):
                    scope = "class" if scope_kinds and scope_kinds[-1] == "class" else "module"
                    annotation_name = _py_expr_name(annotation)
                    conventional_constant = (
                        any(character.isalpha() for character in assigned_name)
                        and assigned_name.upper() == assigned_name
                    ) or annotation_name.rsplit(".", 1)[-1] == "Final"
                    entity_type = (
                        f"python_{scope}_constant"
                        if conventional_constant
                        else f"python_{scope}_binding"
                    )
                    assigned_qualified = ".".join((*stack, assigned_name))
                    append_symbol(
                        node=node,
                        name=assigned_name,
                        qualified_name=assigned_qualified,
                        kind=f"{scope}_constant" if conventional_constant else f"{scope}_binding",
                        exported=not assigned_name.startswith("_"),
                        return_annotation=annotation_name or None,
                        entity_type=entity_type,
                        unresolved_reasons=["python_assignment_does_not_enforce_runtime_immutability"],
                        extra={
                            "constant_candidate": conventional_constant,
                            "constant_basis": (
                                "uppercase_or_final_annotation"
                                if conventional_constant
                                else "module_or_class_assignment_only"
                            ),
                            "extraction_disposition": "structurally_extracted_not_runtime_constant_proof",
                        },
                    )

        if isinstance(node, ast.Import):
            for alias in node.names:
                result.imports.append(
                    {
                        "id": stable_id("import", path, node.lineno, alias.name, alias.asname or ""),
                        "file_id": file_id,
                        "path": path,
                        "module": alias.name,
                        "names": [],
                        "alias": alias.asname,
                        "kind": "import",
                        "containing_symbol": ".".join(stack) or None,
                        "range": _location(node),
                    }
                )
        elif isinstance(node, ast.ImportFrom):
            result.imports.append(
                {
                    "id": stable_id("import", path, node.lineno, node.module or "", node.level),
                    "file_id": file_id,
                    "path": path,
                    "module": ("." * node.level) + (node.module or ""),
                    "names": [alias.name for alias in node.names],
                    "alias": None,
                    "kind": "from_import",
                    "containing_symbol": ".".join(stack) or None,
                    "range": _location(node),
                }
            )
        elif isinstance(node, ast.Call):
            callee = _py_expr_name(node.func)
            result.calls.append(
                {
                    "id": stable_id(
                        "call",
                        path,
                        node.lineno,
                        node.col_offset,
                        getattr(node, "end_lineno", None),
                        getattr(node, "end_col_offset", None),
                        callee,
                    ),
                    "file_id": file_id,
                    "path": path,
                    "callee": callee,
                    "containing_symbol": ".".join(stack) or None,
                    "range": _location(node),
                    "resolved": False,
                    "unresolved_reasons": ["static_name_only_no_binding_resolution"],
                }
            )

            cli_name: str | None = None
            cli_kind: str | None = None
            if callee.rsplit(".", 1)[-1] == "add_parser" and node.args:
                first = node.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    cli_name, cli_kind = first.value, "cli_subcommand"
            elif callee.rsplit(".", 1)[-1] == "ArgumentParser":
                for keyword in node.keywords:
                    if keyword.arg == "prog" and isinstance(keyword.value, ast.Constant) and isinstance(
                        keyword.value.value, str
                    ):
                        cli_name, cli_kind = keyword.value.value, "cli_command"
            if cli_name and cli_kind:
                container = ".".join(stack) or "<module>"
                append_symbol(
                    node=node,
                    name=cli_name,
                    qualified_name=f"{container}::cli:{cli_name}",
                    kind=cli_kind,
                    exported=True,
                    entity_type=f"python_{cli_kind}",
                    unresolved_reasons=["argparse_command_parentage_not_runtime_resolved"],
                    extra={
                        "framework_candidate": callee,
                        "extraction_disposition": "structural_candidate",
                    },
                )

        for child in ast.iter_child_nodes(node):
            next_scope_kinds = scope_kinds
            if is_symbol:
                next_scope_kinds = (*scope_kinds, kind)
            visit(child, depth + 1, current_stack, next_scope_kinds)

    visit(tree, 0, (), ())
    result.symbols.sort(key=lambda row: row["id"])
    result.imports.sort(key=lambda row: row["id"])
    result.calls.sort(key=lambda row: row["id"])
    result.routes.sort(key=lambda row: row["id"])
    result.tests.sort(key=lambda row: row["id"])
    return result


HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
LINK_RE = re.compile(r"!?\[([^\]]*)\]\(([^)]+)\)")
STATUS_RE = re.compile(
    r"(?:\bstatus\s*[:=]\s*|\*\*|\[)(current|open|closed|complete|blocked|"
    r"superseded|historical|deprecated|draft|in[ -]?progress)(?:\b|\])",
    re.IGNORECASE,
)


def parse_markdown(path: str, file_id: str, text: str) -> ParseResult:
    result = ParseResult(parser="markdown_structural", parser_mode="structural")
    heading_stack: list[tuple[int, str, str]] = []
    in_fence = False
    fence_token = ""
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith(("```", "~~~")):
            token = stripped[:3]
            if not in_fence:
                in_fence, fence_token = True, token
                kind = "code_fence_open"
            elif token == fence_token:
                in_fence, fence_token = False, ""
                kind = "code_fence_close"
            else:
                kind = "code_fence_content"
        elif in_fence:
            kind = "code_fence_content"
        else:
            match = HEADING_RE.match(line)
            if match:
                level, title = len(match.group(1)), match.group(2).strip()
                while heading_stack and heading_stack[-1][0] >= level:
                    heading_stack.pop()
                qualified = " / ".join([item[1] for item in heading_stack] + [title])
                heading_id = stable_id("heading", path, qualified, number)
                heading_stack.append((level, title, heading_id))
                result.markdown.append(
                    {
                        "id": heading_id,
                        "file_id": file_id,
                        "path": path,
                        "kind": "heading",
                        "level": level,
                        "text": text_preview(title),
                        "target": None,
                        "line": number,
                        "containing_heading": heading_stack[-2][2] if len(heading_stack) > 1 else None,
                    }
                )
                kind = f"heading_{level}"
            elif stripped.startswith("<!--"):
                kind = "html_comment"
            elif stripped.startswith(">"):
                kind = "blockquote"
            elif re.match(r"^\s*(?:[-*+] |\d+[.)] )", line):
                kind = "list_item"
            elif "|" in line and stripped.startswith("|"):
                kind = "table_row"
            elif stripped:
                kind = "paragraph"
            else:
                kind = "blank"

        current = heading_stack[-1][2] if heading_stack else None
        if stripped:
            result.line_context[number] = {
                "syntax_kind": kind,
                "containing_symbol": current,
                "depth": len(heading_stack),
                "unresolved_reasons": [],
            }
        if not in_fence:
            for position, match in enumerate(LINK_RE.finditer(line)):
                result.markdown.append(
                    {
                        "id": stable_id("md-link", path, number, position, match.group(2)),
                        "file_id": file_id,
                        "path": path,
                        "kind": "image" if match.group(0).startswith("!") else "link",
                        "level": None,
                        "text": text_preview(match.group(1)),
                        "target": match.group(2).strip(),
                        "line": number,
                        "containing_heading": current,
                    }
                )
            for position, match in enumerate(STATUS_RE.finditer(line)):
                result.markdown.append(
                    {
                        "id": stable_id("md-status", path, number, position, match.group(1).lower()),
                        "file_id": file_id,
                        "path": path,
                        "kind": "status",
                        "level": None,
                        "text": match.group(1).lower().replace(" ", "-"),
                        "target": None,
                        "line": number,
                        "containing_heading": current,
                    }
                )
    if in_fence:
        result.unresolved_reasons.append("unclosed_markdown_fence")
    result.markdown.sort(key=lambda row: row["id"])
    return result


def _json_pointer_part(value: object) -> str:
    return str(value).replace("~", "~0").replace("/", "~1")


def _structured_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    if isinstance(value, (int, float)):
        return "number"
    return "string"


def _configuration_like(path: str) -> bool:
    lower = path.lower()
    name = lower.rsplit("/", 1)[-1]
    return (
        lower.startswith(".github/")
        or name
        in {
            ".mcp.json",
            "package.json",
            "pyproject.toml",
            "pytest.ini",
            "ruff.toml",
            "mypy.ini",
            "hosting.json",
            "wrangler.json",
            "wrangler.jsonc",
        }
        or name.startswith(("tsconfig", "vite.config", "vitest.config"))
        or name.endswith((".config.json", ".config.yaml", ".config.yml", ".config.toml"))
    )


def _flatten_structured(path: str, file_id: str, value: Any, root: str = "") -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    stack: list[tuple[str, Any, int, str]] = [(root or "/", value, 0, "structured_root")]
    while stack:
        pointer, current, depth, entity_type = stack.pop()
        if len(records) >= MAX_STRUCTURED_RECORDS:
            raise ParseFailure(f"{path}: structured record cap {MAX_STRUCTURED_RECORDS} exceeded")
        value_type = _structured_type(current)
        records.append(
            {
                "id": stable_id("structured", path, pointer),
                "file_id": file_id,
                "path": path,
                "pointer": pointer,
                "value_type": value_type,
                "depth": depth,
                "value_digest": digest_object(current),
                "value_preview": text_preview(str(current)) if value_type not in {"object", "array"} else None,
                "entity_type": entity_type,
                "extraction_disposition": "structurally_extracted",
                "unresolved_reasons": [],
            }
        )
        if isinstance(current, dict):
            for key in sorted(current, reverse=True, key=str):
                base = "" if pointer == "/" else pointer
                stack.append(
                    (
                        f"{base}/{_json_pointer_part(key)}",
                        current[key],
                        depth + 1,
                        "configuration_key" if _configuration_like(path) else "structured_field",
                    )
                )
        elif isinstance(current, list):
            for index in range(len(current) - 1, -1, -1):
                base = "" if pointer == "/" else pointer
                stack.append((f"{base}/{index}", current[index], depth + 1, "structured_row"))
    return records


def _context_all_nonblank(text: str, kind: str, containing: str | None = None) -> dict[int, dict[str, Any]]:
    return {
        number: {
            "syntax_kind": kind,
            "containing_symbol": containing,
            "depth": 0,
            "unresolved_reasons": [],
        }
        for number, line in enumerate(text.splitlines(), start=1)
        if line.strip()
    }


def _append_structural_cli_symbol(
    result: ParseResult,
    *,
    path: str,
    file_id: str,
    language: str,
    name: str,
    target: str,
    owner_pointer: str,
    framework: str,
) -> None:
    result.symbols.append(
        {
            "id": stable_id("symbol", path, owner_pointer, name, "cli-command"),
            "file_id": file_id,
            "path": path,
            "name": name,
            "qualified_name": f"{owner_pointer}.{name}",
            "kind": "cli_command",
            "language": language,
            "depth": owner_pointer.count("."),
            "range": {
                "start_line": None,
                "start_column": None,
                "end_line": None,
                "end_column": None,
            },
            "decorators": [],
            "documentation": "",
            "parameters": [],
            "return_annotation": target,
            "exported": True,
            "digest": digest_object({"name": name, "target": target}),
            "entity_type": "declared_cli_command",
            "framework_candidate": framework,
            "target": target,
            "extraction_disposition": "structurally_extracted_declaration",
            "unresolved_reasons": ["declared_entrypoint_target_not_import_or_runtime_resolved"],
        }
    )


def parse_json(path: str, file_id: str, text: str) -> ParseResult:
    try:
        value = json.loads(text)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ParseFailure(f"{path}: JSON parse failed: {exc}") from exc
    result = ParseResult(parser="stdlib_json")
    result.structured = _flatten_structured(path, file_id, value)
    result.line_context = _context_all_nonblank(text, "json_token")
    _dependencies_from_json(path, file_id, value, result)
    if isinstance(value, dict) and path.rsplit("/", 1)[-1].lower() == "package.json":
        bins = value.get("bin")
        if isinstance(bins, str):
            package_name = str(value.get("name") or path.rsplit("/", 1)[-1])
            _append_structural_cli_symbol(
                result,
                path=path,
                file_id=file_id,
                language="json",
                name=package_name,
                target=bins,
                owner_pointer="package.bin",
                framework="npm_bin",
            )
        elif isinstance(bins, dict):
            for name, target in sorted(bins.items(), key=lambda item: str(item[0])):
                _append_structural_cli_symbol(
                    result,
                    path=path,
                    file_id=file_id,
                    language="json",
                    name=str(name),
                    target=str(target),
                    owner_pointer="package.bin",
                    framework="npm_bin",
                )
    return result


def parse_jsonl(path: str, file_id: str, text: str) -> ParseResult:
    result = ParseResult(parser="stdlib_jsonl")
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except (json.JSONDecodeError, ValueError) as exc:
            raise ParseFailure(f"{path}:{number}: JSONL parse failed: {exc}") from exc
        result.line_context[number] = {
            "syntax_kind": "jsonl_record",
            "containing_symbol": f"line:{number}",
            "depth": 0,
            "unresolved_reasons": [],
        }
        for record in _flatten_structured(path, file_id, value, root=f"/line/{number}"):
            result.structured.append(record)
    return result


def parse_toml(path: str, file_id: str, text: str) -> ParseResult:
    try:
        value = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ParseFailure(f"{path}: TOML parse failed: {exc}") from exc
    result = ParseResult(parser="stdlib_tomllib")
    result.structured = _flatten_structured(path, file_id, value)
    section: str | None = None
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped.strip("[]")
            kind = "toml_table"
        elif "=" in stripped and not stripped.startswith("#"):
            kind = "toml_key_value"
        elif stripped.startswith("#"):
            kind = "comment"
        else:
            kind = "toml_token"
        result.line_context[number] = {
            "syntax_kind": kind,
            "containing_symbol": section,
            "depth": section.count(".") + 1 if section else 0,
            "unresolved_reasons": [],
        }
    _dependencies_from_toml(path, file_id, value, result)
    project = value.get("project") if isinstance(value, dict) else None
    scripts = project.get("scripts") if isinstance(project, dict) else None
    if isinstance(scripts, dict):
        for name, target in sorted(scripts.items(), key=lambda item: str(item[0])):
            _append_structural_cli_symbol(
                result,
                path=path,
                file_id=file_id,
                language="toml",
                name=str(name),
                target=str(target),
                owner_pointer="project.scripts",
                framework="python_project_scripts",
            )
    return result


YAML_KEY_RE = re.compile(r"^(?P<indent>\s*)(?:-\s+)?(?P<key>[^:#][^:]*?):(?:\s*(?P<value>.*))?$")


def _yaml_scalar(value: str) -> str:
    return value.strip().strip("'\"")


def _parse_github_workflow_entities(
    path: str,
    file_id: str,
    text: str,
    *,
    workflow_name: str | None,
    triggers: list[str],
) -> list[dict[str, Any]]:
    """Extract an explicit, structural GitHub Actions denominator.

    Expressions, aliases, reusable-workflow expansion, and action internals
    remain unresolved.  Declared jobs, steps, permissions, and explicit
    upload/download artifact actions are nevertheless represented one-for-one.
    """

    source_lines = text.splitlines(keepends=True)
    job_records: dict[str, dict[str, Any]] = {}
    step_records: list[dict[str, Any]] = []
    permission_records: list[dict[str, Any]] = []
    artifact_records: list[dict[str, Any]] = []
    jobs_indent: int | None = None
    job_key_indent: int | None = None
    current_job: str | None = None
    current_job_indent: int | None = None
    steps_indent: int | None = None
    current_step: dict[str, Any] | None = None
    step_index_by_job: Counter[str] = Counter()
    permission_scope: str | None = None
    permission_indent: int | None = None

    def finalize_step(end_line: int) -> None:
        nonlocal current_step
        if current_step is None or current_job is None:
            current_step = None
            return
        start_line = int(current_step["start_line"])
        raw = "".join(source_lines[start_line - 1 : max(start_line, end_line)])
        step_index = int(current_step["index"])
        step_id = stable_id("workflow", path, "job", current_job, "step", step_index)
        uses = str(current_step.get("uses") or "")
        run_value = str(current_step.get("run") or "")
        unresolved = ["yaml_semantics_and_expressions_not_resolved"]
        record = {
            "id": step_id,
            "file_id": file_id,
            "path": path,
            "name": str(current_step.get("name") or uses or f"step-{step_index + 1}"),
            "entity_type": "workflow_step",
            "job": current_job,
            "step_index": step_index,
            "uses": uses or None,
            "run_declared": bool(run_value),
            "source_digest": sha256_bytes(raw.encode("utf-8")),
            "range": {
                "start_line": start_line,
                "start_column": int(current_step.get("indent") or 0),
                "end_line": max(start_line, end_line),
                "end_column": None,
            },
            "parser_mode": "structural",
            "extraction_disposition": "structurally_extracted",
            "unresolved_reasons": unresolved,
        }
        step_records.append(record)
        job_records[current_job]["steps"].append(step_id)

        action = uses.lower()
        direction: str | None = None
        if "upload-artifact" in action or "upload-pages-artifact" in action:
            direction = "produced"
        elif "download-artifact" in action:
            direction = "consumed"
        if direction:
            artifact_id = stable_id("workflow", path, "job", current_job, "artifact", step_index, direction)
            artifact_records.append(
                {
                    "id": artifact_id,
                    "file_id": file_id,
                    "path": path,
                    "name": str(current_step.get("with_name") or current_step.get("name") or "<dynamic-or-default>"),
                    "entity_type": "workflow_artifact",
                    "job": current_job,
                    "step_id": step_id,
                    "direction": direction,
                    "declared_path": current_step.get("with_path"),
                    "action": uses,
                    "parser_mode": "structural",
                    "extraction_disposition": "explicit_artifact_action",
                    "unresolved_reasons": ["artifact_name_or_path_expression_not_evaluated"],
                }
            )
            job_records[current_job]["artifacts"].append(artifact_id)
        current_step = None

    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        list_item = line.lstrip().startswith("- ")
        match = YAML_KEY_RE.match(line)
        key = match.group("key").strip().strip("'\"") if match else None
        value = (match.group("value") or "").strip() if match else ""

        if current_step is not None and (
            indent < int(current_step["indent"])
            or (indent == int(current_step["indent"]) and list_item)
        ):
            finalize_step(number - 1)

        if permission_indent is not None and indent <= permission_indent and key != "permissions":
            permission_scope = None
            permission_indent = None

        if key == "jobs" and indent == 0:
            jobs_indent = indent
            continue

        if jobs_indent is not None and key and not list_item and indent > jobs_indent:
            if job_key_indent is None:
                job_key_indent = indent
            if indent == job_key_indent:
                finalize_step(number - 1)
                current_job = key
                current_job_indent = indent
                steps_indent = None
                job_id = stable_id("workflow", path, "job", key)
                job_records[key] = {
                    "id": job_id,
                    "file_id": file_id,
                    "path": path,
                    "name": key,
                    "entity_type": "workflow_job",
                    "steps": [],
                    "permissions": [],
                    "artifacts": [],
                    "parser_mode": "structural",
                    "extraction_disposition": "structurally_extracted",
                    "unresolved_reasons": ["job_matrix_needs_and_conditions_not_evaluated"],
                }
                continue

        if key == "steps" and current_job is not None and current_job_indent is not None and indent > current_job_indent:
            steps_indent = indent
            continue

        if (
            list_item
            and key
            and current_job is not None
            and steps_indent is not None
            and indent > steps_indent
        ):
            finalize_step(number - 1)
            index = step_index_by_job[current_job]
            step_index_by_job[current_job] += 1
            current_step = {
                "index": index,
                "start_line": number,
                "indent": indent,
                "with_indent": None,
            }
            current_step[key] = _yaml_scalar(value)
            continue

        if current_step is not None and key and indent > int(current_step["indent"]):
            if key == "with":
                current_step["with_indent"] = indent
            elif current_step.get("with_indent") is not None and indent > int(current_step["with_indent"]):
                current_step[f"with_{key}"] = _yaml_scalar(value)
            else:
                current_step[key] = _yaml_scalar(value)

        if key == "permissions":
            scope = f"job:{current_job}" if current_job and current_job_indent is not None and indent > current_job_indent else "workflow"
            permission_scope = scope
            permission_indent = indent
            if value:
                permission_id = stable_id("workflow", path, "permission", scope, "<aggregate>")
                permission_records.append(
                    {
                        "id": permission_id,
                        "file_id": file_id,
                        "path": path,
                        "name": "<aggregate>",
                        "entity_type": "workflow_permission",
                        "scope": scope,
                        "access": _yaml_scalar(value),
                        "parser_mode": "structural",
                        "extraction_disposition": "structurally_extracted",
                        "unresolved_reasons": ["permission_expression_not_evaluated"] if "${{" in value else [],
                    }
                )
                if current_job and scope.startswith("job:"):
                    job_records[current_job]["permissions"].append(permission_id)
            continue
        if permission_scope and permission_indent is not None and key and indent > permission_indent:
            permission_id = stable_id("workflow", path, "permission", permission_scope, key)
            permission_records.append(
                {
                    "id": permission_id,
                    "file_id": file_id,
                    "path": path,
                    "name": key,
                    "entity_type": "workflow_permission",
                    "scope": permission_scope,
                    "access": _yaml_scalar(value) or "<mapping>",
                    "parser_mode": "structural",
                    "extraction_disposition": "structurally_extracted",
                    "unresolved_reasons": ["permission_expression_not_evaluated"] if "${{" in value else [],
                }
            )
            if current_job and permission_scope.startswith("job:"):
                job_records[current_job]["permissions"].append(permission_id)

    finalize_step(len(source_lines))
    workflow_id = stable_id("workflow", path)
    workflow = {
        "id": workflow_id,
        "file_id": file_id,
        "path": path,
        "name": workflow_name or path.rsplit("/", 1)[-1],
        "entity_type": "workflow",
        "triggers": sorted(set(filter(None, triggers))),
        "jobs": sorted(job_records),
        "job_ids": sorted(str(record["id"]) for record in job_records.values()),
        "step_ids": sorted(str(record["id"]) for record in step_records),
        "permission_ids": sorted(str(record["id"]) for record in permission_records),
        "artifact_ids": sorted(str(record["id"]) for record in artifact_records),
        "parser_mode": "structural",
        "extraction_disposition": "structurally_extracted_with_explicit_limits",
        "unresolved_reasons": [
            "yaml_semantics_not_resolved",
            "reusable_workflows_actions_and_expressions_not_expanded",
            "artifact_inventory_limited_to_explicit_upload_download_actions",
        ],
    }
    return [workflow, *job_records.values(), *step_records, *permission_records, *artifact_records]


def parse_yaml_structural(path: str, file_id: str, text: str) -> ParseResult:
    """A bounded structural adapter; it never claims YAML semantic resolution."""

    result = ParseResult(parser="yaml_structural", parser_mode="structural")
    stack: list[tuple[int, str]] = []
    records: list[dict[str, Any]] = []
    job_indent: int | None = None
    workflow_jobs: list[str] = []
    workflow_name: str | None = None
    triggers: list[str] = []
    in_on = False
    on_indent = 0
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        indent = len(line) - len(line.lstrip(" "))
        if "\t" in line[: len(line) - len(line.lstrip())]:
            raise ParseFailure(f"{path}:{number}: tab indentation is not accepted by YAML adapter")
        if stripped.startswith("#"):
            result.line_context[number] = {
                "syntax_kind": "comment",
                "containing_symbol": stack[-1][1] if stack else None,
                "depth": len(stack),
                "unresolved_reasons": [],
            }
            continue
        match = YAML_KEY_RE.match(line)
        if match:
            key = match.group("key").strip().strip("'\"")
            value = (match.group("value") or "").strip()
            while stack and stack[-1][0] >= indent:
                stack.pop()
            parent = stack[-1][1] if stack else ""
            pointer = f"{parent}/{_json_pointer_part(key)}" if parent else f"/{_json_pointer_part(key)}"
            records.append(
                {
                    "id": stable_id("structured", path, pointer, number),
                    "file_id": file_id,
                    "path": path,
                    "pointer": pointer,
                    "value_type": "mapping" if not value else "scalar",
                    "depth": len(stack),
                    "value_digest": sha256_bytes(value.encode("utf-8")),
                    "value_preview": text_preview(value) if value else None,
                    "entity_type": (
                        "configuration_key"
                        if _configuration_like(path) or path.startswith(".github/workflows/")
                        else "structured_field"
                    ),
                    "extraction_disposition": "structurally_extracted",
                    "unresolved_reasons": ["yaml_structural_only_no_tag_anchor_or_merge_resolution"],
                }
            )
            result.line_context[number] = {
                "syntax_kind": "yaml_key_value" if value else "yaml_mapping_key",
                "containing_symbol": parent or None,
                "depth": len(stack),
                "unresolved_reasons": ["yaml_semantics_not_resolved"],
            }
            stack.append((indent, pointer))
            if key == "name" and indent == 0:
                workflow_name = value.strip("'\"")
            if key == "jobs" and indent == 0:
                job_indent = indent
            elif job_indent is not None and indent > job_indent and len(stack) == 2:
                workflow_jobs.append(key)
            if key == "on" and indent == 0:
                in_on, on_indent = True, indent
                if value:
                    triggers.extend(part.strip(" []'\"") for part in value.split(",") if part.strip())
            elif in_on and indent > on_indent and len(stack) == 2:
                triggers.append(key)
            elif in_on and indent <= on_indent:
                in_on = False
        else:
            reasons = ["yaml_line_not_a_simple_mapping"]
            if any(token in stripped for token in ("&", "*", "!", "<<:")):
                reasons.append("yaml_anchor_alias_tag_or_merge_unresolved")
            result.line_context[number] = {
                "syntax_kind": "yaml_sequence_or_scalar",
                "containing_symbol": stack[-1][1] if stack else None,
                "depth": len(stack),
                "unresolved_reasons": reasons,
            }
    result.structured = records
    result.unresolved_reasons.append("yaml_adapter_is_structural_not_semantic")
    if path.startswith(".github/workflows/"):
        result.workflows = _parse_github_workflow_entities(
            path,
            file_id,
            text,
            workflow_name=workflow_name,
            triggers=triggers,
        )
    return result


def parse_ini(path: str, file_id: str, text: str) -> ParseResult:
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    try:
        parser.read_string(text)
    except configparser.Error as exc:
        raise ParseFailure(f"{path}: INI parse failed: {exc}") from exc
    value = {section: dict(parser.items(section)) for section in parser.sections()}
    result = ParseResult(parser="stdlib_configparser")
    result.structured = _flatten_structured(path, file_id, value)
    section: str | None = None
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped[1:-1]
            kind = "ini_section"
        elif stripped.startswith(("#", ";")):
            kind = "comment"
        elif "=" in stripped or ":" in stripped:
            kind = "ini_key_value"
        else:
            kind = "ini_token"
        result.line_context[number] = {
            "syntax_kind": kind,
            "containing_symbol": section,
            "depth": 1 if section else 0,
            "unresolved_reasons": [],
        }
    for section in parser.sections():
        if "entry_points" not in section.lower():
            continue
        for group, declarations in parser.items(section):
            if group.lower().replace("-", "_") != "console_scripts":
                continue
            for declaration in declarations.splitlines():
                if "=" not in declaration:
                    continue
                name, target = (part.strip() for part in declaration.split("=", 1))
                if name and target:
                    _append_structural_cli_symbol(
                        result,
                        path=path,
                        file_id=file_id,
                        language="ini",
                        name=name,
                        target=target,
                        owner_pointer=f"{section}.console_scripts",
                        framework="python_console_scripts",
                    )
    return result


def parse_csv_file(path: str, file_id: str, text: str) -> ParseResult:
    try:
        reader = csv.reader(io.StringIO(text, newline=""), strict=True)
        rows_with_lines: list[tuple[list[str], int, int]] = []
        previous_end = 0
        for row in reader:
            end_line = reader.line_num
            rows_with_lines.append((row, previous_end + 1, end_line))
            previous_end = end_line
            if len(rows_with_lines) > MAX_STRUCTURED_RECORDS:
                raise ParseFailure(f"{path}: CSV row cap {MAX_STRUCTURED_RECORDS} exceeded")
    except csv.Error as exc:
        raise ParseFailure(f"{path}: CSV parse failed: {exc}") from exc
    rows = [row for row, _start, _end in rows_with_lines]
    result = ParseResult(parser="stdlib_csv")
    header = rows[0] if rows else []
    result.structured.append(
        {
            "id": stable_id("structured", path, "/dataset"),
            "file_id": file_id,
            "path": path,
            "pointer": "/dataset",
            "value_type": "table",
            "depth": 0,
            "value_digest": digest_object(rows),
            "entity_type": "csv_dataset",
            "row_count_including_header": len(rows),
            "data_row_count": max(0, len(rows) - 1),
            "row_accounting_state": "complete",
            "extraction_disposition": "structurally_extracted",
            "value_preview": f"{max(0, len(rows) - 1)} rows × {len(header)} columns",
            "unresolved_reasons": [],
        }
    )
    for index, (row, start_line, end_line) in enumerate(rows_with_lines):
        unresolved = []
        if index > 0 and len(row) != len(header):
            unresolved.append("csv_row_width_differs_from_header")
        result.structured.append(
            {
                "id": stable_id("structured", path, "/rows", index),
                "file_id": file_id,
                "path": path,
                "pointer": f"/rows/{index}",
                "value_type": "row",
                "depth": 1,
                "value_digest": digest_object(row),
                "value_preview": f"{len(row)} cells",
                "entity_type": "csv_header_row" if index == 0 else "csv_data_row",
                "row_index": index,
                "cell_count": len(row),
                "range": {
                    "start_line": start_line,
                    "start_column": 0,
                    "end_line": end_line,
                    "end_column": None,
                },
                "extraction_disposition": "structurally_extracted",
                "unresolved_reasons": unresolved,
            }
        )
    for index, name in enumerate(header):
        result.structured.append(
            {
                "id": stable_id("structured", path, "/columns", index, name),
                "file_id": file_id,
                "path": path,
                "pointer": f"/columns/{index}",
                "value_type": "column",
                "depth": 1,
                "value_digest": sha256_bytes(name.encode("utf-8")),
                "value_preview": text_preview(name),
                "entity_type": "csv_column",
                "extraction_disposition": "structurally_extracted",
                "unresolved_reasons": [],
            }
        )
    result.line_context = _context_all_nonblank(text, "csv_row")
    return result


CSS_BLOCK_RE = re.compile(r"(?s)([^{}]+)\{")
CSS_COMMENT_RE = re.compile(r"(?s)/\*.*?\*/")


def _offset_range(text: str, start: int, end: int) -> dict[str, int | None]:
    start_line = text.count("\n", 0, start) + 1
    start_column = start - (text.rfind("\n", 0, start) + 1)
    end_line = text.count("\n", 0, end) + 1
    end_column = end - (text.rfind("\n", 0, end) + 1)
    return {
        "start_line": start_line,
        "start_column": start_column,
        "end_line": end_line,
        "end_column": end_column,
    }


def _split_css_selectors(value: str) -> list[str]:
    selectors: list[str] = []
    start = 0
    square = 0
    round_depth = 0
    quote: str | None = None
    escaped = False
    for index, character in enumerate(value):
        if escaped:
            escaped = False
            continue
        if character == "\\":
            escaped = True
            continue
        if quote:
            if character == quote:
                quote = None
            continue
        if character in {"'", '"'}:
            quote = character
        elif character == "[":
            square += 1
        elif character == "]":
            square = max(0, square - 1)
        elif character == "(":
            round_depth += 1
        elif character == ")":
            round_depth = max(0, round_depth - 1)
        elif character == "," and square == 0 and round_depth == 0:
            if value[start:index].strip():
                selectors.append(value[start:index].strip())
            start = index + 1
    if value[start:].strip():
        selectors.append(value[start:].strip())
    return selectors


def _extract_css_entities(path: str, file_id: str, text: str, result: ParseResult) -> None:
    masked = CSS_COMMENT_RE.sub(lambda match: " " * len(match.group(0)), text)
    occurrences: Counter[str] = Counter()
    for match in CSS_BLOCK_RE.finditer(masked):
        raw_prelude = text[match.start(1) : match.end(1)]
        prelude = raw_prelude.strip()
        if not prelude:
            continue
        if prelude.startswith("@"):
            name = prelude.split(None, 1)[0]
            result.structured.append(
                {
                    "id": stable_id("structured", path, "css-at-rule", match.start(1)),
                    "file_id": file_id,
                    "path": path,
                    "pointer": f"/at-rules/{match.start(1)}",
                    "value_type": "css_at_rule",
                    "depth": 0,
                    "value_digest": sha256_bytes(prelude.encode("utf-8")),
                    "value_preview": text_preview(prelude),
                    "entity_type": "css_at_rule",
                    "name": name,
                    "extraction_disposition": "structurally_extracted",
                    "unresolved_reasons": ["css_at_rule_semantics_not_resolved"],
                }
            )
            continue
        selector_start_base = match.start(1) + (len(raw_prelude) - len(raw_prelude.lstrip()))
        for selector in _split_css_selectors(prelude):
            occurrence = occurrences[selector]
            occurrences[selector] += 1
            selector_offset = text.find(selector, selector_start_base, match.end(1))
            if selector_offset < 0:
                selector_offset = selector_start_base
            result.symbols.append(
                {
                    "id": stable_id("symbol", path, "css-selector", selector, occurrence),
                    "file_id": file_id,
                    "path": path,
                    "name": selector,
                    "qualified_name": f"selector:{selector}#{occurrence}",
                    "kind": "css_selector",
                    "language": "css",
                    "depth": 0,
                    "range": _offset_range(text, selector_offset, selector_offset + len(selector)),
                    "decorators": [],
                    "documentation": "",
                    "parameters": [],
                    "return_annotation": None,
                    "exported": False,
                    "digest": sha256_bytes(selector.encode("utf-8")),
                    "entity_type": "css_selector",
                    "extraction_disposition": "structurally_extracted",
                    "unresolved_reasons": [
                        "css_cascade_specificity_nesting_and_consumer_resolution_not_performed"
                    ],
                }
            )


class _MarkupEntityParser(HTMLParser):
    def __init__(self, path: str, file_id: str, language: str) -> None:
        super().__init__(convert_charrefs=False)
        self.path = path
        self.file_id = file_id
        self.language = language
        self.records: list[dict[str, Any]] = []
        self.occurrences: Counter[str] = Counter()

    def _append(self, tag: str, attrs: list[tuple[str, str | None]], self_closing: bool) -> None:
        raw = self.get_starttag_text() or f"<{tag}>"
        raw_name = re.match(r"<\s*([^\s/>]+)", raw)
        tag = raw_name.group(1) if raw_name else tag
        line, column = self.getpos()
        occurrence = self.occurrences[tag]
        self.occurrences[tag] += 1
        newline_count = raw.count("\n")
        end_line = line + newline_count
        end_column = column + len(raw) if newline_count == 0 else len(raw.rsplit("\n", 1)[-1])
        component_role = (
            "template"
            if tag == "template"
            else "custom_element"
            if "-" in tag
            else "markup_element"
        )
        self.records.append(
            {
                "id": stable_id("component", self.path, self.language, tag, occurrence),
                "file_id": self.file_id,
                "path": self.path,
                "name": f"{tag}[{occurrence}]",
                "tag_name": tag,
                "kind": "markup_element",
                "entity_type": f"{self.language}_element",
                "component_role": component_role,
                "self_closing": self_closing,
                "attribute_names": sorted(name for name, _value in attrs),
                "attributes_digest": digest_object(attrs),
                "exported": False,
                "range": {
                    "start_line": line,
                    "start_column": column,
                    "end_line": end_line,
                    "end_column": end_column,
                },
                "detection": "stdlib_html_start_tag_inventory",
                "extraction_disposition": "structurally_extracted_start_tag",
                "unresolved_reasons": ["markup_tree_rendering_and_component_ownership_not_resolved"],
            }
        )

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._append(tag, attrs, False)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._append(tag, attrs, True)


def _extract_markup_entities(path: str, file_id: str, language: str, text: str, result: ParseResult) -> None:
    parser = _MarkupEntityParser(path, file_id, language)
    try:
        parser.feed(text)
        parser.close()
    except (AssertionError, ValueError) as exc:
        raise ParseFailure(f"{path}: markup structural parse failed: {exc}") from exc
    result.components.extend(parser.records)
    result.unresolved_reasons.append(
        f"{language}_stdlib_html_parser_is_lenient_and_does_not_validate_rendered_tree"
    )


def _extract_command_entity(
    path: str,
    file_id: str,
    language: str,
    number: int,
    line: str,
    result: ParseResult,
) -> None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return
    try:
        tokens = shlex.split(stripped, posix=language == "shell")
    except ValueError:
        tokens = stripped.split()
    if not tokens:
        return
    command = tokens[0]
    if language == "powershell" and command in {"&", "."} and len(tokens) > 1:
        command = tokens[1]
    shell_controls = {
        "if",
        "then",
        "else",
        "elif",
        "fi",
        "for",
        "while",
        "do",
        "done",
        "case",
        "esac",
        "function",
        "try",
        "catch",
        "finally",
        "switch",
    }
    assignment = bool(re.match(r"^(?:export\s+)?[A-Za-z_][A-Za-z0-9_]*=", stripped)) or (
        language == "powershell" and bool(re.match(r"^\$[^=]+\s*=", stripped))
    )
    if assignment:
        entity_type = f"{language}_assignment"
    elif command.lower() in shell_controls or stripped in {"{", "}"}:
        entity_type = f"{language}_control_statement"
    else:
        entity_type = f"{language}_command_candidate"
    result.calls.append(
        {
            "id": stable_id("call", path, language, number, sha256_bytes(stripped.encode("utf-8"))),
            "file_id": file_id,
            "path": path,
            "callee": command,
            "containing_symbol": None,
            "range": {
                "start_line": number,
                "start_column": len(line) - len(line.lstrip()),
                "end_line": number,
                "end_column": len(line),
            },
            "resolved": False,
            "entity_type": entity_type,
            "statement_digest": sha256_bytes(stripped.encode("utf-8")),
            "extraction_disposition": "lexical_candidate",
            "unresolved_reasons": [
                f"{language}_tokenization_does_not_resolve_aliases_functions_pipelines_or_continuations"
            ],
        }
    )


def parse_generic_text(path: str, file_id: str, language: str, text: str) -> ParseResult:
    result = ParseResult(parser=f"{language}_lexical", parser_mode="structural")
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(("#", "//", "/*", "*", "<!--", ";")):
            kind = "comment"
        elif language == "css" and "{" in stripped:
            kind = "css_rule"
        elif language in {"html", "svg"} and stripped.startswith("<"):
            kind = "markup"
        elif language in {"shell", "powershell"}:
            kind = "command_or_assignment"
        elif language == "config":
            kind = "config_directive"
        else:
            kind = "text"
        result.line_context[number] = {
            "syntax_kind": kind,
            "containing_symbol": None,
            "depth": max(0, (len(line) - len(line.lstrip())) // 2),
            "unresolved_reasons": [f"{language}_adapter_is_lexical_only"],
        }
        if language in {"shell", "powershell"} and kind != "comment":
            _extract_command_entity(path, file_id, language, number, line, result)
        if language in {"config", "jsonc", "manifest"} and kind != "comment":
            key_match = re.match(r'^\s*["\']?([^:=\s"\']+)["\']?\s*[:=]', line)
            key = key_match.group(1) if key_match else f"line-{number}"
            result.structured.append(
                {
                    "id": stable_id("structured", path, "directive", number, key),
                    "file_id": file_id,
                    "path": path,
                    "pointer": f"/directives/{number}/{_json_pointer_part(key)}",
                    "value_type": "configuration_directive",
                    "depth": 0,
                    "value_digest": sha256_bytes(stripped.encode("utf-8")),
                    "value_preview": text_preview(stripped),
                    "entity_type": "configuration_key" if key_match else "configuration_directive",
                    "extraction_disposition": "lexically_extracted",
                    "unresolved_reasons": [f"{language}_configuration_semantics_not_resolved"],
                }
            )
    if language == "css":
        _extract_css_entities(path, file_id, text, result)
    elif language in {"html", "svg"}:
        _extract_markup_entities(path, file_id, language, text, result)
    result.unresolved_reasons.append(f"{language}_adapter_is_lexical_only")
    if path.rsplit("/", 1)[-1].lower().startswith("requirements"):
        _dependencies_from_requirements(path, file_id, text, result)
    return result


def _dependencies_from_json(path: str, file_id: str, value: Any, result: ParseResult) -> None:
    if not isinstance(value, dict) or path.rsplit("/", 1)[-1].lower() != "package.json":
        return
    for scope in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        items = value.get(scope)
        if not isinstance(items, dict):
            continue
        for name, constraint in sorted(items.items()):
            result.dependencies.append(
                {
                    "id": stable_id("dependency", path, scope, name),
                    "file_id": file_id,
                    "path": path,
                    "ecosystem": "npm",
                    "scope": scope,
                    "name": str(name),
                    "constraint": str(constraint),
                    "resolved_version": None,
                }
            )


def _dependencies_from_toml(path: str, file_id: str, value: Any, result: ParseResult) -> None:
    if path.rsplit("/", 1)[-1].lower() != "pyproject.toml" or not isinstance(value, dict):
        return
    project = value.get("project") or {}
    deps = project.get("dependencies") if isinstance(project, dict) else []
    for item in deps if isinstance(deps, list) else []:
        name = re.split(r"[<>=!~;\s\[]", str(item), maxsplit=1)[0]
        result.dependencies.append(
            {
                "id": stable_id("dependency", path, "project", item),
                "file_id": file_id,
                "path": path,
                "ecosystem": "python",
                "scope": "project",
                "name": name,
                "constraint": str(item),
                "resolved_version": None,
            }
        )
    optional = project.get("optional-dependencies") if isinstance(project, dict) else {}
    if isinstance(optional, dict):
        for group, items in sorted(optional.items()):
            for item in items if isinstance(items, list) else []:
                name = re.split(r"[<>=!~;\s\[]", str(item), maxsplit=1)[0]
                result.dependencies.append(
                    {
                        "id": stable_id("dependency", path, f"optional:{group}", item),
                        "file_id": file_id,
                        "path": path,
                        "ecosystem": "python",
                        "scope": f"optional:{group}",
                        "name": name,
                        "constraint": str(item),
                        "resolved_version": None,
                    }
                )


def _dependencies_from_requirements(path: str, file_id: str, text: str, result: ParseResult) -> None:
    for number, line in enumerate(text.splitlines(), start=1):
        value = line.strip()
        if not value or value.startswith("#"):
            continue
        if value.startswith(("-r", "--requirement")):
            name = value.split(maxsplit=1)[-1]
            scope = "include"
        elif value.startswith("-"):
            name, scope = value, "option"
        else:
            name = re.split(r"[<>=!~;\s\[]", value, maxsplit=1)[0]
            scope = "runtime"
        result.dependencies.append(
            {
                "id": stable_id("dependency", path, number, value),
                "file_id": file_id,
                "path": path,
                "ecosystem": "python",
                "scope": scope,
                "name": name,
                "constraint": value,
                "resolved_version": None,
            }
        )


def parse_by_language(path: str, file_id: str, language: str, text: str) -> ParseResult:
    if language == "python":
        return parse_python(path, file_id, text)
    if language == "markdown":
        return parse_markdown(path, file_id, text)
    if language == "json":
        return parse_json(path, file_id, text)
    if language == "jsonl":
        return parse_jsonl(path, file_id, text)
    if language == "toml":
        return parse_toml(path, file_id, text)
    if language == "yaml":
        return parse_yaml_structural(path, file_id, text)
    if language == "ini":
        return parse_ini(path, file_id, text)
    if language == "csv":
        return parse_csv_file(path, file_id, text)
    return parse_generic_text(path, file_id, language, text)
