"""Vault-digest producer (vault-fenced, D3/D4, ADR-0001 Amendment 1) — read the personal vault ->
distill generic domain facts -> Rule-3 sanitize -> hash-seal -> emit ``docs/vault-digest/digest-*.jsonl``.

THE FENCE (ADR-0001 Amendment 1, point 4): the vault read happens **here**, in the network/vault-connected
research lane, **never from an air-gapped repo session**. The air-gapped repo only ever reads the frozen,
hash-sealed, sanitized digest (via :mod:`cisco_toolkit.recall` /
:func:`cisco_toolkit.intel_feed.verify_feed`).
This module lives **outside** ``cisco_toolkit/`` (the attestation fence) exactly like the intel-feed producer,
so its file I/O over the vault never counts against the engine's no-egress import graph.

What crosses is a **digest, not pages** (Amendment 1, point 1): per note we emit only a distilled entry —
a title + a length-**capped** summary + tags — never the full raw note, and we **drop** any page flagged
client-adjacent (defense-in-depth *before* the scrub). Everything is then scrubbed by
:func:`research_lane.sanitize.sanitize_advisories` (Rule-3) and hash-sealed by
:func:`cisco_toolkit.intel_feed.build_feed` (the one integrity contract the consumer verifies). The SHA-256
is unkeyed and declares ``authentication: none``: it detects corruption but does not authenticate who
produced the digest. The entry ``id`` is assigned **after** the scrub, from the sanitized title, so a client
token can never leak through the id.

Run it from a vault-connected worktree/host; ``python -m research_lane.vault_digest --vault <dir>``.
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Tuple

from research_lane.sanitize import sanitize_advisories

# Crude YAML frontmatter split (--- ... --- at the top of a note). We read flat ``key: value`` lines only.
_FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)
# Frontmatter keys / tag substrings that mark a note as client-adjacent -> DROP it whole (never digest it).
_CLIENT_FLAGS = ("client", "private", "confidential", "engagement", "customer")
# The SAME authored marker, written as an INLINE tag (``#client``, ``#engagement/site-a``) — which is
# where a note that carries no frontmatter puts it, and that is the common shape. Requires a word
# character straight after the ``#``, so a markdown heading (``# Title``: hash, then a space) is not a
# tag, and the leading lookbehind keeps ``##Sub`` from reading as one either.
_INLINE_TAG_RE = re.compile(r"(?<![\w#])#([A-Za-z][\w/-]*)")
_OUTPUT_LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_MAX_NOTE_BYTES = 2 * 1024 * 1024
_MAX_VAULT_BYTES = 64 * 1024 * 1024
_MAX_TITLE_CHARS = 200
_MAX_TAG_CHARS = 512


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-") or "entry"


def _is_within(root: str, candidate: str) -> bool:
    try:
        return os.path.normcase(os.path.commonpath([root, candidate])) == os.path.normcase(root)
    except ValueError:
        return False


def _parse_frontmatter(text: str) -> Tuple[Dict[str, str], str]:
    """Return ``(meta, body)``. ``meta`` is flat ``key: value`` frontmatter (lowercased keys); ``body`` is the
    remainder. No frontmatter -> ``({}, text)``. Intentionally tiny (no YAML dep, no nesting)."""
    m = _FM_RE.match(text or "")
    if not m:
        return {}, text or ""
    meta: Dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" in line and not line.lstrip().startswith("#"):
            k, _, v = line.partition(":")
            meta[k.strip().lower()] = v.strip().strip('"').strip("'")
    return meta, m.group(2)


def _first_paragraph(body: str, *, max_chars: int) -> str:
    """First non-heading paragraph of the body, capped at ``max_chars`` — this cap is what enforces
    'digest, not full page' (Amendment 1, point 1)."""
    for p in re.split(r"\n\s*\n", body or ""):
        p = p.strip()
        if p and not p.lstrip().startswith("#"):
            return p[:max_chars]
    first = (body or "").strip()
    return first[:max_chars]


def _bounded_text(value: Any, max_chars: int) -> str:
    """Collapse whitespace and cap a distilled metadata field after source selection."""
    return re.sub(r"\s+", " ", str(value or "")).strip()[:max_chars]


def _is_client_adjacent(meta: Dict[str, str], text: str = "") -> bool:
    """True if the note carries an explicit client-adjacent MARKER: a flag key set truthy or a client marker
    in ``tags``/``type``, the same marker written as an INLINE tag (``#client``) anywhere in the note, or a
    frontmatter block that OPENS and cannot be parsed.

    This reads only the frontmatter before, which is not where a note without frontmatter keeps its tags: one
    tagged ``#client #confidential`` in its body was digested and then hash-sealed with
    ``sanitized: true`` and zero redactions, so the client's name crossed the two-store boundary
    (ADR-0001) under an attestation.

    The scope is stated exactly, because the previous wording ("when in doubt about a note being generic, it is
    dropped") claimed more than the code does and the claim is the load-bearing part here. This drops on an
    authored MARKER, never on content: a note carrying no marker at all is NOT dropped, it goes on to the
    Rule-3 scrub, which is the real boundary. Deliberately not the filename or the prose either — this is a
    NETWORKING vault, where "client" and "private" are ordinary words (dhcp-client, private-vlan), and a gate
    that eats those teaches its operator to bypass it, which costs more than the gap it closes.

    Unparseable frontmatter IS dropped, and that one IS a when-in-doubt: a note that opens ``---`` and never
    closes it has markers the parser cannot see, so "no flags found" says nothing about whether there are any.
    """
    if (text or "").startswith("---") and not _FM_RE.match(text):
        return True
    blob = (str(meta.get("tags", "")) + " " + str(meta.get("type", "")) + " "
            + " ".join(_INLINE_TAG_RE.findall(text or ""))).lower()
    if any(f in blob for f in _CLIENT_FLAGS):
        return True
    # A client flag is authored by NAMING one at least as often as by asserting a boolean --
    # `client: acme-bank` is the most natural spelling of the marker, and it is MORE
    # client-adjacent than `client: true`, not less. Requiring the value to be literally
    # true/yes/1 inverted that: the boolean was dropped and the named client was published.
    # So: any client-flag key carrying a value drops the note, EXCEPT an explicit negation --
    # `client: false` is an author saying "not one", and honouring that keeps the gate from
    # eating notes its operator deliberately cleared (the same reason this never reads prose).
    return any(str(meta.get(f, "")).strip().lower() not in ("", "false", "no", "0", "none", "n/a")
               for f in _CLIENT_FLAGS)


def distill_note(path: str, text: str, *, max_chars: int = 600) -> Optional[Dict[str, Any]]:
    """Distill ONE vault note into a digest entry, or ``None`` if it must be dropped (client-adjacent, or no
    usable body). A digest entry is ``{title, detail, notes, source}`` — title + a **capped** summary + tags,
    never the full raw note. The ``id`` is deliberately NOT set here; it is assigned post-sanitize."""
    if max_chars <= 0 or max_chars > 10_000:
        raise ValueError("max_chars must be between 1 and 10,000")
    meta, body = _parse_frontmatter(text)
    if _is_client_adjacent(meta, text):
        return None
    title = meta.get("title") or ""
    if not title:
        m = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
        title = m.group(1).strip() if m else os.path.splitext(os.path.basename(path))[0]
    detail = _bounded_text(
        meta.get("summary") or _first_paragraph(body, max_chars=max_chars),
        max_chars,
    )
    if not detail.strip():
        return None
    return {
        "title": _bounded_text(title, _MAX_TITLE_CHARS),
        "detail": detail,
        "notes": _bounded_text(meta.get("tags", ""), _MAX_TAG_CHARS),
        "source": "vault-digest",
    }


def vault_source(vault_dir: str, *, subdir: str = "", max_chars: int = 600,
                 max_notes: Optional[int] = None) -> List[Dict[str, Any]]:
    """**Reads the vault** (markdown, recursively) and distills each note. RUNS IN THE FENCED LANE ONLY.
    Walks ``vault_dir/subdir`` for ``*.md``; returns distilled entries (client-adjacent notes dropped). The
    caller (the CLI) gates this behind an explicit ``--vault`` so it never reads a vault by default. Resolved
    paths must stay inside the selected vault; escaping links, unreadable/non-UTF-8 notes, per-note or
    aggregate byte overruns, and a ``max_notes`` overrun are refused rather than silently skipped or
    partially published."""
    if max_chars <= 0 or max_chars > 10_000:
        raise ValueError("max_chars must be between 1 and 10,000")
    if max_notes is not None and max_notes <= 0:
        raise ValueError("max_notes must be positive")
    vault_root = os.path.realpath(vault_dir)
    root = os.path.realpath(os.path.join(vault_root, subdir) if subdir else vault_root)
    if not os.path.isdir(vault_root) or not os.path.isdir(root):
        raise ValueError("vault path and selected subdirectory must both be directories")
    if not _is_within(vault_root, root):
        raise ValueError("vault subdirectory escapes the selected vault root")
    entries: List[Dict[str, Any]] = []
    bytes_read = 0
    for dirpath, dirs, files in os.walk(root):
        dirs.sort()
        for dirname in list(dirs):
            candidate = os.path.realpath(os.path.join(dirpath, dirname))
            if not _is_within(root, candidate):
                raise ValueError(f"vault directory link escapes the selected root: {dirname}")
        for fn in sorted(files):
            if not fn.lower().endswith(".md"):
                continue
            note_path = os.path.join(dirpath, fn)
            resolved_note = os.path.realpath(note_path)
            if not _is_within(root, resolved_note):
                raise ValueError(f"vault note link escapes the selected root: {fn}")
            note_bytes = os.path.getsize(resolved_note)
            if note_bytes > _MAX_NOTE_BYTES:
                raise ValueError(f"vault note exceeds the 2 MiB limit: {fn}")
            bytes_read += note_bytes
            if bytes_read > _MAX_VAULT_BYTES:
                raise ValueError("vault source exceeds the 64 MiB aggregate read limit")
            try:
                with open(resolved_note, encoding="utf-8") as handle:
                    text = handle.read()
            except (OSError, UnicodeError) as exc:
                raise ValueError(f"vault note is unreadable UTF-8: {fn}") from exc
            e = distill_note(fn, text, max_chars=max_chars)
            if e:
                entries.append(e)
            if max_notes is not None and len(entries) > max_notes:
                raise ValueError(
                    f"vault contains more than the explicit {max_notes}-note limit; "
                    "refusing a silently partial digest"
                )
    return entries


def produce_digest(entries: List[Dict[str, Any]], *, forbidden: Tuple[str, ...] = (),
                   generated: str = "", redact_ips: bool = True) -> Tuple[str, List[str]]:
    """Sanitize (Rule-3) -> assign leak-proof ids -> hash-seal. Returns ``(digest_text, redactions)``.
    ``sanitized: true`` is recorded only after the scrub runs here; the redaction list is audit detail, not
    independent proof or authentication.
    The id is slugged from the **sanitized** title (+ index for uniqueness) so it cannot carry a client token."""
    clean, redactions = sanitize_advisories(
        entries,
        forbidden=forbidden,
        redact_ips=redact_ips,
        require_ids=False,
    )
    for i, e in enumerate(clean):
        e["id"] = f"{_slug(str(e.get('title', '')))[:48]}-{i:03d}"
    from cisco_toolkit.intel_feed import build_feed          # one integrity contract, shared with the consumer
    feed = build_feed(clean, sanitized=True, producer="vault-digest", generated=generated)
    return feed, redactions


def run(entries: List[Dict[str, Any]], out_dir: str = os.path.join("docs", "vault-digest"), *,
        forbidden: Tuple[str, ...] = (), generated: str = "", redact_ips: bool = True,
        allow_empty: bool = False) -> Tuple[str, List[str]]:
    """Produce a hash-sealed digest from already-distilled entries and write it under ``out_dir``.
    Empty input is refused unless explicitly authorized, the generated label is filename-safe, and the
    complete envelope is verified before an atomic temp-write/fsync/replace publishes it. Returns
    ``(path, redactions)``."""
    if not entries and not allow_empty:
        raise ValueError(
            "refusing to publish an empty vault digest without allow_empty=True"
        )
    label = generated or "latest"
    if not _OUTPUT_LABEL.fullmatch(label) or label in (".", ".."):
        raise ValueError("generated label must be a safe 1-64 character filename token")
    feed, redactions = produce_digest(
        entries,
        forbidden=forbidden,
        generated=generated,
        redact_ips=redact_ips,
    )
    from cisco_toolkit.intel_feed import verify_feed
    verified = verify_feed(feed, forbidden=forbidden)
    if not verified["ok"]:
        raise ValueError(f"refusing to publish an invalid vault digest: {verified['reason']}")
    # ADR-0001: this repo NEVER writes the vault. `out_dir` came straight from `--out` with no
    # confinement, so `--vault <vault> --out <vault>/digest` wrote the digest INTO the store it had
    # just read. The existing shell guard cannot catch it — `vault_guard_bash._WRITE_TOKENS` is a
    # hand-maintained list of shell write VERBS (`cp`, `mv`, `tee`, …) and `--out` is not one of
    # them, so that command classifies as ALLOWED. A named subset standing in for "anything that
    # writes", with this module as the new instance it never anticipated.
    #
    # Only the label was traversal-checked above; the directory it lands in was not checked at all.
    # The confinement itself is enforced in `main`, where both --vault and --out are known.
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"digest-{label}.jsonl")
    import tempfile
    fd, temp_path = tempfile.mkstemp(prefix=".vault-digest-", suffix=".tmp", dir=out_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(feed)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, path)
    except BaseException:
        try:
            os.unlink(temp_path)
        except FileNotFoundError:
            pass
        raise
    return path, redactions


def main(argv: Optional[List[str]] = None) -> int:
    """CLI (run from a VAULT-CONNECTED session — this reads the vault):
      ``python -m research_lane.vault_digest --vault <C:\\Vaults\\brain> [--subdir wiki] [--generated DATE]
        [--forbidden Acme,SiteA] [--max-chars 600] [--out docs/vault-digest] [--dry-run]``
    Emits ``docs/vault-digest/digest-<date>.jsonl`` — a hash-sealed, sanitized DIGEST the air-gapped repo
    verifies and fuses into recall. **``--dry-run`` previews what would cross (sanitized titles + redaction counts)
    and writes NOTHING** — recommended for the first run of a real vault. Reading the vault requires an
    explicit ``--vault`` (no default): there is no silent vault read, mirroring how the intel producer gates
    live egress behind ``--live --url``."""
    import sys
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    def _opt(name: str, default: str = "") -> str:
        return argv[argv.index(name) + 1] if name in argv and argv.index(name) + 1 < len(argv) else default

    vault = _opt("--vault")
    if not vault:
        print("usage: python -m research_lane.vault_digest --vault <dir> [--subdir wiki] [--generated DATE] "
              "[--forbidden A,B] [--max-chars 600] [--dry-run]\n"
              "  --dry-run previews what would cross (writes nothing) — use it for a real vault's first run.\n"
              "  (reading the vault is explicit + fenced — run this from a vault-connected session, "
              "never an air-gapped repo session; ADR-0001 Amendment 1)")
        return 2
    # ADR-0001: this lane READS the vault and must never write it. `--out` was passed straight
    # through to `os.makedirs` + `mkstemp`, so `--vault <vault> --out <vault>/digest` published the
    # digest INTO the store it had just read. The shell guard cannot catch that:
    # `vault_guard_bash._WRITE_TOKENS` is a hand-maintained list of shell write VERBS (`cp`, `mv`,
    # `tee`, …) and `--out` is not one, so the command classifies as ALLOWED. Only the output LABEL
    # was ever traversal-checked; the directory was not checked at all.
    _out_probe = _opt("--out", os.path.join("docs", "vault-digest"))
    if _is_within(os.path.realpath(vault), os.path.realpath(_out_probe)):
        print("refusing to write the digest inside the vault (ADR-0001 two-store rule): --out must "
              "resolve OUTSIDE --vault. This lane reads the vault and never writes it.")
        return 2
    subdir = _opt("--subdir", "")
    generated = _opt("--generated", "")
    # .strip() per token — see research_lane.producer.main: `--forbidden Acme, SiteA` left the
    # second token as " SiteA", which matched nothing while the digest still claimed sanitized.
    forbidden = tuple(t for t in (s.strip() for s in _opt("--forbidden", "").split(",")) if t)
    try:
        max_chars = int(_opt("--max-chars", "600") or "600")
    except ValueError:
        print("[vault-digest] --max-chars must be an integer between 1 and 10,000")
        return 2
    out_dir = _opt("--out", os.path.join("docs", "vault-digest"))

    print(f"[vault-digest] READING VAULT (fenced): {vault}{('/' + subdir) if subdir else ''}")
    try:
        entries = vault_source(vault, subdir=subdir, max_chars=max_chars)
    except (OSError, ValueError) as exc:
        print(f"[vault-digest] intake refused: {exc}")
        return 3
    if not forbidden:
        print("[vault-digest] WARNING: no --forbidden tokens set - standard IP/MAC/email/serial patterns "
              "are scrubbed, but the air-gapped consumer will refuse this digest until an "
              "engagement-specific CISCO_ASSESS_FORBIDDEN denylist is configured. Pass "
              "--forbidden <client,site,device> now to scrub those names at the producer too.")
    if "--dry-run" in argv:
        # Sanitize + hash-seal IN MEMORY but write NOTHING — preview exactly what would cross (safe first run).
        feed, redactions = produce_digest(entries, forbidden=forbidden, generated=generated)
        from cisco_toolkit.intel_feed import verify_feed
        verified = verify_feed(feed, forbidden=forbidden)
        if not verified["ok"]:
            print(f"[vault-digest] dry-run envelope refused: {verified['reason']}")
            return 3
        preview = verified["entries"]
        print(f"[vault-digest] DRY-RUN — nothing written. Would emit {len(preview)} entry(ies), "
              f"{len(redactions)} redaction(s). Preview (sanitized titles):")
        for e in preview[:60]:
            print(f"    - {e.get('id')}: {str(e.get('title', ''))[:70]}  ({len(str(e.get('detail', '')))} ch)")
        return 0
    try:
        path, redactions = run(
            entries,
            out_dir=out_dir,
            forbidden=forbidden,
            generated=generated,
        )
    except (OSError, ValueError) as exc:
        print(f"[vault-digest] publish refused: {exc}")
        return 3
    print(f"[vault-digest] wrote {path} ({len(entries)} distilled entry(ies); {len(redactions)} redaction(s) "
          f"applied; digest not pages, capped at {max_chars} chars/entry)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
