"""Plan-A #16 (typed-default half): the PARSER_RETURN_SHAPE totality + anti-drift gate.

cmdio.PARSER_RETURN_SHAPE maps every parse_* to its empty-container SHAPE so _safe_parse's
fail-soft fallback returns the RIGHT empty ([] for a list parser, {} for a dict parser),
closing the {}-vs-[] hazard. This reconciles that frozen table against (a) the live set of
parsers, (b) their real return annotations (outermost type), and (c) the build.py call-site
defaults -- so it can never silently drift from the code.
"""
import inspect
import re
import typing
from pathlib import Path

from cisco_toolkit import cmdio, parse
from cisco_toolkit.cmdio import PARSER_RETURN_SHAPE, _empty_for

_PARSERS = {n: getattr(parse, n) for n in dir(parse)
            if n.startswith("parse_") and callable(getattr(parse, n))}
_BUILD_SRC = (Path(cmdio.__file__).parent / "build.py").read_text(encoding="utf-8")


def _annotated_shape(fn):
    """Empty-shape implied by fn's return ANNOTATION via the OUTERMOST type (get_origin), or
    None if unannotated. Dict->'dict'; List/Set/Tuple->'list'; str/int scalar. Using get_origin
    (not a substring check) is what correctly reads List[Dict[...]] as a LIST."""
    ann = inspect.signature(fn).return_annotation
    if ann is inspect.Signature.empty:
        return None
    origin = typing.get_origin(ann) or ann
    if origin is dict:
        return "dict"
    if origin in (list, set, tuple):
        return "list"
    if origin is str:
        return "str"
    if origin is int:
        return "int"
    return "OTHER:" + str(ann)


def test_every_parser_has_a_registered_shape():
    missing = sorted(set(_PARSERS) - set(PARSER_RETURN_SHAPE))
    assert not missing, f"parsers with no PARSER_RETURN_SHAPE entry (a new parser?): {missing}"
    extra = sorted(set(PARSER_RETURN_SHAPE) - set(_PARSERS))
    assert not extra, f"PARSER_RETURN_SHAPE names non-existent parser(s): {extra}"


def test_registry_agrees_with_return_annotations():
    """The frozen table must match each parser's REAL return annotation. The lone unannotated
    parser (parse_aws_security_groups) is registered 'list' by design (list-or-None)."""
    bad = []
    for name, fn in _PARSERS.items():
        want = _annotated_shape(fn)
        if want is None:                       # unannotated -> registry states intent
            continue
        if PARSER_RETURN_SHAPE.get(name) != want:
            bad.append((name, f"registry={PARSER_RETURN_SHAPE.get(name)}", f"annotation={want}"))
    assert not bad, f"PARSER_RETURN_SHAPE disagrees with return annotations: {bad}"


def _safe_parse_call_defaults(src):
    """Yield (parser_name, declared_shape, sentinel) for each _safe_parse(...) call, where
    declared_shape is 'dict'/'list' when the site pins one via a trailing `or {}`/`or []` or an
    inner `_default={}`/`_default=[]`, else None. `sentinel` is True when the call is tagged with
    a `shape-sentinel` marker in the comment immediately after it -- the ONE coverage-honest idiom
    where a deliberately OFF-registry crash default is CORRECT because the result is isinstance-
    guarded to 'not observed' before any shape-specific consumer sees it (build_cloud). Balanced-
    paren scan because the calls nest _load_cmd_output(...), which a flat regex cannot span."""
    out = []
    for m in re.finditer(r"_safe_parse\(", src):
        pm = re.match(r"\s*(parse_\w+)", src[m.end():])
        if not pm:
            continue
        parser = pm.group(1)
        depth, j = 1, m.end()
        while j < len(src) and depth:
            depth += (src[j] == "(") - (src[j] == ")")
            j += 1
        inside, tail = src[m.end():j], src[j:j + 8].lstrip()
        shape = None
        if "_default=[]" in inside:
            shape = "list"
        elif "_default={}" in inside:
            shape = "dict"
        elif tail.startswith("or []"):
            shape = "list"
        elif tail.startswith("or {}"):
            shape = "dict"
        sentinel = "shape-sentinel" in src[j:j + 200]       # marker in the comment right after the call
        out.append((parser, shape, sentinel))
    return out


def test_build_call_site_defaults_match_the_registry():
    """The anti-drift guard: wherever a build.py _safe_parse site pins an empty default
    (`or {}` / `or []` / `_default=`), it must equal the parser's registered shape -- so a
    future `or {}` on a list parser (the exact hazard) turns this red. The SOLE exemption is a
    `shape-sentinel`-tagged site: a deliberately OFF-registry crash default that is immediately
    isinstance-guarded to 'not observed' (build_cloud), so the sentinel never reaches a
    shape-specific consumer. An UNMARKED mismatch is still the hazard -> still red."""
    mismatches = []
    for parser, shape, sentinel in _safe_parse_call_defaults(_BUILD_SRC):
        if shape is None or sentinel:
            continue
        reg = PARSER_RETURN_SHAPE.get(parser)
        if reg is not None and reg != shape:
            mismatches.append((parser, f"call-site={shape}", f"registry={reg}"))
    assert not mismatches, f"build.py _safe_parse default disagrees with the parser's shape: {mismatches}"


def test_shape_sentinel_exemption_is_scoped_to_the_one_documented_site():
    """The `shape-sentinel` exemption must cover EXACTLY the one documented coverage-honest site
    (parse_aws_security_groups in build_cloud) and no other -- so the exemption can never silently
    spread to hide a real shape hazard, and can't be quietly dropped from build_cloud either. Only
    an OFF-registry default counts (a sentinel tag on a matching default is a harmless no-op)."""
    exempt = [parser for parser, shape, sentinel in _safe_parse_call_defaults(_BUILD_SRC)
              if sentinel and shape is not None and PARSER_RETURN_SHAPE.get(parser) not in (None, shape)]
    assert exempt == ["parse_aws_security_groups"], f"unexpected shape-sentinel exemptions: {exempt}"


def test_empty_for_returns_a_fresh_correct_container():
    assert _empty_for(parse.parse_acls) == {} and isinstance(_empty_for(parse.parse_acls), dict)
    assert _empty_for(parse.parse_ospf_neighbors) == [] and isinstance(_empty_for(parse.parse_ospf_neighbors), list)
    assert _empty_for(parse.parse_neighbors_detail) == []          # the List[Dict[...]] parser
    a = _empty_for(parse.parse_acls)
    a["x"] = 1
    assert _empty_for(parse.parse_acls) == {}                      # fresh container each call, no aliasing
    assert _empty_for(lambda: None) == {}                          # unknown fn -> backward-compatible {}
