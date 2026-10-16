"""Token normal forms for the closed, named computation-form ratchet.

These tripwires do not establish absence of computation. Undetected forms need
review. Comments are discarded by language tokenizers, while string payloads
are inspected separately rather than discarded as comments.
"""
import ast
from collections import Counter
import io
import json
import tokenize


def python_stream(text, tree):
    """Keep semantic tokens; mask f-strings for identical 3.10--3.14 tokenization."""
    lines = text.splitlines(keepends=True)
    offsets, offset = [], 0
    for line in lines:
        offsets.append(offset)
        offset += len(line)
    offsets.append(offset)

    def position(line, column):
        # AST columns are UTF-8 byte offsets, unlike tokenize's character columns.
        return offsets[line - 1] + len(lines[line - 1].encode("utf-8")[:column].decode("utf-8"))

    spans = sorted({(position(n.lineno, n.col_offset), position(n.end_lineno, n.end_col_offset))
                    for n in ast.walk(tree) if isinstance(n, ast.JoinedStr)})
    masks = []
    for start, end in spans:
        if masks and start < masks[-1][1]:
            masks[-1] = (masks[-1][0], max(end, masks[-1][1]))
        else:
            masks.append((start, end))
    for start, end in reversed(masks):
        old = text[start:end]
        text = text[:start] + "('__census_payload__'" + "\n" * old.count("\n") + ")" + text[end:]
    ignored = {tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT,
               tokenize.DEDENT, tokenize.ENDMARKER, tokenize.ENCODING}
    tokens = []
    for token in tokenize.generate_tokens(io.StringIO(text).readline):
        if token.type in ignored:
            continue
        kind, value = "op", token.string
        if token.type == tokenize.NAME:
            kind = "name"
        elif token.type == tokenize.NUMBER:
            kind, value = "number", repr(ast.literal_eval(token.string))
        elif token.type == tokenize.STRING:
            kind, value = "string", ast.literal_eval(token.string)
            if isinstance(value, bytes):
                value = value.hex()
        tokens.append([kind, value, token.start[0]])
    return tokens


def string_payloads(tree):
    """Docstrings are inert documentation; used string constants may contain code."""
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant):
                docstrings.add(id(node.body[0].value))
    result = []

    def visit(node):
        if isinstance(node, ast.JoinedStr):
            # A template is one payload, not several falsely unclosed HTML
            # documents. Interpolations stay opaque; their expressions are
            # independently visited by the normal AST rules.
            text = "".join(value.value if isinstance(value, ast.Constant) and isinstance(value.value, str)
                           else "__census_interpolation__" for value in node.values)
            result.append((text, node.lineno))
            for value in node.values:
                if isinstance(value, ast.FormattedValue):
                    visit(value.value)
            return
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            result.append((node.value, node.lineno))
        for child in ast.iter_child_nodes(node):
            visit(child)

    visit(tree)
    return result


def lexical_sites(path, tokens, symbol, digest, occurrences):
    """Match a named token grammar, never raw whitespace/comment spellings."""
    result = []
    values = [token[1] for token in tokens]

    def emit(start, end, rule):
        normalized = json.dumps([token[:2] for token in tokens[start:end]], ensure_ascii=True,
                                separators=(",", ":"))
        fingerprint = digest(normalized)
        key = (path, symbol, rule, fingerprint)
        occurrences[key] += 1
        result.append(dict(path=path, symbol=symbol, rule=rule, fingerprint=fingerprint,
                           occurrence=occurrences[key], line=tokens[start][2],
                           expression=" ".join(str(value) for value in values[start:end])[:240]))

    for index, (kind, value, _line) in enumerate(tokens):
        tail = values[index: index + 5]
        if kind == "name" and value in {"eval", "exec", "Function"} and tail[1:2] == ["("]:
            emit(index, index + 2, "dynamic-code")
        if kind == "name" and value in {"queue", "visited", "adjacency", "neighbours", "neighbors"}:
            if len(tail) >= 4 and tail[1] == "." and tail[2] in {"shift", "pop", "popleft", "add", "push", "append"} and tail[3] == "(":
                emit(index, index + 4, "graph-worklist")
        if (kind == "op" and value == "." and tail[1:2] in (["length"], ["size"])) or (
                kind == "name" and value in {"len", "sum", "Counter"} and tail[1:2] == ["("]):
            emit(index, index + 2, "raw-count")
        if kind == "op" and value in {">=", "<=", ">", "<", "==", "===", "!=", "!=="}:
            if index + 1 < len(tokens) and tokens[index + 1][0] == "number":
                emit(index, index + 2, "raw-threshold")
        if kind == "op" and tail[:3] == [".", "filter", "("]:
            depth, end = 1, index + 3
            while end < len(tokens) and depth:
                if tokens[end][0] == "op":
                    depth += (values[end] == "(") - (values[end] == ")")
                end += 1
            if not depth and values[end:end + 2] == [".", "length"]:
                emit(index, end + 2, "filter-count")
    return result


def lexical_counter():
    return Counter()
