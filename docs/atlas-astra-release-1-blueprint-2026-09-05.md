# Atlas + GPT-6 Astra: final Release-1 operating blueprint

Status: product and operating blueprint. It defines boundaries and evidence requirements; it does
not assert that external signing, physical qualification, human review, publication, or Astra
entitlement exists.

## Executive decision

Ship Atlas Release 1 as a deterministic, local, Windows x64 portable application. Keep GPT-6
Astra outside the field evidence plane: use it as an engineering/review conductor when it becomes
available on the selected Codex or API surface. Do not put a model, API key, cloud dependency,
Graphify, Obsidian, raw capture, or personal-vault content inside `Atlas.exe`.

The first product is deliberately bounded:

- one-folder `Atlas.exe` plus a local loopback AssessHub UI;
- saved-capture assessment by default and explicitly enabled, separately authorized read-only live
  collection;
- the registry-owned deliverable family, honest coverage, visible approval posture, redaction, and
  manifest verification;
- an operator-initiated, whole-tree staged update with retained client `data\` and explicit rollback;
- proprietary field-pilot packaging through one exact collaborator-visible draft GitHub candidate;
  the source repository itself remains intentionally public.

Release 2/3 transition proofs, autonomous changes, SaaS, and a cloud model companion are not
Release-1 scope. Their absence must not be described as a defect in the bounded product, and their
existence elsewhere must not be used to promote Release 1.

## Three-plane architecture

### Plane A - offline field product

`Atlas.exe` is the only executable entry. The frozen process serves the browser UI on numeric
loopback and dispatches the engine through the same executable. Non-loopback Python socket paths
used by the product are denied unless the operator restarts with `--allow-live-network`; a physically
disconnected NIC and managed host policy remain the hard offline controls.

The application tree is immutable between releases. `Atlas\data\` is the only client-writable
namespace. Update staging, database migration rehearsal, activation, recovery, and rollback all run
on the destination volume. A release ZIP carries an exact runtime-member manifest, internal and
outer checksums, file-plus-dependency CycloneDX SBOM, embedded third-party license evidence,
toolchain receipt, signing posture, qualification receipt, and build-time Git source identity.
Those unkeyed records prove internal consistency only; verified GitHub attestations and Authenticode
provide separate authenticated statements.

### Plane B - engineering and release control

Git and tracked owner documents hold durable truth. Graphify is a generated navigation index over an
exact tree. A separately opened generated Obsidian vault is a disposable browse projection. Codex,
Claude, ChatGPT, and future Astra sessions propose, implement, challenge, and summarize; none of
them is an approver, signer, device operator, field tester, or source of release authority.

Each consequential change follows this compact loop:

1. bind the exact current source, owner, and acceptance denominator;
2. preserve unrelated WIP and negative evidence;
3. implement in one reviewable source branch;
4. run focused mutation/refusal tests, then complete gates;
5. use independent read-only product, security, and regression challenge passes;
6. merge only the exact reviewed head and label an administrator exception as technical integration;
7. rebuild from fresh exact main, independently reopen every artifact, and stop at the next real
   human or physical gate.

OpenAI's current model page identifies the API model as `gpt-6-astra`, with structured outputs,
function calling, computer use, web/file search, skills, MCP, and tool search through the Responses
API. The current model guide specifically recommends auditing accessible skills/instruction files,
explicitly prompting for desired delegation, and calibrating test breadth. Those are design inputs,
not an entitlement claim: this Codex host's selectable-model list still does not expose Astra, so
the workflow remains executable with its current model until access is actually observed. See the
[official model page](https://developers.openai.com/api/docs/models/gpt-6-astra) and
[official Astra model guidance](https://developers.openai.com/api/docs/guides/latest-model).

### Plane C - optional Astra companion after Release 1

The companion is a separate project and deployment. It may proceed only after a tracked
`cloud_safe_bundle/1` contract proves that the upload contains no raw captures, configuration,
hostnames, descriptions, addresses, MACs, serials, credentials, vault pages, document binaries, or
unbounded free-form evidence. Current field redaction intentionally retains hostnames and
descriptions, so it is not that contract.

The companion may expose only bounded read-only functions such as `get_release_status`,
`get_snapshot_summary`, `get_finding_evidence`, `query_graph`, `verify_manifest`, and
`draft_next_gate`. Model output uses a closed `atlas_advisory/1` schema, remains advisory, and is
locally revalidated before a human can apply it. Data-retention/ZDR eligibility, account entitlement,
prompt-injection resistance, cost ceilings, evals, audit retention, and an offline fallback are
separate launch gates.

## Authority map

| Question | Owner | What must never substitute |
|---|---|---|
| What Atlas computes | current code, tests, runtime evidence, `docs/ssot.md` owners | Graphify counts, a model summary, or an old plan |
| What ships | portable member manifest plus exact ZIP digest | a directory listing or prior candidate |
| Where bytes came from | exact source identity plus externally verified GitHub attestation | self-authored provenance alone |
| Who published the executable | trusted Authenticode chain and RFC3161 timestamp | a package hash or self-signed test |
| Whether it runs under policy | recorded Smart App Control/AppLocker/App Control result on the target | valid signature alone |
| Whether USB/update/recovery works | completed physical field packet on the exact candidate | CI or simulated drive letters |
| Whether a deliverable is approved | engagement-owned human gate ledger | generation, draft text, agent review, or owner merge |
| Whether the product is accepted | named field operator/owner acceptance for the bounded pilot | download count, green checks, or a draft release |

## Release-1 gate sequence

1. **Source custody** - reconcile protected WIP by path and preserve its original refs/checkout.
2. **Product contracts** - agent templates remain invalid placeholders until real authority and
   execution evidence are supplied; gated Word output carries visible and machine-readable
   `UNAPPROVED DRAFT` state.
3. **Portable build** - exact pinned Windows toolchain; real PyInstaller build; populated PE policy
   metadata; embedded CPython/PyInstaller/runtime licenses; no host-installed Python and no
   OpenAI/Graphify/Obsidian runtime dependency.
4. **Automated qualification** - frozen smoke, numeric loopback, sanitized Python path, alternate
   drive letters, Unicode profile/install path, same-version and v3.32.1 database-copy migration,
   canary-bearing redaction, exact manifest, update/recovery/rollback state machine.
5. **Supply chain** - closed release-set denominator, exact byte manifests, runtime dependency and
   license inventory, draft-only status, GitHub provenance/SBOM attestations verified before attach.
6. **Human and physical qualification** - production signing identity, managed policy, clean
   Python-absent/NIC-disconnected host, physical USB/read-only/full/interruption tests, BitLocker To
   Go recovery, display scaling, AAA rotation, peer review, and operator acceptance.
7. **Publication** - the v1 candidate and its machine receipts are permanently draft-only; no
   supported public-promotion lane exists. After every applicable field is non-null and passing, a
   separate reviewed contract must bind the unchanged signed ZIP to an externally custodied human
   promotion decision and a write-separated workflow. Until that exists, nobody changes the draft
   status or manually uploads a signed set. A rebuilt ZIP is a new candidate and invalidates prior
   physical/signing evidence.

## Knowledge-system placement

- GitHub/Git: source, review, immutable release assets, authenticated workflow statements.
- `docs/ssot.md`: fact-owner routing; owner code remains authoritative.
- Graphify: exact-tree relationship/navigation projection, refreshed only through its guarded
  workflow.
- Generated Obsidian vault: separate, reproducible, relocatable browse view; never merged into the
  personal vault by automation.
- Personal Obsidian vault: private working knowledge, independently backed up, never a release owner.
- Model context: smallest source-bound slices required for the task; no whole-repository or raw-vault
  upload merely because a long context is available.

## Field-pilot learning loop

Run one bounded pilot before expanding features. Capture task completion, correction/retry counts,
document omissions, redaction refusals, update/rollback time, managed-policy friction, and operator
decisions. Preserve all failures and abstentions. Convert observed product gaps into tracked owner
changes; do not turn a field anecdote into a general support or GA claim.

Release 1 succeeds when an authorized engineer can take one exact candidate to a managed offline
Windows host, assess saved evidence, produce and verify the bounded deliverable family, preserve
client data through a rehearsed update/rollback, and have a human accept the result. Astra's value is
making that evidence loop faster and more adversarial—not becoming another authority or another
copy of the client data.
