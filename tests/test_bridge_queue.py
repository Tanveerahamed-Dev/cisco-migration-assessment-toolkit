"""Bridge-candidate promotion-queue depth — the honest, watermarked backlog.

The property under test is the one that makes this module worth existing: the *lifetime* count
of ``bridge-candidate`` tags in ``docs/log.md`` only ever grows (``/ingest`` never rewrites the
append-only log), so it must NOT be reported as "pending". Pending is watermarked by the last
``/ingest`` date — tags in sessions strictly after it. A fresh ingest ⇒ 0 pending even with a
large lifetime; that is the cried-wolf regression these tests pin.
"""
from cisco_toolkit.bridge_queue import bridge_queue_status, format_status

# Three dated sessions, newest first (the docs/log.md convention), 4 tagged lessons total.
LOG = """# Session log

## [2026-07-10] — newest session
- `!lesson` a generic NX-OS trap. bridge-candidate
- `!lesson` another client-generic lesson. bridge-candidate

## [2026-07-08] — middle session
- `!lesson` an older lesson. bridge-candidate

## [2026-07-05] — oldest session
- `!lesson` an ancient lesson. bridge-candidate
"""


def test_lifetime_counts_every_tag_regardless_of_ingest():
    assert bridge_queue_status(LOG)["lifetime"] == 4
    assert bridge_queue_status(LOG, "2026-07-11")["lifetime"] == 4  # ingest does not shrink lifetime


def test_pending_is_strictly_after_the_watermark():
    # ingest on 07-08 swept up the 07-08 and 07-05 sessions; only the two 07-10 tags remain pending.
    st = bridge_queue_status(LOG, "2026-07-08")
    assert st["pending"] == 2
    assert st["last_ingest"] == "2026-07-08"


def test_fresh_ingest_means_empty_queue_not_the_lifetime_count():
    # THE cried-wolf regression: 4 lifetime tags but a fresh ingest AFTER the newest session -> 0 pending.
    st = bridge_queue_status(LOG, "2026-07-11")
    assert st["lifetime"] == 4
    assert st["pending"] == 0
    rendered = format_status(st)
    assert "0 pending" in rendered
    assert "run /ingest" not in rendered  # must not nag when the queue is empty


def test_real_backlog_nags_to_run_ingest():
    # ingest on 07-06: the 07-08 (1) and 07-10 (2) sessions are after it -> 3 genuinely pending.
    st = bridge_queue_status(LOG, "2026-07-06")
    assert st["pending"] == 3
    rendered = format_status(st)
    assert "3 lessons pending" in rendered
    assert "run /ingest" in rendered


def test_no_watermark_reports_pending_unknown_never_a_silent_zero():
    st = bridge_queue_status(LOG, None)
    assert st["pending"] is None  # honest: unknown, not 0
    assert st["last_ingest"] is None
    assert st["lifetime"] == 4
    assert "lifetime" in format_status(st) and "pending" in format_status(st)


def test_invalid_watermark_is_treated_as_absent():
    st = bridge_queue_status(LOG, "not-a-date")
    assert st["pending"] is None
    assert st["last_ingest"] is None


def test_singular_and_plural_rendering():
    # plural: the 07-10 session (2 tags) is the only one after a 07-09 watermark.
    assert "2 lessons pending" in format_status(bridge_queue_status(LOG, "2026-07-09"))
    # singular: a one-tag log with an earlier watermark.
    one = "## [2026-07-10] — s\n- only one. bridge-candidate\n"
    assert "1 lesson pending" in format_status(bridge_queue_status(one, "2026-07-09"))


def test_newest_session_reported():
    assert bridge_queue_status(LOG)["newest_session"] == "2026-07-10"


def test_preamble_tag_counts_lifetime_but_never_pending():
    # a stray tag before any dated header is pre-history: lifetime yes, pending no.
    text = "intro mentions bridge-candidate once\n\n## [2026-07-10] — s\n- x bridge-candidate\n"
    st = bridge_queue_status(text, "2026-07-11")
    assert st["lifetime"] == 2
    assert st["pending"] == 0


def test_total_on_bad_and_empty_input():
    assert bridge_queue_status(None, None)["lifetime"] == 0
    assert bridge_queue_status(None, None)["pending"] is None
    empty = bridge_queue_status("", "2026-07-11")
    assert empty["lifetime"] == 0 and empty["pending"] == 0 and empty["newest_session"] is None


def test_main_ingest_flag_reports_pending(tmp_path, capsys):
    from cisco_toolkit import bridge_queue as bq
    log = tmp_path / "log.md"
    log.write_text("## [2026-07-10] a\n- x bridge-candidate\n", encoding="utf-8")
    assert bq.main([str(log), "--ingest", "2026-07-09"]) == 0   # a 07-10 candidate is after the watermark
    assert "pending" in capsys.readouterr().out.lower()


def test_main_missing_log_is_reported_never_a_gate(capsys):
    from cisco_toolkit import bridge_queue as bq
    assert bq.main(["no-such-log.md"]) == 0                     # a report, always exit 0
    assert "log not found" in capsys.readouterr().out
