# Architecture: read-only & no-egress (the air-gapped moat)

This engine is **read-only and fully offline by construction** — not by policy, configuration, or a trust
statement, but by what the code structurally *can* and *cannot* do. As of 2026-06-25 these properties are
**enforced by regression tests** (`tests/test_readonly_and_no_egress.py`, roadmap items W1-1/W1-2) that fail the
build if a future change breaks them. This is the differentiator the cloud assurance tools (Forward, Auvik,
ThousandEyes) and cloud AI SSH clients (e.g. Transit AI) structurally cannot offer: they require sending data to
a cloud, so they cannot run inside a secure enclave.

## The exactly-two network paths
Only two code paths touch the network, both **collectors**, both **read-only**:

1. **SSH collection** — `COLLECT_PARSE_V3_23_0.py` via `netmiko` (imported lazily inside `connect_device`,
   ~L458). It has a **protocol-level read-only floor**: it issues only `dev.send_command(...)` — which *cannot*
   change device state — never `send_config_set`/`send_config_from_file`/`config_mode`. The only non-`show`
   strings on the wire are the two terminal-pager-disabling setup commands (`terminal length 0` /
   `terminal width 511`, L810). Every collected command is a read query (`show`/`display`/`get`/`moquery`/
   `aws ec2 describe-*`), re-verified from the registries by `test_command_registries_are_read_only`.

2. **Controller-REST collection** — `cisco_toolkit/rest_collect.py` (opt-in, never auto-runs; ACI/APIC,
   Catalyst SD-WAN/vManage, ISE, FMC). **GET-only except a single login POST**; no PUT/PATCH/DELETE method
   exists in the module, so it cannot create/modify/delete a fabric object. *Honest caveat:* REST has no
   protocol-level read-only floor the way SSH `show` does (a stolen token with write scope could POST), so it
   **requires a dedicated read-only RBAC account** — this is a deployment requirement, documented in the module.

## What never touches the network
**Everything else** — the entire analysis → design → deliverable pipeline (`cisco_toolkit/analyze.py`,
`design_advisor.py`, `html.py`, `mop.py`, `crd.py`, `deck.py`, the explorer, …) — imports **no network library
at all** (`socket`/`requests`/`httpx`/`urllib.request`/`netmiko`/`paramiko`/…). After collection, the engine
operates purely on the local `snapshot.json`; it can be run **`--no-collect --collection-dir <dir>`** on a
fully air-gapped host with zero outbound connectivity. `test_no_network_egress_in_analysis_pipeline` enforces
this by walking every import in `cisco_toolkit/*.py` (at any nesting depth — lazy imports included), with only
`rest_collect.py` and the dev-only `data/gen_port_registry.py` (a one-off data-pack generator, not reachable
from the runtime pipeline) excluded.

## No LLM / no telemetry
There is **no AI/LLM inference path and no telemetry** in the engine. The offline Ask-the-Engineer chat
answers deterministically from the snapshot (it is not a model), as it states in-product
(`blast_radius_explorer.html`: "fully offline … no cloud, no model, no telemetry"). Redaction
(`--redact`, `cisco_toolkit/html.py`) one-way-scrubs secrets before any snapshot/log is written.

## Why this is enforced, not asserted
A "we're secure / we're offline" claim is exactly the kind of unverifiable marketing the engine's
coverage-honesty doctrine forbids (cf. the SmartyMe teardown). So the property is a **falsifiable test**, not a
badge: add a write command, a REST write method, or a stray `import requests` to a deliverable, and the build
goes red. The guarantee is in the green test, which anyone can read and run.
