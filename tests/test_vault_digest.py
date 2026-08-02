"""Vault-digest recall store (Phase 5, D3/D4, ADR-0001 Amendment 1).

Pins the safety-critical properties of the one-way, sanitized, read-only vault digest:
  * PRODUCER (research_lane/vault_digest.py, fenced lane): distils a DIGEST not raw pages (length-capped),
    DROPS client-adjacent notes, Rule-3-scrubs, and assigns a leak-proof id from the *sanitized* title.
  * CONSUMER (cisco_toolkit.recall): PROVENANCE-VERIFIES before use (reuses the intel-feed gate) — a tampered
    or unsanitized digest is refused whole; a verified digest fuses into RRF as a real 3rd store.
  * DEGRADATION: no digest -> empty corpus (never a fabricated hit); Ollama absent -> lexical-only.
"""
import pytest

import ollama_recall
from cisco_toolkit import recall as R
from cisco_toolkit.intel_feed import build_feed, verify_feed
from research_lane import vault_digest as VD


def _write_vault(root):
    """A synthetic vault (never the real one) — distillable notes + traps that must be handled."""
    (root / "bgp-rr.md").write_text(
        "---\ntitle: BGP Route Reflector Cluster-ID\ntags: bgp ibgp scale\n---\n"
        "# BGP RR\n\n" + ("A route reflector re-advertises iBGP routes so a full mesh is not required; the "
        "cluster-id groups redundant RRs to prevent loops. " * 8) + " Contact Acme NOC at 10.1.1.1.\n",
        encoding="utf-8")
    (root / "ospf.md").write_text("# OSPF LSA Types\n\nType-1 router LSAs flood within an area; "
                                  "type-3 summary LSAs cross area boundaries via the ABR.\n", encoding="utf-8")
    (root / "client-secret.md").write_text("---\ntitle: SiteA Cutover Runbook\ntags: client engagement\n---\n"
                                           "Raw client-adjacent note — must never be digested.\n", encoding="utf-8")
    (root / "empty.md").write_text("# Heading only\n", encoding="utf-8")
    # The client marker written where a note WITHOUT frontmatter can carry it: inline tags. This is
    # the common vault shape, and the frontmatter-only check digested it -- then hash-sealed the result
    # `sanitized: true`, so a client identifier crossed the ADR-0001 two-store boundary carrying an
    # attestation that it could not have.
    (root / "no-frontmatter-client.md").write_text(
        "# Northwind Bank core cutover\n\n#client #engagement/northwind\n\n"
        "Wave 2 moves the Northwind distribution pair; the cluster-id groups redundant RRs.\n",
        encoding="utf-8")
    # Frontmatter that OPENS but never closes: the parser sees no metadata, so any marker inside it
    # is invisible. Absence of a readable marker is not absence of a marker.
    (root / "broken-frontmatter.md").write_text(
        "---\ntitle: Northwind Site B\ntags: client engagement\n"
        "# Northwind Site B\n\nThe ABR summarises type-3 LSAs across the area boundary.\n",
        encoding="utf-8")


# --- producer: digest, not pages -------------------------------------------------------------------

def test_vault_source_distills_digest_drops_client_and_empty(tmp_path):
    _write_vault(tmp_path)
    entries = VD.vault_source(str(tmp_path))
    titles = {e["title"] for e in entries}
    assert "BGP Route Reflector Cluster-ID" in titles          # frontmatter title used
    assert "OSPF LSA Types" in titles                          # H1 fallback title
    assert not any("SiteA" in t or "Cutover" in t for t in titles)   # client-adjacent note DROPPED
    assert all(e["detail"].strip() for e in entries)           # heading-only note dropped (no body)
    # digest, not full page: every distilled detail is capped
    assert all(len(e["detail"]) <= 600 for e in entries)


def test_frontmatter_summary_and_tags_cannot_bypass_digest_caps():
    text = (
        "---\n"
        "title: " + ("Title " * 1000) + "\n"
        "summary: " + ("summary " * 200_000) + "\n"
        "tags: " + ("tag " * 200_000) + "\n"
        "---\nbody\n"
    )
    entry = VD.distill_note("large.md", text, max_chars=120)
    assert entry is not None
    assert len(entry["title"]) <= 200
    assert len(entry["detail"]) <= 120
    assert len(entry["notes"]) <= 512
    assert sum(len(str(value)) for value in entry.values()) <= 900


def test_a_client_marker_outside_frontmatter_still_drops_the_note(tmp_path):
    """The client gate read YAML frontmatter only, so a note without frontmatter — the common vault
    shape — was digested and then marked `sanitized: true`, carrying a client identifier across the
    ADR-0001 two-store boundary with an attestation it could not have earned. The marker is the same
    authored one (`#client`), written where such a note can carry it.

    Both traps here are marker-visibility, not content: a note that opens `---` and never closes it
    parses to no metadata, so any tag inside is invisible to the parser. Absence of a READABLE
    marker is not absence of a marker."""
    _write_vault(tmp_path)
    entries = VD.vault_source(str(tmp_path))
    titles = " | ".join(e["title"] for e in entries)
    details = " | ".join(e["detail"] for e in entries)
    assert "Northwind" not in titles and "Northwind" not in details, (
        f"a client-marked note crossed the two-store boundary: {titles}")
    # Calibration — the gate must drop on an authored MARKER, never on ordinary networking prose.
    # 'client' and 'private' are everyday words here (dhcp-client, private-vlan); a gate that ate
    # those would train its operator to bypass it.
    assert "OSPF LSA Types" in titles, "the unmarked, frontmatter-less note must still be digested"


def test_produce_digest_sanitizes_and_signs_with_leakproof_id(tmp_path):
    root = tmp_path / "v"; root.mkdir()
    (root / "acme.md").write_text("---\ntitle: Acme BGP Design Pattern\ntags: bgp\n---\n"
                                  "# x\n\nGeneric iBGP scaling note mentioning Acme and 10.9.9.9.\n",
                                  encoding="utf-8")
    entries = VD.vault_source(str(root))
    feed, redactions = VD.produce_digest(entries, forbidden=("Acme",), generated="2026-07-07")
    assert "Acme" in redactions and "10.9.9.9" in redactions   # proof-of-scrub recorded
    assert "Acme" not in feed and "10.9.9.9" not in feed       # scrubbed from the crossing artifact
    res = verify_feed(feed, forbidden=("Acme",))
    assert res["ok"] and res["entries"]                        # sanitized + hash-intact -> verifies
    assert all("acme" not in str(e["id"]).lower() for e in res["entries"])   # id derived post-scrub: no leak


def test_run_writes_a_verifiable_digest_and_tamper_is_refused(tmp_path):
    root = tmp_path / "v"; root.mkdir(); _write_vault(root)
    out = tmp_path / "vd"
    entries = VD.vault_source(str(root))
    path, _red = VD.run(entries, out_dir=str(out), generated="2026-07-07")
    assert verify_feed(open(path, encoding="utf-8").read())["ok"]
    # flip a byte in an entry line -> hash mismatch -> refused whole
    lines = open(path, encoding="utf-8").read().splitlines()
    lines[-1] = lines[-1].replace("area", "xrea", 1) if "area" in lines[-1] else lines[-1] + " "
    assert verify_feed("\n".join(lines))["ok"] is False


def test_vault_source_and_output_paths_fail_closed(tmp_path):
    root = tmp_path / "vault"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "note.md").write_text("# Outside\n\nmust not cross\n", encoding="utf-8")

    with pytest.raises(ValueError, match="escapes"):
        VD.vault_source(str(root), subdir="../outside")
    with pytest.raises(ValueError, match="empty vault digest"):
        VD.run([], out_dir=str(tmp_path / "out"), generated="2026-07-30")
    with pytest.raises(ValueError, match="filename token"):
        VD.run(
            [{"title": "safe", "detail": "safe", "source": "test"}],
            out_dir=str(tmp_path / "out"),
            generated="../../outside",
        )
    assert not (tmp_path / "out").exists()


# --- consumer: verify before use, then fuse --------------------------------------------------------

def test_load_vault_digest_verifies_and_builds_corpus(tmp_path):
    root = tmp_path / "v"; root.mkdir(); _write_vault(root)
    out = tmp_path / "vd"
    VD.run(VD.vault_source(str(root)), out_dir=str(out), generated="2026-07-07")
    corpus = R.load_vault_digest(str(out), forbidden=("Meridian Reference",))
    assert corpus and any("route reflector" in t.lower() for t in corpus.values())


def test_load_vault_digest_requires_an_engagement_denylist(tmp_path):
    out = tmp_path / "vd"
    out.mkdir()
    (out / "digest-x.jsonl").write_text(
        build_feed([{"id": "e1", "title": "generic", "detail": "safe"}]),
        encoding="utf-8",
    )
    status = {}
    assert R.load_vault_digest(str(out), status=status) == {}
    assert status["denylist_enforced"] is False
    assert status["refused"]
    assert "denylist is required" in status["refused"][0]["reason"]


def test_load_vault_digest_refuses_unsanitized_and_missing(tmp_path):
    out = tmp_path / "vd"; out.mkdir()
    # an UNSANITIZED feed (sanitized=False) must be refused -> contributes nothing
    (out / "digest-x.jsonl").write_text(
        build_feed([{"id": "e1", "title": "t", "detail": "d"}], sanitized=False), encoding="utf-8")
    assert R.load_vault_digest(str(out), forbidden=("Meridian",)) == {}
    assert R.load_vault_digest(
        str(tmp_path / "does-not-exist"),
        forbidden=("Meridian",),
    ) == {}    # absence is absence


def test_load_vault_digest_refuses_cross_file_duplicate_ids(tmp_path):
    out = tmp_path / "vd"
    out.mkdir()
    for label in ("a", "b"):
        (out / f"digest-{label}.jsonl").write_text(
            build_feed([{"id": "same", "title": label, "detail": "generic"}]),
            encoding="utf-8",
        )
    status = {}
    assert R.load_vault_digest(
        str(out),
        forbidden=("Meridian",),
        status=status,
    ) == {}
    assert len(status["refused"]) == 2
    assert all("duplicate entry id" in row["reason"] for row in status["refused"])


def test_load_vault_digest_enforces_file_size_bound(tmp_path, monkeypatch):
    out = tmp_path / "vd"
    out.mkdir()
    path = out / "digest-large.jsonl"
    path.write_text(
        build_feed([{"id": "e1", "title": "generic", "detail": "safe"}]),
        encoding="utf-8",
    )
    monkeypatch.setattr(R, "_MAX_VAULT_DIGEST_BYTES", 8)
    status = {}
    assert R.load_vault_digest(
        str(out),
        forbidden=("Meridian",),
        status=status,
    ) == {}
    assert "limit" in status["refused"][0]["reason"]


def test_vault_store_fuses_a_vault_only_hit(tmp_path):
    corpus = {"vd-anycast-000": "anycast rendezvous point pim sparse-mode redundancy",
              "vd-mtu-001": "jumbo mtu path discovery"}
    ranked = R.vault_digest_rank("anycast rendezvous point", corpus)
    fused = [x for x, _ in R.hybrid_recall("anycast rendezvous point",
                                           docs_corpus={"d.md": "unrelated"}, code_corpus={"c.py": "unrelated"},
                                           extra_lists=[ranked])]
    assert "vd-anycast-000" in fused                           # surfaced purely from the vault store


# --- Ollama: optional, gated, degrades -------------------------------------------------------------

def test_ollama_cosine_pure():
    assert ollama_recall.cosine([1.0, 0.0, 0.0], [1.0, 0.0, 0.0]) == 1.0
    assert ollama_recall.cosine([1.0, 0.0], [0.0, 1.0]) == 0.0
    assert ollama_recall.cosine([], [1.0]) == 0.0              # mismatched/empty -> 0, never fabricated


def test_ollama_probe_fastfails_and_empty_digest_degrade(tmp_path):
    # The degradation MECHANISM: an unreachable Ollama makes the TCP probe fast-fail, so recall falls back to
    # the lexical vault signal. Tested against a closed port, so it holds whether or not Ollama is installed
    # on the test machine (the suite must stay hermetic — never require a running Ollama).
    assert ollama_recall._listening("127.0.0.1:1", timeout=0.3) is False
    # And an empty digest dir yields nothing to rank -> [] / exit 0, independent of Ollama being up.
    assert R.ollama_digest_rank("anything", digest_dir=str(tmp_path)) == []
    assert ollama_recall.main(["query", str(tmp_path)]) == 0   # fast, silent, non-raising


def test_producer_dry_run_previews_and_writes_nothing(tmp_path, capsys):
    root = tmp_path / "v"; root.mkdir(); _write_vault(root)
    out = tmp_path / "vd"
    rc = VD.main(["--vault", str(root), "--dry-run", "--out", str(out)])
    assert rc == 0
    printed = capsys.readouterr().out
    assert "DRY-RUN" in printed and "nothing written" in printed
    assert "WARNING: no --forbidden" in printed                # no scrub tokens -> safety warning surfaced
    assert (not out.exists()) or not list(out.glob("digest-*.jsonl"))   # preview writes nothing


def test_producer_cli_reports_invalid_inputs_without_traceback(tmp_path, capsys):
    assert VD.main(["--vault", str(tmp_path), "--max-chars", "not-an-int"]) == 2
    assert "--max-chars must be an integer" in capsys.readouterr().out

    missing = tmp_path / "missing-vault"
    assert VD.main(["--vault", str(missing)]) == 3
    assert "intake refused" in capsys.readouterr().out


def test_a_NAMED_client_in_frontmatter_drops_the_note_not_only_the_boolean_spelling():
    """The drop gate honoured `client: true` but published `client: acme-bank`.

    `_is_client_adjacent`'s last clause required the frontmatter VALUE to be literally
    true/yes/1. But a client flag is authored by NAMING one at least as often as by asserting a
    boolean, and `client: acme-bank` is MORE client-adjacent than `client: true`, not less. The
    gate was therefore inverted exactly where it mattered: the note that named the client was the
    one that crossed the two-store boundary (ADR-0001) and got hash-sealed as sanitized.

    The tag/type/inline-tag blob above it does not cover this: it reads `tags` and `type`, not an
    arbitrary `client:` key's value.
    """
    from research_lane.vault_digest import _is_client_adjacent, _parse_frontmatter

    def dropped(text):
        meta, _ = _parse_frontmatter(text)
        return _is_client_adjacent(meta, text)

    for flag in ("client", "customer", "engagement", "private", "confidential"):
        text = f"---\n{flag}: Acme Bank PLC\ntitle: T\n---\nbody\n"
        assert dropped(text), f"a note naming a client under `{flag}:` was NOT dropped"

    # the boolean spellings must keep working -- this fix must not trade one gap for another
    assert dropped("---\nclient: true\ntitle: T\n---\nbody\n")
    assert dropped("---\nclient: yes\ntitle: T\n---\nbody\n")


def test_the_drop_gate_still_honours_an_explicit_negation_and_stays_off_unmarked_notes():
    """Non-vacuity, both directions. If every note dropped, the gate would be trivially 'safe' and
    the lane would be useless -- and this vault is a NETWORKING vault where 'client' and 'private'
    are ordinary words, so a gate that eats generic notes teaches its operator to bypass it."""
    from research_lane.vault_digest import _is_client_adjacent, _parse_frontmatter

    def dropped(text):
        meta, _ = _parse_frontmatter(text)
        return _is_client_adjacent(meta, text)

    assert not dropped("---\nclient: false\ntitle: T\n---\nbody\n"), "an explicit negation was dropped"
    assert not dropped("---\nclient: no\ntitle: T\n---\nbody\n")
    assert not dropped("---\nclient:\ntitle: T\n---\nbody\n"), "an empty value was dropped"
    assert not dropped("---\ntitle: T\n---\nordinary body\n"), "an unmarked note was dropped"
    assert not dropped("---\ntitle: DHCP client and private VLAN notes\n---\nbody\n"), \
        "the gate read PROSE -- it must drop on an authored marker only"
