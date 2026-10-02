# W2d: immutable snapshot projection performance

Status: implementation and final validation in progress. This record does not claim
readiness, merge, release qualification or field acceptance.

## Source and scope

Base: `db9d8534cd93f62379d2cfda8fa37090b710c0e7`, the merge of #584 from
`61961ca371392c99f209c604456a99cc6e19b04e`. Their trees are identical. Work is on
`codex/ui-projection-performance` in the existing UI checkout. The merged W2c row
is removed under board rule 8. W2e, W6 and W7 remain ordered follow-ups; #582 belongs
to the separate Scope session.

The requested boundary is one computed and validated projection for immutable
stored bytes and engine/projection semantics, reused across views and pages.
Current store authority, exact digest form, deletion behavior, all owner fact
states, full-document validation before selection, and HTTP response validation
remain required. Schema-validator construction was already reused on the base;
repeated projection, full validation, transport validation and list copies were
the measured request costs.

## Reproducible measurement

`tests/perf_ui_projection.py` exercises actual ASGI HTTP responses, including store
reads, authority verification, projection, validation, paging and serialization.
It uses a temporary database, explicit loopback peer and unchanged committed
sample. The scale load is the existing synthetic `_big` fixture from
`tests/test_ui_projection_inventory.py`: 300 devices, 20,100 interfaces and 9,000
endpoints. It is load evidence, not a newly assessed or accepted network.

Run the benchmark with `--all-lists --repeats 5 --output <external receipt.json>`.
Use `--limit 200` to exercise the maximum page size and
`--require-sample-warm-ms 300` to make the sample target an explicit exit gate.
Receipts include individual timings, source hashes, runtime/dependency versions,
stored-byte identity, response sizes and response digests. Each endpoint's first
request is recorded separately; later view requests can already benefit from an
earlier view's snapshot cache. Repeated response bytes must match exactly.

Base measurement on Python 3.12.10 / Windows, 50-row limit, two repeated calls per
endpoint (preliminary baseline, not a percentile estimate):

| Endpoint | Warm median ms | Warm maximum ms |
|---|---:|---:|
| Overview | 2165.1 | 2417.9 |
| Trust | 2650.1 | 2866.2 |
| Inventory | 2777.5 | 2943.8 |
| Findings | 2513.8 | 2795.5 |
| Device | 456.1 | 528.8 |
| Inventory device list | 1871.4 | 2057.4 |
| Findings list | 2153.0 | 2400.8 |
| Device interface list | 295.8 | 351.4 |

The stored sample is 2,473,211 compact JSON bytes; its store digest is
`sha256:d7d887336b7d85f71d3ce95a7a32a8a912dc7e50b039dec86f51f567f039ffaf`.
Its source file and upload digest are different identities. The first benchmark
attempt received the expected 403 for a symbolic non-loopback ASGI client;
the harness was corrected to specify a numeric loopback peer. No application
guard was relaxed.

## Closing evidence still required

- Final sample and 300-device HTTP measurements, including all list selectors.
- Focused cache/custody/validator refutations and independent review.
- Appropriate backend, OpenAPI, distribution and portable checks.
- Repository privacy and complete new-commit message/patch scan before push.
- Every required hosted check green on the final PR head, followed by the
  authorized exact-head admin merge commit and tree reconciliation.

The canonical Graphify graph was used only for navigation. It belongs to the
protected main checkout, not this linked checkout; no graph refresh or claim of
current-tree graph coverage is made here.
