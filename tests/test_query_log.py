"""Tests for the real-query log (P2-0a) — cisco_toolkit.recall.log_query and its two real surfaces.

D10's dense-lane precondition ("classify 30 real queries by type FIRST" — the d10 design doc §5)
needs a real-query log to EXIST; P2-0a instruments the real surfaces: the recall CLI
(surface=recall) and the prose-only /ask command via the --log-only arm (surface=ask). Pins the
P2-0a contract:
  * one JSON line per call, exactly {date, query, surface} — nothing else, append-only;
  * FAIL-OPEN — a logging failure returns False / never raises, and retrieval still completes;
  * the synthetic --eval path (the labeled experiment) NEVER logs, so the real mix stays real;
  * the SSOT registration (docs/ssot.md row, tracked owner file, /ask wiring) cannot silently rot.
"""
import json
import pathlib
import re

from cisco_toolkit import recall as R

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _lines(p):
    return p.read_text(encoding="utf-8").splitlines()


def test_log_query_appends_exactly_one_line_with_exact_schema(tmp_path):
    p = tmp_path / "query_log.jsonl"
    assert R.log_query("circuit breaker cooldown", path=str(p)) is True
    lines = _lines(p)
    assert len(lines) == 1, "one recall call must append exactly one line"
    row = json.loads(lines[0])
    assert set(row) == {"date", "query", "surface"}, "P2-0a schema: date/query/surface — nothing else"
    assert row["query"] == "circuit breaker cooldown"
    assert row["surface"] == "recall"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", row["date"])


def test_log_query_is_append_only_and_carries_the_surface(tmp_path):
    p = tmp_path / "query_log.jsonl"
    assert R.log_query("first", path=str(p)) is True
    assert R.log_query("second", surface="ask", path=str(p)) is True
    lines = _lines(p)
    assert len(lines) == 2, "appends, never truncates"
    assert json.loads(lines[0])["query"] == "first"
    row = json.loads(lines[1])
    assert row["query"] == "second" and row["surface"] == "ask"


def test_log_query_failure_degrades_silently_never_raises(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("a file where the log's parent dir must go", encoding="utf-8")
    p = blocker / "sub" / "query_log.jsonl"        # makedirs under a FILE -> OSError inside
    assert R.log_query("q", path=str(p)) is False  # honest False, no exception (fail-open)


def _quiet_offline(monkeypatch, root):
    """Point the CLI at an isolated root and silence the subprocess/store signals (fast + hermetic)."""
    monkeypatch.setattr(R, "_repo_root", lambda: str(root))
    monkeypatch.setattr(R, "graph_rank", lambda q, **kw: [])
    monkeypatch.setattr(R, "load_vault_digest", lambda *a, **kw: {})


def test_cli_real_query_logs_once_and_retrieval_completes(tmp_path, monkeypatch, capsys):
    _quiet_offline(monkeypatch, tmp_path)
    assert R.main(["circuit breaker cooldown"]) == 0
    lines = _lines(tmp_path / "docs" / "quality" / "query_log.jsonl")
    assert len(lines) == 1, "one CLI query must append exactly one line"
    row = json.loads(lines[0])
    assert row["surface"] == "recall" and row["query"] == "circuit breaker cooldown"
    assert 'recall "circuit breaker cooldown"' in capsys.readouterr().out   # retrieval still rendered


def test_cli_logging_failure_never_breaks_retrieval(tmp_path, monkeypatch, capsys):
    _quiet_offline(monkeypatch, tmp_path)
    # a FILE where docs/ must go -> the log write fails, retrieval must be unaffected (fail-open)
    (tmp_path / "docs").write_text("blocker", encoding="utf-8")
    assert R.main(["circuit breaker cooldown"]) == 0
    assert 'recall "circuit breaker cooldown"' in capsys.readouterr().out


def test_cli_log_only_is_the_ask_surface_arm(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(R, "_repo_root", lambda: str(tmp_path))
    q = "which VLANs stretch between the two sites"
    assert R.main(["--log-only", "--surface=ask", q]) == 0
    lines = _lines(tmp_path / "docs" / "quality" / "query_log.jsonl")
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["surface"] == "ask" and row["query"] == q
    assert "logged" in capsys.readouterr().out


def test_cli_log_only_failure_still_exits_zero_and_says_so(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(R, "_repo_root", lambda: str(tmp_path))
    (tmp_path / "docs").write_text("blocker", encoding="utf-8")
    assert R.main(["--log-only", "--surface=ask", "q"]) == 0   # /ask is never blocked by logging
    # coverage-honest: it never claims a write it did not make
    assert "nothing recorded" in capsys.readouterr().out


def test_eval_path_never_logs_the_synthetic_labeled_set(tmp_path, monkeypatch):
    _quiet_offline(monkeypatch, tmp_path)
    assert R.main(["--eval"]) == 0
    assert not (tmp_path / "docs" / "quality" / "query_log.jsonl").exists(), (
        "--eval wrote the labeled experiment into the REAL-query log — the D10 mix is polluted")


def test_registry_and_ask_command_wire_the_owner():
    """Ratchet guard (Law 1): the registry row, the tracked owner file, and the /ask wiring must all
    stay present — dropping any one silently un-registers the query-mix owner or starves the log."""
    reg = (ROOT / "docs" / "ssot.md").read_text(encoding="utf-8")
    assert "query_log.jsonl" in reg, "docs/ssot.md no longer registers the query-mix owner"
    assert "log_query" in reg, "docs/ssot.md no longer names the writer symbol on the row"
    assert (ROOT / "docs" / "quality" / "query_log.jsonl").exists(), "the owner file is gone"
    ask = (ROOT / ".claude" / "commands" / "ask.md").read_text(encoding="utf-8")
    assert "--log-only" in ask and "--surface=ask" in ask, (
        "/ask no longer invokes the --log-only arm — its questions would stop reaching the log")
