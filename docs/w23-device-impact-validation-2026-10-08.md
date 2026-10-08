# W23 device failure impact and structural links

Started from main `a816bfca`. This record covers gaps G10 and G11. The device page now carries
the stored `failure_impact` row and the `link_centrality` rows that name the device. They are
selected by exact host, built by the fleet topology's own row builders, and never re-simulated.

An empty `failure_impact` selection is `not_collected`, never "no impact".
`compute_failure_impact` writes one row for each `build_network_model` host. An empty
`structural_links` selection is also `not_collected`, because the host-pair model keeps only
links whose two ends were both scanned. A duplicate impact row is `unverified`, and one row is
never picked over the other.

No local test, browser, SPA build, benchmark or frozen smoke was run; the owner's rule is
GitHub-hosted only.

## Native transport schema re-pin

The first hosted run of bootstrap `e0a545f5` reported 99 failures:
- CI job `113260469865`: Tests · py3.13 · ubuntu-latest;
- CI job `113260545113`: Backend e2e tests.

All 99 sit in the native-transport group of `webapp/tests/test_ui_projection_api.py`:
- the pin assertion;
- the prospective-pin parity matrix;
- the W12a/W13 native-parity tests, whose native validator was disabled by the hash mismatch;
- the request-local native smoke;
- the reaudited topology-list check.

Every other test passed, including the new `tests/test_ui_projection_device_impact.py`. The
frontend type-check and build job also passed, including the generated-type `api:check`.

### Reviewed structural delta of the transport schemas

The delta adds no keyword outside the established domain. It uses only `$ref`, `properties`,
`required`, `additionalProperties`, `minItems`, `maxItems` and `oneOf`:

1. `DevicePage` gains two required properties, `failure_impact` and `structural_links`. They
   are `$ref`s to the existing `TopologyImpactRowList` and `TopologyStructuralLinkRowList`
   definitions, which the topology views already validate.
2. The device limitations array grows from 15 to 17 fixed items (`minItems` = `maxItems`).
   The two added entries re-address the existing limitation IDs `topology_scanned_model` and
   `impact_scanned_scope` into the device document. No new limitation ID or text exists.
3. The list union gains the two device list paths for the new sections, in owner property
   order.

The provider version (`jsonschema-rs` 0.58.5), the private resolver guard, the admitted
instance domain (`_native_instance_allowed`) and the offline Python fallback are unchanged.

**One behavioural consequence:**
- `TopologyStructuralLinkRow.betweenness` is a JSON float, and the admitted native domain
  excludes floats.
- So a device view that carries structural-link rows is validated by the offline Python path,
  exactly as topology views already are.
- Correctness and public errors are unchanged; native acceleration does not apply to those
  device views.
- The opt-in 300 ms projection performance measurement remains the latency evidence.

### Hashes

The hashes are compact `ensure_ascii` JSON plus LF, in owner key order. Values are taken from
the hosted assertion output of the jobs above and were not computed locally:

- view: `ccce3f33ce10533fad39e9bf9b33ee677497b3cbbcc6ad78a3a5feb2d4adc866`
- list: `110640131dd9e789538b4ce43dcc02a75128e8bc25d94906e1829739ab440c11`

The W12b prospective-pin parity test carries the same pair. W24 (#617, the G43 vocabulary block)
moves the same pins. Whichever of the two merges second takes current main, and re-pins on top
of the combined schema with its own reviewed delta.

All required hosted checks on the exact final head remain mandatory, and so does independent
refutation by Codex.
