# Synthetic 300-device pre-release scale qualification

The hosted workflow measures the actual offline engine, AssessHub collection ZIP
ingest and stored-byte API, all six `ui_projection` views and their first/last
list pages, then the Atlas Scope compiler against that same stored snapshot.
It is a synthetic capacity gate for preparing the owner's real-infrastructure
run. It does not certify the real fleet, browser rendering, the Windows portable
binary, media, or owner acceptance. Atlas Scope's preview decision remains.

## Corpus and paths

`webapp/sample_data/build_scale.py` owns profile `synthetic-campus-300/1`:
240 access, 40 distribution, 8 core, 6 Catalyst 9800 WLC and 6 ASA firewalls.
Twenty paired distribution pods carry 200 VLANs. The 1,500 unique-port physical
cables include 632 managed-device links with reciprocal CDP and 868 observed
phone neighbours with no collected inventory. These neighbours are explicitly
uncollected; the managed fleet denominator remains 300.

The demo's `_sw_trunk`, `_sw_access`, `_PLATFORMS`, `_write_collection` and
`_make_template` generators are reused without modifying its golden snapshot.
Show outputs contain 48/64/96 switch ports, 512–4,096 MAC rows on bridging devices,
250 ARP rows on SVI devices and actual peer entries on routed devices,
200–1,000 routes and 1,000 logging records per device, plus WLC AP/summary and
ASA HA/resource/connection captures. Routed links use reciprocal unique /30
subnets and interface config/brief share their address records. Unsupported vendor-specific records remain raw
capture load, never invented parsed coverage. Captures use fixed identities,
order, LF bytes and collection instant; ZIP headers have fixed timestamps.
The report includes capture/ZIP digests, capture-size ranges and parsed fleet
censuses. The CLI's normal run timestamps are not claimed byte-reproducible.

The engine stage executes the installed `cisco-assess --no-collect
--collection-dir` command with one worker. It writes the workbook and full
snapshot and suppresses optional document rendering, matching AssessHub's ingest
path. The ingest stage uploads the deterministic ZIP through the real HTTP
route using ASGI transport; it runs its own normal engine child and persists the
result in a fresh SQLite store. Projection uses that store, not a constructed
or enlarged snapshot. Every response must bind its exact persisted bytes.
Scope uses the actual `compile-all.mjs` validation/binding/compiler path with
an external output directory. No tracked sample or compiled file is rewritten.

## Budgets and measurement

`.github/scripts/qualify_scale.py :: BUDGETS` is the sole budget owner. The initial
ceilings are chosen before measurement: generation 60 s / 512 MiB / 128 MiB;
CLI 600 s / 3 GiB / 256 MiB; ingest 660 s / 4 GiB / 128 MiB; projection 180 s /
2 GiB / 64 MiB; compile 60 s / 2 GiB / 128 MiB. Time budgets keep the offline
engine inside AssessHub's existing 600-second engine timeout and reserve ingest
overhead. Memory budgets leave headroom on the pinned hosted Linux image;
output ceilings retain finite artifact, archive and snapshot size. These are
engineering regression limits, not independently approved workload budgets.
Do not raise them merely to make a failing run pass.

Each stage starts a fresh process group. Wall time includes imports, stage work
and its census validation. Peak RSS is the maximum sampled **sum** of live group
residents (50 ms intervals, including the ingest engine child), with the exact
leader `wait4` high-water mark as a floor. Shared pages can be counted twice and
short child spikes between samples can be missed; this is an explicit RSS
measurement contract, not Python heap or cache accounting. Artifact size is
the complete stage-owned uncompressed output tree; log/report files and toolchain
installation are excluded. Any execution failure or budget breach fails the
job, retains the partial measurements and logs, and marks dependent stages
skipped. Tests exercise actual failing child processes for each budget class.

## Hosted execution and evidence

`.github/workflows/scale-qualification.yml` has only `workflow_dispatch` and a
weekly Monday 02:23 UTC / 05:23 Qatar schedule. It selects `ubuntu-24.04`, Python
3.12 and Node 24.19.0, uses pinned actions, read-only contents permission and
credential-free checkout, and binds the selected full source commit. The
composite action refuses execution outside GitHub-hosted Linux.

GitHub requires a new manual workflow to exist on the default branch before its
first dispatch. The existing `ci.yml` therefore has an opt-in
`measure_scale_qualification` dispatch input; its guarded job calls the identical
composite action to obtain pre-merge numbers. It never qualifies on a PR or push.
Other CI checks remain unchanged. After merge, the standalone weekly/manual
workflow is the normal door. The weekly schedule activates only on main.

The 30-day `scale-qualification-300-<sha>-<run>-<attempt>` artifact carries
`report.json`, `summary.md` and one log per attempted stage. The JSON records
source commit/tree, run/attempt, runner/tool versions, budgets, wall/RSS/size,
censuses, CLI slow phases, projection request timings and failed evidence.
The job summary carries the same table; the PR body must cite its measured
source and run, not transfer measurements from an older head. Rule-7 repository,
history/per-parent patch and publication-body marker scans precede every push.

No local engine, test, build or measurement is permitted. Claude reviews and
merges after hosted checks are green. Large discovered defects get their own
board row with the failing source/run and closing evidence.
