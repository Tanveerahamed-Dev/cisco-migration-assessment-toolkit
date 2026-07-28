# Whole-repo code review — 2026-07-28

Register of every finding from the repo-wide review sweep (307 Python files, ~111k lines,
27 reviewer agents partitioned by subsystem). **All 98 are closed.** Tranche 1 in `1f0e652`,
then `5b8711a`, `2139bab`, `e67fa81`, `62f3dd8`, with the golden re-blessed in `66e2bad`.
Full suite green (exit 0, 6m53s).

## How to read this

- **Status** — `FIXED` (landed), `PARTLY REFUTED` (the mechanism was real but part of the reported
  claim was wrong; see the note on that row), `OPEN` (none remain).
- **Confidence** — `verified` = reproduced by running the code; `reported` = a reviewer agent's
  claim, quoted with file:line but not independently reproduced at register time. Everything marked
  `reported` was subsequently refuted-first by the agent that fixed it, and each fix was proven by a
  reverse patch: the new test was observed RED without it.
- Severity tiers reflect blast radius under this repo's doctrine (CLAUDE.md): a fail-OPEN gate or a
  fabricated-evidence claim outranks a crash, because a crash is visible and a false clean bill is not.

The dominant defect class, by a wide margin, is **absence rendered as health** — a missing
capture, an unparsed field, or an unreachable device presented as an observed "ok". That is the one
thing this codebase's doctrine says must never happen, and it recurred in every subsystem. Two rows
invert it (#38, #39): absence rendered as observed-BROKEN, which is the same error with the sign
flipped and is equally a fabrication.

## What this review does NOT claim

Each reviewer partition surfaced up to 8 candidates. For a 6,570-line file like `analyze.py` that is
a **sample**, not an exhaustive audit. Every subsystem was reviewed and every surfaced finding is
closed; the repo is not thereby proven defect-free. The five largest files
(`analyze.py`, `design_advisor.py`, `parse.py`, `excel.py`, `design_kb.py`) would repay a second,
deeper pass.

Two findings were partly refuted on inspection and are recorded as such rather than quietly dropped:
**#55** (the `total_ports` half was wrong — `model.DevicePhysical` declares it `int = 0` with no None
state, so 0 there IS the not-observed marker) and **#56** (`FASTMCP_*` env vars cannot in fact widen
the bind, because the module passes host as an init kwarg and pydantic-settings ranks init above env;
the unauthenticated-listener half was real). One further correction belongs here: the trigger cited
for the tranche-1 `os.path.exists` finding was wrong on Windows — `nt._path_exists` falls back to
`GetFileAttributes`, so the documented EACCES race never reaches the probe. The consequence was
reproduced and the fix stands, but it earns its keep on POSIX and on persistent stat failures, not on
the Windows race originally named.

---

## Tier 1 — evidence integrity and share-safety (client harm)

| # | Where | Status | Conf. | Defect |
|---|---|---|---|---|
| 1 | `webapp/backend/ingest.py:939` | FIXED | reported | `--redact-collection` is reported from the **flag**, not the outcome. `redact_collection_dir` skips unreadable/locked captures and continues; the phase is not a `_run_phase`, leaves no ledger row, is absent from `_REDACTION_PHASES`, and its warning does not match `_ENGINE_GAP_RE`. Exit 0 tells the engineer secrets were scrubbed off the stick. The only test asserts `report["redacted_collection"] is True` after passing `redact_collection=True` — it pins the echo of its own input. |
| 2 | `webapp/backend/ingest.py:697` | FIXED | reported | Both redaction certifications accept a **pre-existing** `.phase_timings.json` / `.snapshot.json` as this run's proof (`is_file()`), so under `--reuse-out` an earlier run's ok:true ledger certifies a run whose redaction phase failed soft. `pre_existing` / `_written_by_this_run` already exist and are not used here. |
| 3 | `webapp/backend/ingest.py:887` | FIXED | reported | The three failure exits that leave half a deliverable set on disk (timeout, non-zero engine exit, no snapshot) do **not** write `UNSAFE_MARKER`. Files named `*_redacted*` remain with nothing on disk saying they may be unredacted. |
| 4 | `webapp/backend/ingest.py:392` | FIXED | reported | The `--out` reuse refusal checks only `cli_artifacts(stem)` (the 10 documents), not `.snapshot.json` / `.run_manifest.json` / `.phase_timings.json`. Another job's snapshot travels inside a delivery, unlisted — and redaction keeps hostnames. |
| 5 | `webapp/backend/ingest.py:98` | FIXED | reported | `_safe_extract` validates traversal but not Windows **reserved device names**: `core1/NUL` resolves inside `dest`, passes the prefix guard, and `open()` writes to the null device. `COM1`-`COM9` writes archive bytes out a serial port. Returns `len(infos)` as "files written" without verifying any landed. |
| 6 | `webapp/backend/ingest.py:996` | FIXED | reported | The WEBAP-01 log-tail scrub strips only the workdir, but `run_collection_folder` passes the caller's absolute path as `--collection-dir`, so engine breadcrumbs disclose the server layout and engagement folder name. `_engine_gap_lines` already scrubs three roots; this sibling scrubs one. |
| 7 | `portable/make_stick.ps1:41` | FIXED | reported | The `/XD` pin protecting the stick's `data\` is the **destination** absolute path, so it cannot match a source `dist\Atlas\data\`. If the bundle was ever launched in place, `/MIR` mirrors the dev box's store over the field evidence. |
| 8 | `research_lane/vault_digest.py:64` | FIXED | reported | `_is_client_adjacent` inspects only YAML frontmatter, so a note **without** frontmatter (the common shape) is digested and then signed `sanitized: true` — a false attestation crossing the two-store boundary (ADR-0001). |

## Tier 2 — fail-open gates and false-clean verdicts

| # | Where | Status | Conf. | Defect |
|---|---|---|---|---|
| 9 | `COLLECT_PARSE_V3_23_0.py:658` | FIXED | **verified** | **17 non-`show` strings** sit in the live SSH command registries (`dataservice/device*`, `moquery -c *`, `api/fmc_config/*`, `ers/config/node`) and `collect()` sends the union of `COMMANDS_NXOS + COMMANDS_IOS` to every device. At an IOS exec prompt with `ip domain-lookup` on, an unknown word triggers a DNS lookup and a Telnet attempt **from production gear**. `tests/test_readonly_and_no_egress.py` states as doctrine "the only non-`show` strings on the SSH wire are the two terminal setup commands" — and passes. |
| 10 | `COLLECT_PARSE_V3_23_0.py:963` | FIXED | reported | When both transports fail, `send_cmd` returns `""`, which `collect()` writes as a normal capture with `paths[cmd]` set. `cmdio.cmd_capture_state` then ranks it `empty` **above** `error`, so a device whose SSH session died reads as one that positively reported nothing. |
| 11 | `COLLECT_PARSE_V3_23_0.py:918` | FIXED | reported | `terminal length 0` / `terminal width 511` failures are swallowed by a bare `except Exception: pass` with no log and no record. Under command authorization that denies `terminal *`, every capture is pager-truncated or 80-col wrapped, and the fixed-column parsers return plausible-but-wrong values. |
| 12 | `cisco_toolkit/analyze.py:1975` | FIXED | reported | Migration-readiness checks 5 (STP consistency) and 6 (port-channels) emit an affirmative `pass` with "no inconsistent ports" / "all members bundled" when the evidence was never collected. The adjacent routing check (line 1981) carries a `routing_collected` coverage set for exactly this reason; these two do not. |
| 13 | `cisco_toolkit/analyze.py:1147` | FIXED | reported | `compute_failure_impact` renders "no trunk/STP evidence collected" as **"No reachability impact"** for a transit switch, because `_link_carries` returns the same empty string for "positively not carried" and "no evidence at all". |
| 14 | `cisco_toolkit/analyze.py:2547` | FIXED | reported | `_physical_uplink_index` derives single-homed uplinks only from `model["links"]`, which keeps links whose **both** ends are scanned — so an access switch homed to an uncollected core is never flagged and readiness reports "no single-homed switch". The most common real topology is the one that reads clean. |
| 15 | `cisco_toolkit/analyze.py:1766` | FIXED | reported | `dq = data_quality.get(h, 1.0)` publishes a fabricated `data_quality: 1.0` for a host never measured, and the Insufficient-Data band cannot fire. |
| 16 | `cisco_toolkit/analyze.py:6399` | FIXED | reported | The device-dossier `scanned` guard is inert for a host banded Insufficient Data: it still has a health row, so Physical and Protocol render "ok — no L1 findings" beside "Health: na — collection gap". |
| 17 | `cisco_toolkit/analyze.py:3571` | FIXED | reported | `compute_trunk_capture_gaps` wraps each host in a bare `except Exception: continue`, dropping it from the coverage-gap list — the exact absence-reads-as-clean the function exists to prevent. |
| 18 | `cisco_toolkit/excel.py:3990` | FIXED | reported | Physical Health stamps `ok` for every port whose `show interfaces` was never collected (not an essential command, exact-match lookup). Contradicts this file's own line 1287: "Nothing renders as 'ok'/'healthy' — absence of evidence is never health". Same at `:4211` for `show track`. |
| 19 | `cisco_toolkit/archreview.py:422` | FIXED | reported | Check L2-2 grades **CONFORMS** once guarded ports exceed half of *all* access ports, using a different denominator from its not-assessable gate, then asserts "the edge is protected". Siblings HIER-2 and L2-3 carry conforms-by-silence guards; this one does not. |
| 20 | `cisco_toolkit/archreview.py:327` | FIXED | reported | RES-3 (redundant PSUs) is not-assessable only when **no** device in the fleet reports a PSU count, so one device reporting 2 grades the whole fleet CONFORMS. |
| 21 | `cisco_toolkit/capture_integrity.py:167` | FIXED | reported | A capture that exists but cannot be read is skipped by the integrity guard (`continue`) **and** counted complete by collection-completeness (which tiers on file presence) — it falls between both guards and reads as fully covered. |
| 22 | `webapp/backend/execution.py:221` | FIXED | reported | `_derive_outcome` falls through to `OUTCOME_SUCCESS` on a run with **zero waves**, because both `any()` guards are vacuously False. The PIR then renders "Outcome: SUCCESSFUL" over "0 of 0 wave(s) completed". |
| 23 | `webapp/backend/nrfu_docx.py:194` | FIXED | reported | The NRFU/ATP design-decision coverage table prints "Tested — …" unconditionally, defaulting the phase when no `design_nrfu` item exists. Filed previously as EX-nrfu-004 with a proposed fix that was never applied. |
| 24 | `cisco_toolkit/html.py:604` | FIXED | reported | `_trend_point` defaults four migration metrics to hard `0` when their snapshot sections are absent, so a partial upload reads "IMPROVING" with an empty verdict note. `avg_health`/`past_ldos` in the same dict correctly abstain — the idiom was known and applied to 2 of 6. |

## Tier 3 — wrong answers an engineer acts on

| # | Where | Status | Conf. | Defect |
|---|---|---|---|---|
| 25 | `cisco_toolkit/parse.py:138` | FIXED | reported | The IOS route-code regex requires a **single** uppercase token, so every two-token code (`O IA`, `O E2`, `D EX`, `i L1`) fails to match: the route is dropped from the RIB **and** its next-hop is grafted onto the previous prefix as a phantom ECMP sibling. Every OSPF inter-area/external, EIGRP external and IS-IS route silently absent. |
| 26 | `cisco_toolkit/upgrade_targets.py:205` | FIXED | reported | An unparseable entry in a CVE's `fixed` list is silently discarded when another fix parses, defeating the `>=2 same-train fixes -> MANUAL-VERIFY` guard and shipping a remediation MOP whose target release is **still vulnerable**. |
| 27 | `cisco_toolkit/fib.py:450` | FIXED | reported | ECMP is a pure existential ("any leg reaches"), so a destination with one blackholing leg certifies `computed:reached`; `reachability_diff` calls that cutover "preserved" and `ecmp_consistency` compares only MTU/ACL names. 50% loss reads clean on all three surfaces. |
| 28 | `cisco_toolkit/fib.py:426` | FIXED | reported | `_explore` turns an empty FIB lookup into the **definitive** `computed:unreachable`, but `snap['routes']` is scoped (`scope_routes` keeps only in-scope prefixes + default), so a scoping artifact is reported as a device forwarding decision. Both-absent then reads `both_unreachable` = non-regression. |
| 29 | `cisco_toolkit/aclcheck.py:34` | FIXED | reported | Protocol tokens compared as raw strings, so numeric IP-protocol forms (`6`/`17`/`1`) never intersect their names (`tcp`/`udp`/`icmp`). Two ACEs covering the same protocol model as disjoint, defeating first-match shadowing in the **unsafe** direction. |
| 30 | `cisco_toolkit/aclcheck.py:276` | FIXED | reported | `_rule_box` downgrades any rule with `unevaluable` set — and `parse.py:2843` sets that on **every** object-group address spec, including ones that resolve. The whole object-group resolution path is dead code on real configs, and the surfaced reason misattributes the cause. |
| 31 | `cisco_toolkit/aclcheck.py:455` | FIXED | reported | `search_filters` never models the implicit `deny ip any any`, so an ACL with no explicit deny is "proven" (`PROVEN_NONE`) to deny nothing. |
| 32 | `cisco_toolkit/fib.py:283` | FIXED | reported | `mtu_verdict` is computed from the **spread** of observed MTUs and ignores `required_mtu`, so a path where every hop is below the requirement (the normal shape of a 1500-byte underlay dropping VXLAN) reports `uniform`. |
| 33 | `cisco_toolkit/parse.py:2773` | FIXED | reported | The BPDU-guard branch has no `no `-prefix guard, so `no spanning-tree bpduguard enable` parses as **Enable**. The compensating `low.endswith("no")` is dead code. Its immediate sibling (rootguard) has the guard. |
| 34 | `cisco_toolkit/parse.py:4132` | FIXED | reported | `parse_show_interface_counters` captures only the link word and discards `line protocol is down`, so up/line-protocol-down records as `oper='up'` — and on routers there is no `show interface status` to override it. |
| 35 | `cisco_toolkit/parse.py:4210` | FIXED | reported | `parse_auth_sessions` alternation puts `Authz?` first, so "Authz Success" and "Authz Failed" both collapse to `Authz`. No other field carries the distinction. |
| 36 | `cisco_toolkit/parse.py:4070` | FIXED | reported | `parse_show_environment`: the PS-status branch treats `bad` as FAIL, the PS-FAN branch one line below omits it; unknown status words are dropped entirely, after which `_worst()` reports the surviving healthy PSU's OK as the chassis verdict. |
| 37 | `cisco_toolkit/parse.py:1436` | FIXED | reported | `_ise_rows` treats any single-key dict as a wrapped node, so an ISE **ERROR envelope** becomes a phantom deployment node, `build_ise` skips its fallback, and all three ISE detectors go silent. The FMC front door guards this exact shape. |
| 38 | `cisco_toolkit/design_advisor.py:1324` | FIXED | reported | The BPDU-Guard arm fires on an **absent** field: `stp_bpduguard` comes only from run-config-interface, while the gating fields come from MAC/CDP, so a collection without run-config reports every endpoint port as unguarded. `archreview` abstains correctly here; this does not. |
| 39 | `cisco_toolkit/design_advisor.py:1020` | FIXED | reported | `single_vrf = len(vrfs) <= 1` asserts a flat single-VRF estate from the **absence** of a `segmentation` block, driving a High decision whose own citation points at a path that does not exist on that snapshot. |
| 40 | `cisco_toolkit/design_advisor.py:3848` | FIXED | reported | `_vlan_host_counts` matches `== "Access"` exact/case-sensitive, so an uploaded snapshot with `"static access"` sizes every VLAN at 0 hosts and the LLD allocates a /24 to a VLAN carrying 300 endpoints. `textutils.is_trunk_mode` exists precisely to end this divergence. |
| 41 | `cisco_toolkit/design_advisor.py:3437` | FIXED | reported | The trade-off scorecard's coverage guard keys on `sig["not_collected"]`, which is 0 both when everything was collected and when the census is **missing**, so a snapshot with no completeness block certifies availability "Strong" from zero collected devices. |
| 42 | `cisco_toolkit/design_advisor.py:851` | FIXED | reported | An unsynchronised device with an unparsed stratum renders the literal `stratum 16` as observed evidence. |
| 43 | `cisco_toolkit/design_advisor.py:2592` | FIXED | reported | The DHCPv6-Guard clause claims a subset relation it does not compute (two independently accumulated sets), producing "1 switch … 2 of them" and naming the wrong device. |
| 44 | `cisco_toolkit/ops.py:58` | FIXED | reported | `str(r.get("fhrp","none")) or "none"` applies `str()` **before** the fallback, so a null `fhrp` becomes `"None"` and counts as FHRP-protected. `crd.py` and `design.py` both get this right; `ops.py` is the outlier. |
| 45 | `cisco_toolkit/build.py:554` | FIXED | reported | `build_ipv6_fhs` credits **global** policy-definition lines to whatever interface was seen last (`cur_if` never cleared), so a box that defines but never attaches RA-Guard/DHCPv6-Guard reports first-hop security present. |
| 46 | `cisco_toolkit/build.py:1036` | FIXED | reported | `detect_cross_device_dual_connections` keys on `(hostname, port)` without checking the devices **differ**, and step 7 manufactures the duplicate by copying MACs between a port-channel and its members — so a single-homed endpoint reads dual-homed, hiding a SPOF. |
| 47 | `cisco_toolkit/runbook.py:390` | FIXED | reported | §6.1 counts `fhrp == "none"` and labels it "single-gateway exposure", conflating no-FHRP with single-gateway (the producer distinguishes them), giving the war room an ~8x-divergent count from the design doc. |
| 48 | `cisco_toolkit/design.py:282` | FIXED | reported | §1 "Devices in scope" uses the canonical inventoried count while every enumeration (§3.1 inventory, §3.4 BoM, §3.5 software plan) iterates `snap['devices']` = collected only. The BoM under-orders by the gap with no reconciliation note. |
| 49 | `cisco_toolkit/mop.py:284` | FIXED | reported | The BLUF "open blockers" count uses readiness FAIL checks while §x.2 and §1's table use remediation+punchlist — two numbers under one label, and the BLUF cross-references the section that contradicts it. |
| 50 | `cisco_toolkit/design_advisor.py:3769` | FIXED | reported | `Past-EoS` is counted two contradictory ways in one blueprint: `refresh_soon` in the BoM and simultaneously "supportable asset to carry forward" in the narrative. |
| 51 | `cisco_toolkit/analyze.py:2705` | FIXED | reported | CL-04 pairs the fleet-wide set of tracked-down hosts against **every** FHRP VLAN without joining on VLAN, multiplying one device fault into N High findings and saturating the XL cap. |
| 52 | `cisco_toolkit/analyze.py:2212` | FIXED | reported | `_extract_protocol_states` matches EtherChannel flags with `\(([sDIwH])\)` — omits `M` and `f` and cannot match a combined token — so the states `compute_protocol_health` rates High produce no advisory. |
| 53 | `cisco_toolkit/html.py:293` | FIXED | reported | The diff workbook's Summary prints `len(devices)` while the delta returned by the same function prints canonical `n_devices` — one call, two fleet sizes, at the cutover gate. |
| 54 | `webapp/backend/cutover.py:352` | FIXED | reported | `_int(mg.get("endpoints")) or hard_ep` — `or`-masks-zero on an SSOT headline count, mis-ranking the pilot-first wave order. `storage.add_snapshot:266` documents guarding this exact class. |
| 55 | `cisco_toolkit/excel.py:693` | PARTLY REFUTED | reported | `compute_capacity` collapses an **observed** zero active ports to `""` (the unknown marker) while still emitting 0.0% utilisation and free=total — two contradictory coverage claims in one row. |

## Tier 4 — security surfaces

| # | Where | Status | Conf. | Defect |
|---|---|---|---|---|
| 56 | `cisco_toolkit/mcp_server.py:462` | PARTLY REFUTED | reported | `--transport sse` / `streamable-http` start an **unauthenticated HTTP listener** serving the whole snapshot, while the module docstring and `--help` both claim "offline, no egress". Host/port not pinned; FastMCP reads `FASTMCP_*` from the environment. |
| 57 | `cisco_toolkit/rest_collect.py:470` | FIXED | reported | `--password` is a required argv parameter with no env/getpass alternative, so a production APIC/vManage credential is typed on the command line (process table, shell history, EDR telemetry). The SSH path already solved this. |
| 58 | `webapp/backend/app.py:154` | FIXED | reported | `_client_is_loopback` fails **open** when `request.client is None` (UDS bind, some ASGI adapters/proxies), and ships a hardcoded `host == "testclient"` bypass in production code. |
| 59 | `webapp/backend/app.py:601` | FIXED | reported | `GET /api/snapshots/{id}` is a **state-changing** GET (`_summary_freshened` -> `store.update_summary`) with no `_forbid_cross_site`, and the CSRF guard returns False for GET by construction. The test pinning it as "must not be guarded" only holds because its fixture writes a current-schema summary first. |
| 60 | `webapp/backend/app.py:553` | FIXED | reported | The generation cap covers three **named** routes; `/ingest` and `/ingest-folder` — which fork the engine for up to 600s and buffer 256MB in memory — take no slot. Guarded by route list rather than by the property that made them worth guarding. |
| 61 | `webapp/backend/app.py:99` | FIXED | reported | `GateIn` carries `max_length` caps with a comment naming the vector; **every** sibling write model (`EventIn.text`, `StepIn.note`, `CheckIn.observed`, `CloseoutIn.note`, `FinishIn.note`, `ExecutionIn.*`, `CampaignIn.*`, `FolderIngestIn.label`, both Form labels) has none, and there is no global body-size limit. |
| 62 | `webapp/backend/app.py:272` | FIXED | reported | `_send_file`'s temp cleanup runs only in a `BackgroundTask` after the body is sent, so a cancelled download leaves a fully-rendered **unredacted** client deliverable in `%TEMP%` permanently. |
| 63 | `cisco_toolkit/excel.py:57` | FIXED | reported | The formula-injection neutraliser tests only `startswith("=")`; a leading tab/CR (which `xml_safe` deliberately preserves) slips the same payload through, and `+`/`-`/`@` are unhandled by design. Live on the CSV re-export path. Also: the guard lives only in `harden_workbook()`, which no writer calls or asserts. |
| 64 | `cisco_toolkit/excel.py:1047` | FIXED | reported | `write_topology_diagram` interpolates raw device-advertised CDP/LLDP names into quoted Mermaid and Graphviz labels with no escaping and no `xml_safe` (plain `open()/write()`), so a quote or newline injects statements into both shipped files. |
| 65 | `cisco_toolkit/nrfu_export.py:329` | FIXED | reported | `_safe_name` preserves `.`, so `_safe_name("..") == ".."` and a crafted `wave_id` writes the command pack one directory **above** `--out`. |
| 66 | `cisco_toolkit/rest_collect.py:294` | FIXED | reported | `collect_ise`'s ERS pagination has no visited-set or page cap (`while nxt:`), so a self-referential `nextPage.href` is an unbounded authenticated GET loop against a production ISE PAN. Its FMC sibling guards exactly this. |
| 67 | `cisco_toolkit/retrieval_eval.py:519` | FIXED | reported | The judge payload (corpus excerpts incl. vault-digest text) is written to a fixed, **non-gitignored** path under `docs/quality/`, removed only in a `finally` inside a 6-hour timeout window. |

## Tier 5 — self-verification instruments that certify without checking

| # | Where | Status | Conf. | Defect |
|---|---|---|---|---|
| 68 | `cisco_toolkit/attestation.py:87` | FIXED | reported | The no-egress / no-LLM attestation walks only the **top level** (`os.listdir`, not `os.walk`) yet publishes "0 network-library imports across N analysis modules". `cisco_toolkit/data/gen_port_registry.py` imports `urllib.request` and fetches iana.org — which is why `NO_EGRESS_EXCEPTIONS = {"gen_port_registry.py"}` is dead code. This is the client-facing "Trust & Sovereignty" panel. |
| 69 | `cisco_toolkit/scorecard.py:82` | FIXED | reported | `_ARTIFACT_VERDICT_RE`'s `([A-Za-z][\w./+-]{1,40})` matches **any** word, so "Verdict: APPROVE" in a session summary mints a QA scorecard row — proposer == verifier at the persistence layer, feeding the calibration nerve. |
| 70 | `cisco_toolkit/scorecard.py:259` | FIXED | reported | `is_provisional` short-circuits to False on any row carrying a numeric `score`, so one extra field disables the entire `JUDGE_TNR_FLOOR` enforcement — and `selfcheck.check_judge_trust` uses the same predicate, so the fabricated-confidence detector is blind to the row that fabricated it. |
| 71 | `cisco_toolkit/selfcheck.py:77` | FIXED | reported | The docstring promises "a check that raises is caught and reported UNKNOWN, never crashes the nightly run", but `run_selfcheck` wraps nothing and the per-check guards catch only `OSError`. One non-UTF-8 byte in `scorecard.jsonl` raises `UnicodeDecodeError` and the immune system goes dark rather than reporting that it went dark. |
| 72 | `cisco_toolkit/selfcheck.py:280` | FIXED | reported | `check_protected_artifact` has no verbatim/byte pin: it checks 8 short anchor substrings, so the never-compressible D12 tier can be compressed to a keyword list and still read GREEN. The only real mechanism (`verify_snapshot`'s sha256) is reachable solely from the manual CLI. |
| 73 | `cisco_toolkit/precert.py:332` | FIXED | reported | `compute_readiness_freeze` silently drops move-groups whose readiness label is absent or unrecognised — they inflate `n_groups` but contribute to neither the worst-of verdict, the distribution, nor `blind_spots`. A freeze can certify READY over groups never assessed. |
| 74 | `cisco_toolkit/docmeta.py:176` | FIXED | reported | `add_related_documents` emits "the set is internally consistent (every number reconciles)" unconditionally, in the same front matter where the SSOT badge may warn the opposite; and `related_rows()` lists web-only kinds a CLI/Atlas set never produces. |
| 75 | `cisco_toolkit/retrieval_eval.py:726` | FIXED | reported | The §7 Hole@10 pool-bias validity bar is vacuous for the strata it protects: the same run judges the pool and then measures holes against it, so Hole@10 is ~0 by construction and the pre-registered verdict is always allowed. |
| 76 | `cisco_toolkit/retrieval_eval.py:249` | FIXED | reported | `load_pooled_qrels` discards the `judge`/`date` provenance `append_pooled_qrels` writes, so a digest-absent run scores itself against grades produced under a different corpus config — the DEC-006 A2 no-pooling rule is prose-only. |
| 77 | `ollama_judge.py:235` | FIXED | reported | `run_baseline` turns a judge that never answered into a measurement: every exception becomes `"(judge error: …)"`, which `parse_verdict` reads as free text and defaults to **APPROVE**, so `approves_clean` can be satisfied with zero successful calls and a `judge_tnr` is appended as real. |
| 78 | `research_lane/sources.py:119` | FIXED | reported | The Cisco PSIRT fetch swallows every per-CVE exception, so a total failure (expired token, 403, DNS) yields an empty advisory list that is then **signed** and published as a legitimate zero-advisory feed. |
| 79 | `cisco_toolkit/design_kb.py:3977` | FIXED | reported | The `_NOT_YET_AUTO_DETECTED` demotion for `security-l2-access-edge-suite` is stale — the advisor does emit it — and the wrong flag is republished into `design_blueprint.doctrine`, which the HLD and `/ask` read. |

## Tier 6 — crash / robustness

| # | Where | Status | Conf. | Defect |
|---|---|---|---|---|
| 80 | `webapp/backend/docx_style.py:66` | FIXED | reported | The web-layer table helper writes raw `str(v)` with no `xml_safe`, while its engine twin sanitizes. One XML-illegal byte from device text makes `doc.save()` raise, so `/deliverable/nrfu`, `/cutover` and the PIR export 500 **permanently** for that snapshot. `tests/test_docx_family_xml_safe.py` parametrizes only the seven engine writers. |
| 81 | `cisco_toolkit/failover.py:56` | FIXED | reported | `_int_or` catches only `(TypeError, ValueError)`; `int(float('inf'))` raises `OverflowError`, so a JSON `Infinity` in `bridge_priority` crashes the L2 failover twin. Every sibling coercer in the repo lists `OverflowError`. |
| 82 | `cisco_toolkit/aclcheck.py:389` | FIXED | reported | `_headers_box` has no IPv4-family guard, so an IPv6 CIDR in a query raises `TypeError` out of `search_filters`. The guard exists on the rule side and is regression-tested there only. A bare v6 address is worse: silently answered over the whole IPv4 space. |
| 83 | `cisco_toolkit/parse.py:3733` | FIXED | reported | `parse_ptp_clock` dereferences `output.lower()` before its own None guard, breaking the module-wide "tolerant; never raises" contract. |
| 84 | `cisco_toolkit/parse.py:817` | FIXED | reported | `_parse_bgp_summary_rows` still carries the unbounded IPv6 alternation the sibling documents as fixed — measured quadratic (1594 chars = 43.9ms; one 3.6KB line = 0.17s through `parse_evpn_summary`). Device output is untrusted and can be megabytes. |
| 85 | `cisco_toolkit/html.py:289` | FIXED | reported | `write_diff_workbook` re-derives interface totals with raw `len()`/`set()` while `compute_snapshot_delta`, called seven lines earlier on the same input, routes it through `_as_dict`. A trimmed snapshot raises `TypeError` at the cutover gate. |
| 86 | `cisco_toolkit/excel.py:1072` | FIXED | reported | ~28 sheet writers call `wb.create_sheet(NAME)` without the delete-if-exists guard the other ~20 use. openpyxl silently renames the collision to `NAME1`, so on a customer-supplied template the stale sheet keeps the canonical tab name — and `write_executive_summary_sheet` then moves the **duplicate** to position 0. |
| 87 | `cisco_toolkit/excel.py:1830` | FIXED | reported | No writer guards Excel's 32,767-char cell limit; openpyxl truncates silently. Affects the remediation plan's `commands` join — a truncated config fragment the engineer is meant to apply. |
| 88 | `cisco_toolkit/excel.py:4300` | FIXED | reported | `append_interface_rows`'s `w()` helper never clears a template cell, so an unobserved field silently retains the **previous run's** value while Hostname/Port/Status are overwritten — rows mixing fresh and stale evidence with no marking. |
| 89 | `COLLECT_PARSE_V3_23_0.py:848` | FIXED | reported | `autodetect_platform` abandons an established `SSHDetect` session on exception (no `finally`), holding a VTY line on production gear. This is the default path (`platform: auto`). |
| 90 | `COLLECT_PARSE_V3_23_0.py:960` | FIXED | reported | On a read timeout `send_cmd` immediately re-sends via `send_command_timing` on a channel with unread output pending, so the capture can splice two executions — and only the one command that fell back is flagged. |

## Tier 7 — tests that pin nothing (the meta-gate)

| # | Where | Status | Conf. | Defect |
|---|---|---|---|---|
| 91 | `tests/test_ci_gates.py:55` | FIXED | reported | `verify-green.sh` — the Stop hook that blocks a turn until the suite is green, i.e. the gate every other test's meaning rests on — is verified only by two substring greps and is **never executed**. Its `rc=$?`, its `exit 2`, and its change detector can all regress with this test green. |
| 92 | `tests/test_proposer_verifier_guard.py:196` | FIXED | reported | The read-only analyst roster pin is a **denylist** of four tool names applied to `tools:`; `tools: *` parses to `['*']` — truthy, no denylisted name — so an analyst can be granted Edit/Write and all five parametrized cases stay green. |
| 93 | `tests/test_readonly_and_no_egress.py:43` | FIXED | reported | Both doctrine guards walk `cisco_toolkit/` with a non-recursive `os.listdir`, so any subpackage is invisible. Same defect as #68, and the dead `gen_port_registry.py` exception proves it. |
| 94 | `tests/test_eval_harness.py:28` | FIXED | reported | The "full eval tier" release gate is skipped unless `EVAL_FULL=1`, which is set **nowhere** in the repository — no workflow, no hook, no script. The only test that renders the whole DOCX family and asserts the `[NOT OBSERVED]` furniture has never run. |
| 95 | `tests/test_ci_gates.py:28` | FIXED | reported | `webapp/tests/conftest.py` un-collects the entire webapp suite via `collect_ignore_glob` when fastapi/httpx is missing — no skip report, no reason line, and `-q` in `pytest.ini` makes it visually identical to a green run. The guard asserts only that two identifiers appear in the conftest text. |
| 96 | `webapp/tests/test_atlas_redaction.py:451` | FIXED | reported | The PPDIOO document gate is **inert** on `--redact-folder` (the engine child runs in a temp workdir, so no ledger is ever found), and the only test touching it drives a hand-written stderr string through a faked `subprocess.run` — a guard asserted exclusively where it cannot fire. |
| 97 | `tests/test_docs_parity.py:52` | FIXED | reported | The CHANGELOG freshness check asserts `"v3.23.176" in ch` against an append-only file while `pyproject` is at 3.31.0 — permanently true, an environment constant. |
| 98 | `webapp/tests/test_atlas_redaction.py` (`test_reuse_out_is_the_deliberate_escape`) | FIXED | **verified** | Order/timing-dependent flake: passes 5/5 in isolation, fails under the full webapp suite — on a **clean** tree too, so pre-existing. `_written_by_this_run` compares (mtime, size) and the fake engine writes identical bytes twice. |

## Also noted (gate_state, beyond tranche 1)

`gate_state.py:935` a typo'd `--engagement` binds a new ledger permanently with no audit row naming it ·
`:980` a case/whitespace variant silently rewrites the canonical identity token ·
`:1359` `show` drops non-dict audit members, under-reporting overrides/refusals ·
`:940` a non-dict `gates` gives a raw `TypeError` and `show` reports no corruption ·
`:1298` the CLI catches only `GateStateError`, so the documented `os.replace` PermissionError escapes as a traceback ·
`:1204` `pending_approvals` breaks its own no-raise contract for a non-str root ·
`:684` `save_store` fsyncs contents but not the directory ·
`:673` `mkstemp`'s 0600 mode is promoted onto the ledger, bricking a shared engagement ·
`:697` `promoted = True` is reached by loop fall-through ·
`:372` `ENOLCK` is classified unsupported though POSIX returns it transiently under contention ·
`:344` `_whoami` is env-forgeable, so every audit `who` is self-asserted ·
`:107` a whitespace-only `--engagement` downgrades the ownership refusal to proximity matching ·
`:137` five engine line-number citations in the module docstring are stale.

---

# Round 2 — the surfaces round 1 never looked at

Round 1 was breadth-complete but **depth-sampled** (8 candidates per partition) and covered **Python
only**. The coverage ledger below is what made that measurable, and it is why round 2 exists.

## Coverage ledger (`git ls-files`, code only)

| Area | Files | Lines | Round 1 | Round 2 | Round 3 | Round 4 |
|---|---:|---:|---|---|---|---|
| `tests/` + `webapp/tests/` | 209 | 53,221 | pattern-audit | **exhaustive AST scan** (205 files / 2,772 test fns) | — | **3-partition MUTATION audit — 20 tests proven vacuous by breaking the code they claim to pin** |
| `cisco_toolkit/` | 71 | 63,398 | per-file | deep re-pass on `analyze.py`; **`blast_radius_explorer.html` (10,500 lines) reviewed for the first time** | **deep pass on the 4 remaining large files** (`parse`, `design_advisor`, `excel`, `design_kb`) | mid-tier files: `build`+`html` (swept over **253 real device captures**), `archreview`+`runbook`+`mop`; `analyze.py` R4-1 |
| `webapp/frontend/` | 46 | 7,876 | **never reviewed** | api + pages, components | — | **second pass** — 5 fixed, 6 refuted |
| `webapp/backend/` | 16 | 5,907 | per-file | `graph.py` (via the frontend findings) | `ingest.py` (via the Atlas boundary) | **`app.py` deep pass** (largest, never deep-passed) + `cutover.py` |
| `.claude/` + `.github/` | 14 | 1,185 | **never reviewed** | hooks + workflows | — | — |
| root, `portable/`, `research_lane/` | 19 | 6,092 | per-file | — | **the three trust boundaries** + `COLLECT_PARSE` | — |
| *excluded:* `.design-sync/` | 21 | 1,023 | design tooling, outside the build (verified — see below) | — | mechanical guard added (`test_design_sync_no_client_data.py`) | that guard was itself proven VACUOUS and fixed (VB-3) |
| **total** | **396** | **138,702** | | | | |

Every row carries at least two passes except `.claude/`+`.github/` (1,185 lines, one pass) and
root/`portable/`/`research_lane/` (deep-passed once, in round 3). Those are the thinnest remaining
surfaces and are named here rather than left to be inferred.

**What this ledger does and does not claim.** It says the whole repo was looked at deliberately, with
increasing depth, and that the deepest passes were verified by mutation rather than by reading. It
does not say the repo is defect-free. Round 4 is the strongest evidence for that caution, not against
it: after three rounds and ~220 closed findings, a mutation audit still found 20 tests that pinned
nothing — including four safety guards and, behind one of them, R4-1. Every round has found the
previous round's blind spot, and there is no reason to believe round 4 was the last one.

**On the one exclusion.** This row originally read "side-engagement scratch (CLAUDE.md)", which was
wrong: CLAUDE.md and `.graphifyignore` exclude `ds-bundle/` and `.ds-sync/` — the design-sync *output*
bundle — not `.design-sync/`, which is a different directory and is deliberately tracked
(`.gitignore:61` names the committed set: `config.json`, `NOTES.md`, `conventions.md`, `previews/`,
`docs/`, `overrides/`). Excluding it from the review is still right, but for reasons that were
checked rather than cited: nothing under `cisco_toolkit/`, `webapp/backend/`, `portable/` or
`research_lane/` references it; `webapp/frontend/tsconfig.json` is `include: ["src"]`, so the
`previews/*.tsx` never enter the build gate; and no vite/rollup root reaches it. Its `NOTES.md` also
asserts a confidentiality invariant in prose — the sample fleet must stay fictional because
design-sync uploads it to claude.ai — which was verified mechanically here and **holds**: no hostname
from `tests/golden/snapshot.json` appears in it, and every IP literal is private, loopback or a
reserved documentation range (TEST-NET / 198.18 / 203.0.113). `.design-sync/.cache/` is gitignored,
so the absolute paths in its local `resync-run.log` are not committed.

## What round 2 found

Roughly 90 further findings. The three that matter most:

1. **Three hooks were completely dead on this machine.** `python3` here is the Microsoft Store
   App-Execution-Alias stub — it prints "Python was not found" and exits 49 — and `|| true` swallowed
   it, so each hook exited 0 having emitted ZERO bytes. One was the `UserPromptSubmit` hook that
   injects the operating protocol, so **every prompt in every session ran without it**. Nothing could
   see this: `.claude/settings.json` was read by no test, and only 4 of 9 hooks were ever executed by
   one. Measured 0 bytes before / 3756 after.
2. **`verify-green.sh` went inert once changes were COMMITTED** — it read the working tree only, so
   the repo's most load-bearing gate stopped applying at the ordinary end of a turn's work.
   Reproduced: identical red suite blocks at exit 2 uncommitted, allows at exit 0 committed.
3. **The explorer carries a second reachability engine with no behavioural gate.** The existing
   parity test executes real JS but covers only the FIB tracer; the model core (`buildModel`,
   `failureImpact`, `tracePath`, `compareModels`) had none, and held 8 divergences from `analyze.py`
   — including a single-homed path advertised as an STP "transient outage" while the correct
   "permanent partition" warning sat in the file as **dead code**.

Also: `/graph` matched canonicalised names against RAW hostnames, so any fleet named `[HISTORY-REDACTED]-CORE-01`
(the Cisco norm) returned **zero edges** — 25 → 0 — drawn as a fabric with an empty SPOF overlay; a
management VRF made a FLAT fabric grade `advisory` instead of `deviation` (conformance weight 0.7 vs
0.35); `archreview` counted a port with BPDU Guard **explicitly disabled** as guarded, while
`design_advisor` counted the same port unguarded off the same field; and `_APP_BAND_RANK` ranked
"Insufficient Data" *better* than Excellent, so a domain of never-collected switches was nominated as
the **pilot** wave.

## Self-inflicted, caught by refutation — recorded because they are the useful part

- The `n_checked` field added in round 1 was rendered by `docmeta` as `{n_checked} of {n_facts}`.
  They are different units (one fact reconciles against several bases), so all seven DOCX
  deliverables shipped **"20 of 14 headline figures self-verified"** — more than the whole. Found by
  the SSOT audit, not by me.
- The suite-non-vacuity meta-guard enumerated via `git ls-files`, so an **untracked** file — the
  exact case it exists to catch — was invisible, and all three assertions passed over planted
  violations.
- The first `/graph` reproduction recursed into field names and renamed `cdp_neighbor` itself,
  "reproducing" the defect for the wrong reason.
- The `verify-green` scope test went clean→modified, moving `git status` too, so it passed with
  content removed from the state key.
- The explorer's new parity gate was one-sided ("never healthier") and stayed green through a
  reverted fix; it now asserts both directions.

Every one surfaced by planting the violation and watching the guard NOT go red. A test that has
never been observed failing is not evidence.

## Open tail — reported, deliberately not fixed

These are real and grounded; each was left because the fix needs a decision, a toolchain, or a blast
radius outside a review's remit. They are the honest answer to "is the repo now clean?" — no.

| Where | Why not fixed |
|---|---|
| `Snapshot.tsx` / `Execution.tsx` — deliverable downloads are plain `<a download>`, so a 403/500/503 body is saved to disk AS the DOCX, and the backend's `X-Gate-Status` disclosure (an unmet PPDIOO gate) is unreadable | needs a fetch+blob download path — the app's primary artifact channel in the field; not safe to rewrite without browser verification |
| `html._slim_for_embed` strips the `[NOT OBSERVED]` physical-health rows before the explorer sees them | an explorer-side fix alone is inert; needs both halves |
| four more `badge b-ok">clean` claims in the explorer (layer heatmap, path hazards, addressing, STP root) | each needs its own "was this axis collected?" predicate; a wrong one turns a real pass into a false blind spot |
| `_linkSig2` (reachability matrix) repeats the parallel-link collapse fixed in `compareModels` | outside the reviewed line range |
| explorer has no `ecmp_dropping_legs` / `drop_evidence` equivalent | `fib.py` gained them opt-in specifically to keep parity green; surfacing them is a UI decision |
| `webapp/tests` is in the default testpaths but never EXECUTES in a required check — mechanism verified below | the obvious fix contradicts a documented design decision; see below |
| `ci.yml` reroutes every matrix job to the self-hosted pool via `vars.CI_RUNNER`, so 5 required checks say `ubuntu-latest` while Linux is never exercised | fleet policy; renaming would change the required contexts |
| gateway-SVI predicate differs between `segmentation` (VlanN + svi_ip) and `l3_forwarding` (svi_ip OR hsrp OR route) | agrees today; the fix is a producer-level decision in `excel.py` |
| `CausalFlow` draws `blast === 0` (the not-measured sentinel) as the thinnest connector | the payload carries no separate unmeasured flag, and 0 is also a legitimate measured value |
| `onWheel` `preventDefault()` is a no-op (React registers `wheel` passive) | needs a ref + non-passive listener; jsdom does not enforce passive semantics, so any test here would pass either way |
| `vault-guard.sh` over-blocks vault SIBLINGS (`brainstorm/`) | its declared recall-over-precision posture; tightening REDUCES a security control's reach |


## Open, and the most important one — the suite outgrew its own gate

`.claude/hooks/verify-green.sh` bounds its pytest run at `timeout 540` and, on exit 124, FAILS OPEN
so a hang can never wedge a turn. Measured after this review: the full suite takes **1055s**. So the
gate now *always* times out and *always* allows the stop. It says so on stderr — it is not silent —
but it no longer gates anything.

That is the second time today this hook stopped applying for a different reason (the first was
CI-9: it only ever read the working tree). Raising the bound is not available: the Stop hook itself
has a 600s ceiling, so 540 is already near the maximum.

What the runtime is actually made of, measured with `--durations`:

- ~20 tests each run the **whole engine pipeline** end to end at ~11–13s apiece. All pre-existing;
  the slowest single test (`test_runbook_survives_truthy_scalar_nested_value`, 22.2s) landed in #457.
- Attributable to THIS review: the new test files total ~33s, and `compute_attestation` went from
  67 top-level modules to a **recursive** 69-module AST walk — 2.54s per pipeline run, so ~50s
  across the suite. That cost is justified: the claim it replaced ("0 network-library imports") was
  false, which is precisely why `NO_EGRESS_EXCEPTIONS` was dead code.
- The remaining delta is **not attributed**. The 6m53s baseline was taken mid-session under
  different machine load than the 1055s run, so the two are not a controlled comparison and I am not
  going to present them as one.

Options, none of which a review should pick unilaterally:

1. **Shard the gate** — have the hook run a fast, high-signal subset and say plainly that it did,
   with the full suite in CI. Honest, but weakens the "green means green" contract the repo relies on.
2. **Speed up the pipeline tests** — ~20 full-engine runs is the whole cost. A shared session-scoped
   fixture that builds the pipeline once would likely reclaim most of it. Biggest win, own project.
3. **Accept it and lean on CI** — but `webapp/tests` is already gated by no required check (above),
   so CI is not currently a complete backstop either.

---

# Round 3 — the five files that had only ever been sampled

Round 2's coverage ledger left one row with an empty cell and four files carrying nothing but round
1's 8-candidate sample. Round 3 closed both. Five deep passes, each owning a disjoint file set, each
instructed to refute before fixing and to prove every fix by reverting it.

| Target | Lines | Fixed | Refuted |
|---|---:|---:|---:|
| `cisco_toolkit/excel.py` | 4,583 | 6 | 6 |
| `cisco_toolkit/design_advisor.py` | 4,897 | 6 | 4 |
| `cisco_toolkit/parse.py` | 4,623 | 4 | 4 |
| `design_kb.py` + `COLLECT_PARSE_V3_23_0.py` | 7,588 | 6 | 6 |
| `portable/` + `research_lane/` + `ollama_*` | ~1,840 | 7 | 4 |

The refutation counts matter as much as the fixes: 24 candidates were disproven against the code
rather than "fixed" defensively. Examples — the four Excel structural caps are unreachable
(`wb.create_sheet` has exactly one call site, every sheet name is a module constant); a suspected
dead half-duplex check is sound because `parse.py:4393` calls `.capitalize()`; `parse_security`
cannot fabricate a hardening report from an error banner because `cmdio._load_cmd_output` screens
`% Invalid input` upstream and `parse_security("")` returns `{}`.

## The three that reached, or could have reached, a human

1. **A read verb with a write tacked onto it passed the wire gate.** `is_ssh_wire_command` was
   `^show\s+\S` — a check on the FIRST WORD. `show running-config | redirect bootflash:x` (NX-OS
   WRITES that file), `show run | tftp://host/x` (ships the config off the box), `show version ;
   reload`, and a read verb followed by an embedded NEWLINE all passed the guard whose whole purpose
   is to forbid them — netmiko writes the string to the channel verbatim, so every embedded line is
   typed at a live exec prompt. Not reachable by today's 100 wire-eligible commands; the point of a
   positive grammar is that a LATER entry is excluded by default, and this is the one entry a prefix
   check cannot see. Now whole-string.
2. **The published attestation asserted the same thing on the same broken basis.**
   `read_only_command_surface` is one of four claims the engine PUBLISHES, and
   `attestation.py :: READ_ONLY_CMD` had the identical prefix-only weakness — so the engine would
   have certified a read-only command surface while carrying a command that writes to bootflash.
   Escalated by the collector pass because the file was outside its ownership. Proven by reverting:
   *"attestation published HOLDS for a registry containing 'show running-config | redirect
   bootflash:pwn.txt'"*.
3. **`STP Root Bridges` printed `Aligned? = yes` for VLANs it never compared.** `stp_root_findings`
   ABSTAINS for a VLAN with no collected gateway SVI — it cannot be in `misaligned`, there being
   nothing to be misaligned with — and the writer read that abstention as an empty findings list.
   On an access-only collection every gateway sits on an uncollected core, so the whole sheet reads
   aligned. The converted deliverable in `graphify-out` shows dozens of consecutive rows doing
   exactly that.

## Enumerating the exits, again

Fixing (2) meant finding that the read-only grammar had **four** consumers in three spellings:
`attestation.py`, two sites in `tests/test_readonly_and_no_egress.py`, and a *re-derived copy* in
`tests/test_nrfu_export.py` — which guards the command files an engineer actually executes during
NRFU, and so was the worst place to hold the weaker rule. All four now compose from one owner via
`is_read_only_command(..., extra_verbs=)`, which widens the VERB list only: `traceroute 10.0.0.1 ;
reload` is still rejected.

The same shape appeared on the sanitizer. `research_lane.sanitize` (producer side) and
`intel_feed.verify_feed` (consumer side) are the two halves of one Rule-3 gate, and both did a
literal token match — so they shared a blind spot exactly, and the second could never catch what the
first missed: an operator's `"Acme Bank"` never matched the device spelling `ACME-BANK-CORE-01`, and
a feed arrived attested `sanitized: true` with an EMPTY redaction list. One owner now
(`textutils.forbidden_token_pattern`).

## A false alarm on good output

`_written_by_this_run` decided "did this run write it?" from `(mtime, size)` inequality against a
pre-run stat. Re-running the same collection into the same folder produces byte-identical documents,
and an immediate same-size rewrite moves neither field — measured here, `st_mtime` delta `0.0` every
time. The document WAS rewritten and the check said it was not, so it was reported *"left by an
EARLIER run into this folder … check which job it belongs to"*: a freshly-redacted set telling the
engineer it might belong to another client. Fixed by stamping a sentinel mtime a day back on the
engine-owned files before the run, so a rewrite is detectable regardless of tick granularity — and
regardless of which direction the clock moved, which the original inequality was deliberately
protecting and which a strictly-greater test would have broken.

## Open, and honestly so

**`webapp/tests/test_atlas_redaction.py` is order-dependent.** Under a full-suite run it fails
intermittently, naming a different test each time (`test_the_note_never_claims_safety_over_an_
uncertified_leftover`, `test_stale_names_…`, `test_an_untouched_note_is_still_cleared_…`). It is
**pre-existing** — proven by stashing all of this session's work and reproducing at HEAD. It passes
in isolation and in fixed order.

On whether the mtime fix above is its cause, this register contradicted itself and the contradiction
is worth keeping rather than smoothing over. **Round 2 finding #98 already recorded this flake, named
the same mechanism, and marked it `verified`** — "`_written_by_this_run` compares (mtime, size) and
the fake engine writes identical bytes twice". Round 3 then re-derived the same mechanism
independently, from the production side rather than the test side, and proved the blindness directly
(`st_mtime` delta `0.0` on every same-size rewrite).

So the mechanism has now been arrived at twice, by two routes. What I could NOT do today is
demonstrate the causal link on demand: a repro that looked deterministic stopped reproducing on
**both** sides of the fix. That is weak evidence about the mechanism and strong evidence about the
measurement — the same suite timed 440s and 1326s on an identical tree, so this box cannot hold a
timing window still long enough to bisect one. The honest statement is therefore: **cause identified
with good confidence and fixed on its own merits; elimination of the flake NOT observed.** It stays
open until a full run demonstrates it, not because the diagnosis is doubted.

## Two errors of mine, recorded because the review is the wrong place to be tidy

- I called `.design-sync/.cache/resync-run.log` a committed client-name leak. It is gitignored and
  `git ls-files` on it is empty — my `grep -r` walked the filesystem, not the index. No leak.
- My first test for the mtime defect **passed with the fix reverted**. It raced the tick rather than
  forcing it, so it pinned nothing — the exact class this review exists to find, written by the
  reviewer. Replaced with one that simulates the coarse tick deterministically and was then shown to
  fail without the fix and pass with it.

## The `webapp/tests` gate gap, traced end to end

Recorded earlier as a remembered claim; here is the verified chain, because the fix that looks
obvious is the wrong one.

1. `pytest.ini` sets `testpaths = tests webapp/tests` — both ARE in the default gate.
2. `.github/workflows/ci.yml:74` runs a bare `python -m pytest`, so the required Tests matrix DOES
   collect `webapp/tests`.
3. But `ci.yml` installs only `requirements.txt -r requirements-dev.txt`, and **neither declares
   `fastapi` or `httpx`** (grepped: zero hits).
4. `webapp/tests/conftest.py` therefore sets `collect_ignore_glob = ["test_*.py"]` and the whole
   directory is un-collected — the Atlas redaction suite, the security-hardening suite, the
   DNS-rebinding allowlist and the unplug-safety suite among them.
5. They execute only in `webapp-ci.yml:53` (`python -m pytest webapp/tests -q`), which is
   **path-filtered**.

So the safety suites are collected by a required check and run by a path-filtered one. To this
repo's credit the un-collection is **loud, by design**: `pytest_report_collectionfinish` prints
"webapp/tests: NOT COLLECTED — missing … this run's green does not cover them", added precisely
because `-q` had made a silently-dropped directory look identical to a full pass.

**Why the obvious fix is not obviously right.** Adding `fastapi`/`httpx` to `requirements-dev.txt`
would make the required matrix run these suites — but the conftest's docstring states the opposite
intent explicitly: engine-only environments "must skip this directory cleanly", and the engine's own
CI matrix is named as one of them. Changing that makes every engine matrix job install the web stack.
That is an architecture decision (does the engine's gate own the web layer's safety suites?), not a
review fix, so it stays open. The alternative — making `webapp-ci` a required context — is a
branch-protection change, equally the owner's call.

---

# Round 4 — the tests themselves, and the surfaces with only one pass

Round 3 closed the last files that had never had a deep pass. Round 4 attacks the remaining gap the
ledger still showed: `tests/` (197 files, 49,786 lines) had been audited only MECHANICALLY — an AST
scan for three unambiguous shapes. Seven passes: three partitions of `tests/` hunting the vacuity
shapes a scanner cannot see, plus `webapp/frontend/`, `webapp/backend/`, and the mid-tier engine
files (`build.py`, `html.py`, `archreview.py`, `runbook.py`, `mop.py`).

The `tests/` passes were required to **mutate the production code a test claims to pin and prove the
test stays green** — pattern-matching alone only produces suspicions.

## R4-1 — a move group graded READY off evidence that was never collected

**The worst finding of the whole review**, and it was found by auditing a test rather than the code.

`cisco_toolkit/analyze.py:2170,2175` computes the two runbook audit checks as

```python
missing_topo = sorted(gset - topo_hosts) if topo_hosts else []
missing_base = sorted(gset - baseline_hosts) if baseline_hosts else []
```

When the evidence set is **wholly empty** the difference is forced to `[]`, so "nothing is missing"
and the check reports `pass` with an affirmative note. Reproduced directly against the production
entry point with `all_interfaces={}`, `physical_health=[]` and no topology model:

```
PASS | Dependency mapping complete: topology/dependency map covers all group switches
PASS | Baseline capture:            interface/physical counters captured for all group switches
VERDICT: READY   n_warn: 0
```

Both sentences assert COVERAGE of evidence that does not exist, and the group is graded READY — the
verdict a human uses to schedule a cutover. `snap['migration_readiness']` feeds the runbook, deck and
design deliverables, and **both pinned snapshots already embed the fabricated notes**
(`tests/golden/snapshot.json:3045-3053`, `webapp/sample_data/sample_fleet.snapshot.json:16993`).

The same function's `Device health floor` check, twelve lines above at :2158, handles the identical
no-evidence case correctly — `warn` + "device health floor not assessable". So the correct pattern
was already present in the same function, applied to one check and not its siblings.

**Why a scanner could never have found it.** The only test covering this behaviour
(`tests/test_readiness_phases.py:82`) pins the fabrication as DESIRED: its docstring reads "the audit
checks fall back to pass rather than crying wolf". Grep across `tests/`, `docs/` and `cisco_toolkit/`
found no other guard and no ADR accepting the trade — the behaviour is asserted as correct in exactly
one place, and that place is a test. This is shape 3 of the vacuity taxonomy (a guard exercised only
where it is inert), with the docstring blessing the inert branch.

**Sequenced, not yet fixed.** `runbook.py` renders `migration_readiness` and a concurrent agent owns
that file; changing the notes mid-flight risks it pinning the fabricated sentence in a new test. The
fix lands once the concurrent passes complete, and both pinned snapshots need re-blessing with it.

## What round 4 found

**41 fixed, 23 refuted, and 20 tests proven vacuous by mutation.** The `tests/` passes were required
to break the production code a test claims to pin and show the test stayed green — so every vacuity
claim below is a measurement, not a reading.

The most important number is a negative one: of the 20 hollow tests, **19 were hiding nothing**. The
shipped code was correct in every case and only the guard was empty. The twentieth was R4-1 above.

### The four safety guards that fell (slice C)

| Guard | Mutation it survived |
|---|---|
| "The SSH send path has no config/write sink" — the read-only floor on the leg that touches customer switches | `conn.write_channel("hostname PWNED\n")` — **a production switch renamed from inside the collector**. `write_channel` is netmiko's raw-channel escape hatch, the primitive `send_config_set` is built on; the guard scanned for four method-name spellings and this is not one of them. Payload assembled at runtime, so the substring scan could not see it either. |
| "`rest_collect` is GET-only bar one login POST" | a second real HTTP write. urllib resolves `Request(url, data=…)` with no `method=` to POST by itself, so a write that does not spell its verb as a literal kwarg was invisible. |
| "The collector never persists the password" | a `session.json` holding the plaintext credential dropped beside the exports and simply not appended to the returned file list. |
| "The webapp un-collection is announced, not silent" | deleting the announcement entirely — the branch only ran on boxes that do not have the problem. |

### The master pattern

Three of those four asserted a safety property by **matching source text**, or by **inspecting a
value the code chooses to return** — rather than a structure the code cannot avoid producing. That is
the pattern to hunt next anywhere in this repo. The fixes now walk the real artifact on disk as
bytes, or resolve the property structurally from the AST, with a non-literal `method=<var>` failing
LOUDLY as unprovable rather than passing. Two non-vacuity assertions are mandatory in the same run:
the walk must find the known-good calls, and the denylist must fire on a planted violation.

A fifth of the same family, from slice B: the emitted explorer's **CSP was asserted for presence
only**. Rewriting the injected policy to `default-src * https:` / `connect-src https://evil.example`
— a fully egress-capable air-gapped deliverable — left the test green, and no other test in the repo
mentions CSP.

### A systemic defect, not four coincidences

Four independent surfaces published a verdict computed by **refining a seeded-optimistic default in a
loop that an empty set never enters**:

- `analyze.py` grading a move group **READY** (R4-1)
- `cutover.build_plan` publishing **`verdict: "GO"`** with zero derived waves — the DOCX printed
  "Cutover posture: GO" in green directly above its own line "No migration waves were derived from
  this snapshot" (BE-2)
- the SPA's **green** "Move-group readiness" tile reading `0✓ 0! 0✕` when nothing was classified
  (FE-12)
- round 3's segmentation asserting "a single global VRF — L3-unsegmented" from an absent block

They were found by four different agents looking at four different layers, which is what makes it
structural. `execution._derive_outcome` already documents and fixes this exact shape; the pattern is
known in-repo and was simply not applied to its siblings.

### The one that would have caused an outage

`mop.py` §x.5 for a pure make-before-break wave decommissioned the legacy path **before** the §x.6
go/no-go validation, while §x.7's rollback read "Because the legacy path was never torn down, this is
non-disruptive" — and named no restore path at all, never referencing the §x.3 configuration backup
that §x.3 itself declares mandatory "for the §x.7 rollback". The phase tags even ran
PRE,PRE,DURING,DURING,DURING,POST,DURING,POST — a `[DURING]` step after a `[POST]` one.

At 2am the engineer follows the numbered steps, tears down the legacy path, runs §4.6, hits a High
failure, opens §4.7 — and is told to fail back onto a path he removed two steps ago, with no restore
procedure on that branch. Reproduced on the sample fleet's real Group 2 (100% dual-homed).

### Measured against real fleet data, not fixtures

The `build.py` pass swept **253 real device captures** rather than reasoning:

- the global BPDU-Guard promotion matched only the pre-IOS-XE-16 spelling, missing
  `spanning-tree portfast **edge** bpduguard default`. Real collection: 109 classic, 25 edge-form.
  Fleet-wide effect of the fix, measured: ports reading `stp_bpduguard='Enable'` **8797 → 10062**.
  Worse than under-reporting — on a mixed box one explicit per-interface `bpduguard enable` flips the
  seen-flag True, and every *other* access port is then counted as an OBSERVED unguarded gap that
  does not exist.
- `neighbor_switch_vtp_domain` was **this** switch's own domain. 367 of 367 populated rows (100%)
  were self-copies, so the workbook comparison an engineer uses to find VTP mismatches across trunks
  could only ever return "every trunk agrees".
- `neighbor_switch_serial` was the neighbour's **hostname** — 581 rows — and `html.py`'s
  `_REDACT_SERIAL_KEYS` then pseudonymised those hostnames into `SNxxxx` while deliberately keeping
  hostnames everywhere else, making the shared deliverable inconsistent with itself.

### Deliberately not fixed

- **The 5-MAC cap** (`build.py`): ~1579 ports truncated, measured from the real per-port histogram
  (the spike at exactly 5 against 43 at 4 is the cap's signature). Not fixed *because* the obvious
  fix is worse: every consumer tokenizes the field naively, so a shared `(+N)` marker token appearing
  on two hosts would make `detect_cross_device_dual_connections` set `dual_connection='Yes'` on both
  — fabricating redundancy. The real fix changes `textutils._split_macs` or adds a model field.
- **`/api/campaigns/{id}/trend` memory**: measured at ~3.8 MB per snapshot, so ~2 GB at 20 large
  collections. Refuted as a vulnerability (the route is `_forbid_cross_site`-guarded and the input is
  the operator's own campaign). Capping N in the route would trade a memory bug for a
  coverage-honesty bug, so it needs a streaming rewrite in `html.py` instead.
- **Undisclosed display caps in `runbook.py`** (§3, §6.2, §6.5, §6.6, §8.1, §10, §10.1). §6.2 is the
  consequential one: §1's register states the full Critical/High cross-layer total while §6.2 renders
  at most 8 blocks. The same class was fixed in `mop.py` §x.2, where a precondition gate depended on
  it.

### Fixing R4-1 required changing the test that blessed it

`tests/test_readiness_phases.py::test_audit_checks_never_flip_verdict_when_data_absent` asserted
`status == "pass"` for both checks with no evidence present. It was the only place in the repo
stating the fabricated behaviour as intended, and the full suite went red on it the moment the fix
landed — which is the correct signal, not an obstacle.

The temptation is to delete the two assertions. That would have been wrong: the test's NAME is its
real contract, and that contract still holds. Absence must not cry wolf — the verdict, `n_warn` and
`n_fail` are all untouched by the fix, because an unassessable axis emits `info` and the verdict
inspects only `fail`/`warn`. So the test now pins BOTH promises separately, because they are
different and only one was ever in doubt:

* **no cry wolf** — `readiness == "READY"`, `n_warn == 0`, `n_fail == 0` (unchanged, still asserted);
* **no fabricated coverage** — the status is not `pass`, the note says NOT ASSESSABLE, and the two
  specific sentences that were invented ("covers all group switches", "captured for all group
  switches") are absent, matched whitespace-normalised so a re-wrap cannot silently un-pin them.

It is strictly stronger than before and still discriminates: reverting the abstention in `analyze.py`
turns it red. Whether a wholly unassessed axis should ALSO downgrade READY is a separate design
decision, deliberately not taken here — and the docstring now says which assertions would change if
it ever is.
