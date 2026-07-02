"""Plan-A Tier-3 #16: the PARSER_CONTRACTS totality gate.

cmdio.PARSER_CONTRACTS is the as-built command -> parser contract for the SSH `show`
channel. This reconciles it against BOTH cisco_toolkit.parse (every named parser exists
and is callable) and build.py's OWN source (no phantom command; every inline
`_safe_parse(parse_X, _load_cmd_output(cmd_to_file, "show ..."))` dispatch is registered
with parse_X among its parsers) -- so the contract cannot silently drift from the code.
That drift IS the recurring bug class this repo keeps re-hitting: a collected command
whose parser was renamed/removed, or a new parser wired with no contract entry.

Additive & behaviour-neutral: PARSER_CONTRACTS is data, build.py still dispatches
directly, so the pipeline golden is untouched (proven by the golden suite staying green).
"""
import re
from pathlib import Path

from cisco_toolkit import cmdio, parse
from cisco_toolkit.cmdio import PARSER_CONTRACTS

_BUILD_SRC = (Path(cmdio.__file__).parent / "build.py").read_text(encoding="utf-8")

# Every inline `_safe_parse(parse_X, _load_cmd_output(cmd_to_file, "CMD"...))` -- DOTALL so
# the many multi-line call sites match; captures the parser and the FIRST command literal
# (single- or double-quoted). Variable command args (e.g. a loop var) carry no literal and
# are correctly skipped.
_INLINE = re.compile(
    r"""_safe_parse\(\s*(parse_\w+)\s*,\s*_load_cmd_output\(\s*cmd_to_file\s*,\s*["']([^"']+)["']""",
    re.DOTALL)


def test_every_contract_parser_exists_and_is_callable():
    bad = [(cmd, p) for cmd, parsers in PARSER_CONTRACTS.items()
           for p in parsers if not callable(getattr(parse, p, None))]
    assert not bad, f"PARSER_CONTRACTS names non-existent/non-callable parser(s): {sorted(bad)}"


def test_no_contract_command_is_a_phantom():
    absent = [cmd for cmd in PARSER_CONTRACTS
              if f'"{cmd}"' not in _BUILD_SRC and f"'{cmd}'" not in _BUILD_SRC]
    assert not absent, f"PARSER_CONTRACTS lists command(s) build.py never dispatches: {absent}"


def test_inline_show_dispatch_is_registered():
    """The anti-drift guard: a new inline show-command builder that forgets the contract
    (or maps to a renamed parser) fails here."""
    unregistered = []
    for parser, cmd in _INLINE.findall(_BUILD_SRC):
        if not cmd.startswith("show "):
            continue                       # controller-REST / cloud channels are out of scope
        parsers = PARSER_CONTRACTS.get(cmd)
        if parsers is None or parser not in parsers:
            unregistered.append((cmd, parser))
    assert not unregistered, (
        "inline show-command dispatch(es) missing/mismatched in PARSER_CONTRACTS "
        f"(add the cmd -> parser): {sorted(set(unregistered))}")


def test_contract_is_show_scoped_and_substantial():
    assert len(PARSER_CONTRACTS) >= 50, "the show-channel contract lost coverage"
    off = [c for c in PARSER_CONTRACTS if not c.startswith("show ")]
    assert not off, f"PARSER_CONTRACTS is scoped to `show ` commands; off-scope keys: {off}"


def test_parser_for_resolver():
    assert cmdio.parser_for("show vpc") == ("parse_vpc",)
    assert "parse_mroute_entries" in cmdio.parser_for("show ip mroute")
    assert cmdio.parser_for("no such command") == ()
