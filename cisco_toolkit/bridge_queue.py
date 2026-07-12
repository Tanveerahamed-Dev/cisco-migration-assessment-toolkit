"""Bridge-candidate promotion queue — the *honest* repo→vault backlog depth.

``/retro`` tags client-generic lessons ``bridge-candidate`` in ``docs/log.md``; a separate
vault-cwd session promotes them with the vault's ``/ingest`` (ADR 0001, Rule-3 sanitized).
``docs/log.md`` is **append-only** and ``/ingest`` never rewrites it, so a lesson keeps its
``bridge-candidate`` tag forever — including after it has already been promoted.

That is the subtlety this module exists for. The *cumulative* count of ``bridge-candidate``
tokens only ever grows, so surfacing it as "N await promotion — run /ingest" cries wolf
permanently: the morning brief read "34 await promotion" on a day ``/ingest`` had already run
that morning. The real queue depth is **watermarked** — a lesson is *pending* only if it was
logged in a session dated strictly after the last ``/ingest``. Everything on or before the
watermark was swept up by that ingest.

The watermark (the last ``/ingest`` date) is knowable only from the vault's own log, which the
SessionStart brief already reads for its rot-watch. This module stays **pure and offline**: it
takes the log text and the watermark date as *inputs* and never touches the vault itself, so it
is trivially testable and safe to import from the air-gapped morning briefing (which passes no
watermark and gets an honest lifetime-only view — pending reported as unknown, never a silent 0).

Distinct from ``cisco_toolkit.learnings`` (the linter for the distilled ``learnings.md`` store)
and from ``docs/log.md`` itself (the raw ``/retro`` source this reads). Pure stdlib, total on
bad input.
"""
from __future__ import annotations

import re
from typing import Dict, Iterator, Optional, Tuple

# A session block in docs/log.md opens with '## [YYYY-MM-DD] — <headline>' (newest first).
_SESSION_RE = re.compile(r"^##\s*\[(\d{4}-\d{2}-\d{2})\]", re.M)
_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# One '## [date]' lesson carries exactly one 'bridge-candidate' token at its tail, so counting
# token occurrences counts tagged lessons (matches the historical morning-briefing regex).
_TAG = "bridge-candidate"


def _is_iso(value: object) -> bool:
    """True only for a well-formed ``YYYY-MM-DD`` string. A bad/absent watermark must degrade to
    'pending unknown', never be trusted as a real date (which would mis-bucket every lesson)."""
    return isinstance(value, str) and bool(_ISO_RE.match(value))


def _sessions(log_text: object) -> Iterator[Tuple[Optional[str], str]]:
    """Yield ``(date_str, block_text)`` per session, in file order. Any preamble before the first
    dated header is yielded with ``date_str=None`` (undated → treated as pre-history)."""
    text = log_text if isinstance(log_text, str) else ""
    matches = list(_SESSION_RE.finditer(text))
    if not matches:
        yield None, text
        return
    if matches[0].start() > 0:
        yield None, text[: matches[0].start()]
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        yield m.group(1), text[m.start():end]


def bridge_queue_status(log_text: object, last_ingest_date: Optional[str] = None) -> Dict[str, object]:
    """Promotion-queue status for the repo→vault bridge, read from ``docs/log.md`` text.

    Returns a dict:

    - ``lifetime`` — total ``bridge-candidate`` tags ever logged. Only grows; a stat, not a backlog.
    - ``pending`` — tags in sessions dated **strictly after** ``last_ingest_date``; ``None`` when
      no valid watermark is supplied, because the backlog is then genuinely unknown. Never a silent
      0 (coverage-honest: absence of a watermark ≠ empty queue).
    - ``last_ingest`` — the watermark echoed back (``None`` if absent/invalid).
    - ``newest_session`` — the newest session date seen (diagnostic; ``None`` if the log has none).
    """
    watermarked = _is_iso(last_ingest_date)
    lifetime = 0
    pending = 0
    newest: Optional[str] = None
    for date_str, block in _sessions(log_text):
        count = block.count(_TAG)
        lifetime += count
        if date_str and (newest is None or date_str > newest):
            newest = date_str
        # Undated preamble tags (date_str is None) are pre-history: counted lifetime, never pending.
        if count and watermarked and date_str and date_str > last_ingest_date:  # type: ignore[operator]
            pending += count
    return {
        "lifetime": lifetime,
        "pending": pending if watermarked else None,
        "last_ingest": last_ingest_date if watermarked else None,
        "newest_session": newest,
    }


def format_status(status: Dict[str, object]) -> str:
    """A one-line, honest summary for a brief. Nags to run ``/ingest`` only on a real, watermarked
    backlog — never on the cumulative lifetime count."""
    lifetime = status.get("lifetime", 0)
    pending = status.get("pending")
    if pending is None:
        return f"{lifetime} tagged bridge-candidate (lifetime; pending tracked at SessionStart)"
    if pending == 0:
        return f"bridge queue empty - 0 pending since /ingest {status.get('last_ingest')} ({lifetime} lifetime)"
    noun = "lesson" if pending == 1 else "lessons"
    return (
        f"bridge queue: {pending} {noun} pending since /ingest {status.get('last_ingest')} "
        f"({lifetime} lifetime) - run /ingest in a vault session"
    )


def main(argv=None) -> int:
    """CLI: ``python -m cisco_toolkit.bridge_queue [log_path] [--ingest YYYY-MM-DD]``.

    Prints the honest one-line status. Always exit 0 — this is a report, never a gate. Defaults to
    ``docs/log.md`` with no watermark (lifetime-only view)."""
    import os
    import sys

    argv = list(sys.argv[1:] if argv is None else argv)
    ingest: Optional[str] = None
    positional = []
    i = 0
    while i < len(argv):
        if argv[i] == "--ingest" and i + 1 < len(argv):
            ingest = argv[i + 1]
            i += 2
            continue
        positional.append(argv[i])
        i += 1
    path = positional[0] if positional else os.path.join("docs", "log.md")
    try:
        text = open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        print(f"log not found: {path}")
        return 0
    print(format_status(bridge_queue_status(text, ingest)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
