"""Vault-digest recall store (Phase 5, D3/D4, ADR-0001 Amendment 1).

Pins the safety-critical properties of the one-way, sanitized, read-only vault digest:
  * PRODUCER (research_lane/vault_digest.py, fenced lane): distils a DIGEST not raw pages (length-capped),
    DROPS client-adjacent notes, Rule-3-scrubs, and assigns a leak-proof id from the *sanitized* title.
  * CONSUMER (cisco_toolkit.recall): PROVENANCE-VERIFIES before use (reuses the intel-feed gate) — a tampered
    or unsanitized digest is refused whole; a verified digest fuses into RRF as a real 3rd store.
  * DEGRADATION: no digest -> empty corpus (never a fabricated hit); Ollama absent -> lexical-only.
"""
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


# --- consumer: verify before use, then fuse --------------------------------------------------------

def test_load_vault_digest_verifies_and_builds_corpus(tmp_path):
    root = tmp_path / "v"; root.mkdir(); _write_vault(root)
    out = tmp_path / "vd"
    VD.run(VD.vault_source(str(root)), out_dir=str(out), generated="2026-07-07")
    corpus = R.load_vault_digest(str(out))
    assert corpus and any("route reflector" in t.lower() for t in corpus.values())


def test_load_vault_digest_refuses_unsanitized_and_missing(tmp_path):
    out = tmp_path / "vd"; out.mkdir()
    # an UNSANITIZED feed (sanitized=False) must be refused -> contributes nothing
    (out / "digest-x.jsonl").write_text(
        build_feed([{"id": "e1", "title": "t", "detail": "d"}], sanitized=False), encoding="utf-8")
    assert R.load_vault_digest(str(out)) == {}
    assert R.load_vault_digest(str(tmp_path / "does-not-exist")) == {}    # absence is absence


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
