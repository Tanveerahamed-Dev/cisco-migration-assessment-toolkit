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
