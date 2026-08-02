"""Research lane — the EGRESS-FENCED "eyes" producer (Phase 5, D2).

**This package lives OUTSIDE ``cisco_toolkit/`` on purpose.** The air-gapped analysis package and the
collector are attested no-egress (``cisco_toolkit/attestation.py`` + ``tests/test_readonly_and_no_egress.py``
scan only ``cisco_toolkit/``). The research lane is where external egress is *allowed* — it sweeps
PSIRT/advisory sources, **Rule-3-sanitizes** the result, **SHA-256 hash-seals** it, and emits a frozen
``docs/intel/feed-*.jsonl`` that the air-gapped repo consumes read-only via
:mod:`cisco_toolkit.intel_feed`. Only the frozen, sanitized, hash-sealed artifact crosses in — so the repo's
no-egress invariant stays byte-identical-reproducible when disconnected. The digest is unkeyed and declares
``authentication: none``: it detects corruption but does not authenticate a producer.

The dependency direction is one-way: ``research_lane`` imports ``cisco_toolkit`` (to reuse the feed's
integrity contract), never the reverse — so nothing here can pull an egress import into the attested package.
Live egress is isolated in :func:`research_lane.producer.http_source` and gated behind an explicit
``--live`` + ``--url``; the guarded fetch path accepts public HTTPS only, confines redirects, pins validated
DNS addresses, disables environment proxies, and enforces response/byte/deadline budgets. The default path
is an offline fixture (no network), mirroring the nightly wrapper's dry-run discipline.
"""
