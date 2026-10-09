# W59: opt-in legacy-SSH collection mode — design (2026-10-09, revision 2)

Status: **design only.** Nothing in this document is implemented yet. It is committed locally on
`claude/w59-legacy-ssh-design` and has not been pushed. The board row is W59 in `docs/NOW.md`.

**Revision 2 (2026-10-09)** follows two inputs:

- an independent critique of revision 1 (head `3c5cdd8a`), with the verdict "adopt with changes" and no P0;
- the supervisor's owner-delegated engineering decisions on revision 1's open questions.

§11 records those decisions and the two items still pending the owner. §13 maps every critique finding to the section
that applies it. Implementation starts with PR-1 (§10). PR-1 can be built before the owner answers the asyncssh
question, because the fixture is isolated behind a subprocess interface (§8), but it cannot merge until then.

Inputs: three option studies prepared for this row on 2026-10-09:

- **A:** in-repo subclasses of paramiko 5;
- **B:** an asyncssh shim;
- **C:** `ssh.exe`, the paramiko forks, vendoring paramiko 4, and a survey of peer tools.

Every external fact below cites a source from §12. Facts tagged **[verified]** were re-read from the primary source by
the designer on 2026-10-09. Facts tagged **[verified, critique]** were re-read from the primary source by the
independent critic and are cited to the same URLs. All other external facts come from the option studies' cited
sources and still need re-verification in the implementing PR.

---

## 1. Problem and constraints

**The two install forms disagree today.**

- The shipped Atlas lock pins `paramiko==4.0.0` under `netmiko==4.7.0` (`portable/windows-x64-requirements.lock`).
  Paramiko 4.0.0 negotiates SHA-1 key exchange and `ssh-rsa` SHA-1 host-key signatures with **every** device that
  offers nothing better, silently.
- That capability is advisory PYSEC-2026-2858 / CVE-2026-44405 / GHSA-r374-rxx8-8654 [A1 **verified**].
  - Scope: "Paramiko through 4.0.0 … rsakey.py allows the SHA-1 algorithm".
  - Severity: CVSS 3.1 `AV:A/AC:H/PR:N/UI:N/S:C/C:N/I:L/A:N`, which scores Low.
- CI suppresses the advisory, for that lock only, with `--ignore-vuln PYSEC-2026-2858`. The suppression is
  registered in `tests/test_python_dependency_audit_contract.py :: NAMED_PIP_AUDIT_SUPPRESSIONS`.
- A `pip install` of the project resolves `netmiko 4.8.0` with `paramiko 5.0.0` (comment in `.github/workflows/ci.yml`
  above the environment audit). Paramiko 5.0.0 removed SHA-1 key exchange and `ssh-rsa` SHA-1 signatures
  [P1 P2 P6 P7 P9]. A SHA-1-only device is therefore uncollectable from a pip install, but silently collected over
  SHA-1 from Atlas.

**Today's Atlas also performs 1024-bit Diffie-Hellman silently.** The SHA-1 advisory is not the whole exposure:

- The shipped paramiko 4.0.0's stock key-exchange list ends with `diffie-hellman-group-exchange-sha1`,
  `diffie-hellman-group14-sha1` and `diffie-hellman-group1-sha1`. `diffie-hellman-group1-sha1` is the 1024-bit RFC 2409
  Second Oakley Group [P13 **verified**, R4].
- Its group-exchange client sets `min_bits = 1024` [P14 **verified**].
- So a device that offers only `group1-sha1`, or that answers group exchange with a 1024-bit group, is collected today
  over a 1024-bit group. That is this design's own High-severity case (§6.3), and nothing records it.

PR-1 (§10) exists to measure both exposures on real collections before anything else changes. The decision not to
build a 1024-bit tier (§11, decision 1) rests on that evidence.

**What the W59 brief requires:**

1. The default path is paramiko 5 with no SHA-1 in the key-exchange hash or the host-key signature.
2. SHA-1 is reachable only by explicit, recorded operator consent, scoped per device and per run.
3. Every snapshot, workbook and report says when a device was collected over SHA-1, as a security finding about that
   **device**, because the device's own limitation is migration-relevant.
4. The mode works in the frozen Atlas bundle with no host Python and no optional host features.
5. Every test runs on GitHub-hosted runners.

**Repository constraints this design must respect** (read from `origin/main` `6390b66c`):

- **The read-only floor.** The AST write-sink scan in `tests/test_readonly_and_no_egress.py ::
  test_ssh_send_path_has_no_config_or_write_sink` covers every top-level `cisco_toolkit/*.py` file plus the collector.
- **The published claims.** `cisco_toolkit/attestation.py :: CLAIM_IDS` publishes four re-derived claims. The
  no-egress claim lists `paramiko` and `netmiko` in `NETWORK_IMPORTS`. Its only charter exclusion is
  `NO_EGRESS_EXCLUDE = frozenset({"rest_collect.py"})`, and that exclusion is paired with a published floor claim of
  its own, `_claim_rest_get_only`.
- **The live-safety seams.** `tests/test_collect_parse_live_safety.py` monkeypatches `C.ConnectHandler` and
  `C.SSHDetect`.
- **Raw-evidence custody.** `COLLECT_PARSE_V3_23_0.py :: _evidence_records` seals every capture plus the
  `_capture_meta.json` sidecar. Finalization refuses success if any sealed byte changes.
- **The network boundary.** `portable/network_boundary.py` deny-guards `socket.socket.connect` in the frozen
  bundle. Live collection needs `Atlas.exe --allow-live-network`, which is a process boundary, "not a device
  authorization grant".
- **AssessHub has no live-collection path.** `webapp/backend/ingest.py` only ever runs the engine with
  `--no-collect`. Its `_find_collection_root` counts a folder as a device only when it holds `show_*.txt` files, and
  `_load_or_synthesize_devices` writes placeholder device rows with only a hostname and a platform.
- **Collection redaction.** `Atlas.exe --redact-folder … --redact-collection` scrubs captures only. Every other file
  under the collection root is reported as NOT COVERED and left unchanged
  (`webapp/tests/test_atlas_redaction.py :: test_files_the_capture_grammar_cannot_read_are_disclosed_not_dropped`).
- **The test environment floats.** The CI test legs install `.[dev]` unpinned, so they already resolve paramiko 5.0.0.
  The paramiko 4.0.0 behaviour exists only in the frozen bundle.

## 2. Decision

**Adopt option A,** with two elements taken from B and C:

- the two-level consent model from C, with the run level naming its hosts (§5);
- "classify the failure, never retry automatically", from both.

Revision 1 also took a separate 1024-bit tier from B. **Revision 2 drops it** (§11, decision 1).

**Evidence on both paths.** An observation-only `paramiko.Transport` subclass is injected on **both** paths. It
defines no algorithm table and overrides only `_parse_kex_init` and `_parse_newkeys`, each calling `super()` (§4.3).
It is the only way to record what a session actually negotiated, because paramiko discards the key-exchange engine at
`NEWKEYS`, before `connect()` returns (§6.1).

**Default path.** The default path is stock paramiko 5.0.0 with netmiko 4.8.0. No repository code adds, removes or
reorders an algorithm on it.

**Legacy path.** The legacy path is a small first-party module, `cisco_toolkit/legacy_ssh.py`:

- It defines `paramiko.Transport` subclasses whose algorithm tables are **new, frozen mappings**.
- Those tables append the SHA-1 entries **after** every stock algorithm of the same kind.
- It reaches netmiko only per connection, through the collector's one connection factory and netmiko's
  `BaseConnection._get_ssh_client_instance()` hook (§4.2).
- It is excluded from the no-egress walk and **paired with a fifth published attestation claim**,
  `legacy_ssh_confined`, exactly as `rest_collect.py` is paired with `rest_collect_get_only` (§7).

The SSH client picks the first algorithm on its own list that the server also offers (RFC 4253 §7.1 [R1]). An
opted-in device that offers any SHA-2 algorithm therefore still negotiates SHA-2. SHA-1 is used only when the device
offers nothing better, and the session record then proves that fact.

### Why the legacy module stays in `cisco_toolkit/`

The critique offered two ways to stop the no-egress exclusion standing without a published claim: add a claim, or
place the module beside the collector at the repository root. Revision 2 keeps the module in the package and adds the
claim:

- The read-only write-sink scan and the no-LLM claim already walk `cisco_toolkit/` as a class. A root-level module
  would escape both, because each names "the collector entry" as a single module. Fixing that means re-deriving the
  collector-side denominator in three places (the write-sink test, `_claim_no_llm` and packaging), which is the "named
  subset standing in for the class" shape.
- The golden moves in either case: a root-level module would change the no-LLM claim's method and count.
- A published claim states the floor to the client on every run. A test only states it to CI.

The cost is recorded in §10: `CLAIM_IDS` grows from four to five, the attestation block in the golden and the sample
changes, and the LF byte-custody receipt gains one path.

### Why not the others

| Option | Rejected because |
|---|---|
| **B. asyncssh shim** | It adds a runtime dependency with a new licence family (EPL-2.0 OR GPL-2.0-or-later [S4]) to the bundle. On Windows, asyncio connects through `ConnectEx`, bypassing `portable/network_boundary.py`'s `socket.socket.connect` guard, and IP literals skip `getaddrinfo` [S6]. asyncssh probes `ctypes` for host `nettle`/`liboqs` DLLs at import. It needs a ~500-line prompt/echo/ANSI reader whose output shape can drift from netmiko's under the fixed-column parsers. It does not expose the negotiated kex name through public API [S2]. Its defaults still enable `diffie-hellman-group14-sha1` and `ssh-rsa` [S1 **verified**], so a forgotten allowlist re-creates the advisory class with no scanner signal. **Retained as a test-only peer, pending the owner** (§8, §11). |
| **C(1). `ssh.exe` subprocess** | OpenSSH is a Windows optional feature that often cannot be installed offline or under WSUS/GPO [C1]. The inbox 7.7/8.1 clients lack `SSH_ASKPASS_REQUIRE` [C2]. netmiko has no subprocess channel. |
| **C(2). paramiko-insecure fork** | Not on PyPI, apt-only, no Windows wheels, and it depends on a renamed Rust `cryptography` fork [C3]. |
| **C(3). vendored paramiko 4.0.0** | It ships an unmaintained 4.x line without the 5.0 audit fixes. A renamed copy is invisible to pip-audit, which hides a gate. It needs a `sys.meta_path` alias in an isolated child process. |
| **C(4). global `paramiko<5` cap** (orb-agent PR #667, `netmiko[par4]`) [C4 N7] | It enables SHA-1 for every device. That is exactly today's Atlas behaviour, which W59 exists to end. |

## 3. Default path

**Lock (PR-3):** `netmiko==4.8.0` and `paramiko==5.0.0`, hash-pinned in `portable/windows-x64-requirements.lock`.

- netmiko 4.8.0 declares `paramiko>=3.5.1` with no upper cap, plus an optional `par4` extra (`paramiko>=4.0,<5.0`)
  [N2 **verified**]. 4.7.0 capped paramiko below 5.0 [N3].
- netmiko 4.8.0 moved `ruamel.yaml` to the optional `bulk-encrypt` extra [N2 **verified**, N4 **verified**]. Expect
  `ruamel-yaml` to leave the lock.
- paramiko 5.0.0 requires `bcrypt>=3.2`, `cryptography>=3.3`, `invoke>=2.0` and `pynacl>=1.5`, and is a pure
  `py3-none-any` wheel [P11 **verified**]. All four dependencies are already in the lock.
- The exact delta is whatever a hosted `pip-compile` produces: Dependabot's lock update, or a GitHub-hosted
  `pip-compile` run whose output is the artifact. **Never a workstation `pip-compile`**, under the standing
  hosted-only rule. A reviewer re-derives every changed `--hash` from PyPI's JSON API.

**Every install form gets the same floor (PR-3).** "No SHA-1 on the default path, in any install form" needs all of
these, because each install form reads a different file:

- `pyproject.toml`: raise `netmiko>=4.1,<5` to `netmiko>=4.8,<5`, and add an **explicit** `paramiko>=5.0,<6`. This
  mirrors the existing `cryptography` comment: "Keep this an explicit dependency rather than relying on
  netmiko/paramiko to provide a security boundary transitively". **Never** request `netmiko[par4]`.
- `requirements.txt`: it restates `netmiko>=4.1,<5` with no paramiko floor, and CI audits it on its own. It gets the
  same two floors.
- `portable/release_contract.py`: its census pins `netmiko` 4.7.0, `paramiko` 4.0.0 and `ruamel-yaml` 0.19.1. PR-3
  updates the census to match the new lock; the lock alone is not enough.
- **A runtime probe**, because a floor in a manifest does not bind an environment that already has paramiko 4, one
  that installed `netmiko[par4]`, or one installed with `--no-deps`. `ssh_session.permits_sha1(...)` inspects the
  stock `Transport._preferred_kex`, `Transport._key_info` and `RSAKey.HASHES` for SHA-1 names. The collector records
  the result in every session record as `library.default_permits_sha1` (PR-1). After PR-3, a live run in which it is
  true is refused before the first connection, naming the fix. The frozen `--selftest` asserts it is false (PR-3).

**Audit (PR-3):**

- Delete the `"PYSEC-2026-2858"` entry from `NAMED_PIP_AUDIT_SUPPRESSIONS`.
- Delete `--ignore-vuln PYSEC-2026-2858` from the "Audit the shipped Atlas lock" step in `.github/workflows/ci.yml`.
- Delete the two comment blocks that describe the suppression.
- The audit contract already fails an unnamed `--ignore-vuln`. PR-3 adds the converse: a named suppression that no
  step uses also fails. A stale entry then cannot linger.

**No algorithm change on the default path.** From PR-1 the default path is built through the same connection factory
as the legacy path, with the observation-only transport (§4.3). That transport has no algorithm table, so the
negotiation is byte-for-byte what stock paramiko would do. T1 proves it holds no table. No `disabled_algorithms` and
no extra algorithms are added.

**Default-path MACs and ciphers: kept, disclosed per session** (§11, decision 5). Paramiko 5's stock lists still
contain `hmac-sha1`, `hmac-sha1-96`, `hmac-md5`, the `aes*-cbc` ciphers and `3des-cbc` [P1 **verified**].

- The boundary is precisely "no SHA-1 in the key-exchange hash or the host-key signature". These are the
  collision-sensitive uses that the advisory and paramiko 5 removed.
- HMAC-SHA-1 does not rest on collision resistance: "there is no indication that attacks on SHA-1 can be extended to
  HMAC-SHA-1" (RFC 6194 §3.3 [R6 **verified**]).
- Every session records its negotiated MAC and cipher in both directions. The Collection Transport sheet shows them,
  and the snapshot row flags `legacy_mac_or_cipher` (§6.2). They raise no finding.

**One default-path weakness this design discloses rather than changes:**

- Paramiko 5's `KexGexSHA256` *requests* `min_bits = 2048` [P4 **verified**].
- Its client-side check rejects only a server prime below **1024** bits: `if (bitlen < 1024) or (bitlen > 8192)` in
  `_parse_kexdh_gex_group` [P4 **verified**]. Paramiko's own 5.0.0 changelog says the minimum was raised, but the code
  changed only the request [P16, **verified, critique**].
- A non-compliant server can therefore get a 1024-to-2047-bit group accepted on the default path.
- The observation-only transport records the group size from the key-exchange engine before `NEWKEYS` discards it
  (§4.3). The session's status is then `weak_dh`, a High finding (§6.3). Revision 1 claimed `dh_group_bits` made this
  visible "after connect"; that was wrong, because the engine is gone by then.
- The default path does not enforce its own 2048-bit floor: the supervisor's decision keeps the default path stock and
  disclosed. Reporting the changelog/code gap upstream is optional and is a public post, so it needs the owner's
  authority.

## 4. Legacy path

### 4.1 Mechanism (`cisco_toolkit/legacy_ssh.py`, PR-2)

Every class subclasses paramiko 5 and inherits its protocol code. Paramiko 5 reads each table through `self`:

- `self.kex_engine = self._kex_info[agreed_kex[0]](self)`;
- `key = self._key_info[self.host_key_type](Message(host_key))`;
- `_filter_algorithm` filters `self._preferred_<type>` against `disabled_algorithms`;
- `_compute_key` takes `getattr(self.kex_engine, "hash_algo", None)`, falling back to `sha1` [P1 **verified**].

`RSAKey.verify_ssh_sig` returns `False` for any signature algorithm not in `self.HASHES` [P2 **verified**].
`KexGroup14SHA256` and `KexGexSHA256` are standalone classes whose `name`, `hash_algo`, `P`, `G` and `min_bits` are
class attributes. Both use `self.hash_algo` in the exchange hash [P3 **verified**, P4 **verified**]. RSA verification
is keyed by the negotiated host-key type, so only an `ssh-rsa` negotiation can reach the SHA-1 legacy key
[**verified, critique**].

**The module imports paramiko, `hashlib` and `cryptography` only.** It imports no netmiko: the collector owns the
netmiko driver construction for both paths (§4.2), and the legacy module supplies only a transport class. It takes
its algorithm names from `cisco_toolkit.ssh_session`'s vocabulary (§5) and restates none.

| Class | Base | Overrides |
|---|---|---|
| `LegacyKexGroup14SHA1` | `KexGroup14SHA256` | `name = "diffie-hellman-group14-sha1"`, `hash_algo = hashlib.sha1`. The RFC 3526 group 14 2048-bit `P` [R5] is inherited unchanged. |
| `LegacyKexGexSHA1` | `KexGexSHA256` | `name = "diffie-hellman-group-exchange-sha1"`, `hash_algo = hashlib.sha1`, `floor_bits = 2048`, plus the `_parse_kexdh_gex_group` floor check below. |
| `LegacySHA1RSAKey` | `RSAKey` | `HASHES = MappingProxyType({**RSAKey.HASHES, "ssh-rsa": hashes.SHA1, "ssh-rsa-cert-v01@openssh.com": hashes.SHA1})` |
| `LegacySHA1Transport` | `(ObservingTransportMixin, Transport)` | `_preferred_kex = Transport._preferred_kex + ("diffie-hellman-group14-sha1", "diffie-hellman-group-exchange-sha1")`; `_kex_info = MappingProxyType({**Transport._kex_info, ...})`; `_preferred_keys = Transport._preferred_keys + ("ssh-rsa",)`; `_key_info = MappingProxyType({**Transport._key_info, "ssh-rsa": LegacySHA1RSAKey, "ssh-rsa-cert-v01@openssh.com": LegacySHA1RSAKey})`. `_preferred_pubkeys`, ciphers and MACs are untouched. |

**Host-key order, precisely.** `ssh-rsa` follows every stock *plain* host-key algorithm. Paramiko's `preferred_keys`
property then appends a `-cert-v01@openssh.com` variant of each plain name after all of them [P1, P13 **verified**].
So `ssh-rsa` sits before the stock `rsa-sha2-*-cert-v01@openssh.com` entries. Cisco devices do not offer host
certificates, so this has no practical effect, but the design does not claim "after every stock algorithm" for host
keys.

**The GEX floor is checked before anything is sent** (critique P2-3):

- Paramiko 5 accepts any GEX prime of 1024 bits or more, whatever `min_bits` it requested [P4 **verified**].
- Paramiko's own `_parse_kexdh_gex_group` reads the prime and then **sends `KEXDH_GEX_INIT`** in the same method
  [P4 **verified**]. Revision 1's override called `super()` first, so the client had already answered the group before
  the floor check ran.
- `LegacyKexGexSHA1._parse_kexdh_gex_group(self, m)` therefore reads the prime from a **copy** of the message
  (`type(m)(m.asbytes())`) [P15 **verified**], so the original's read position is untouched. When the prime is below
  `floor_bits`, it records the offered size in the session's observation sink and raises `WeakGroupRefused`. Only when
  the prime passes does it call `super()._parse_kexdh_gex_group(m)`.
- `WeakGroupRefused` subclasses paramiko's `IncompatiblePeer` and carries `offered_bits`. The collector's negotiation
  classifier (§4.4) therefore matches it, so the device gets **exactly one attempt** and the status `refused_weak_dh`.
  Revision 1 raised a plain `SSHException`, which netmiko 4.8.0 turns into `NetmikoTimeoutException`
  [N1 **verified, critique**]. The collector would then have retried it `CONNECT_MAX_ATTEMPTS = 3` times and recorded
  it as `unknown`.
- The refusal happens before `KEXDH_GEX_INIT`, `NEWKEYS` and authentication, so no key share and no password crosses a
  group smaller than the floor.
- This is the only paramiko protocol method the module overrides. It adds a check and copies no paramiko code.

**SHA-1 order follows RFC 9142.** That RFC grades `diffie-hellman-group14-sha1` **MAY**, and both
`diffie-hellman-group-exchange-sha1` and `diffie-hellman-group1-sha1` **SHOULD NOT** (Table 12 [R2 **verified**]).
SHA-1 entries therefore follow every stock key-exchange algorithm, with `group14-sha1` before `gex-sha1`.

**Tier 1 only** (§11, decision 1). There is no `legacy-sha1-dh1024` profile, no `group1-sha1` class and no 1024-bit
GEX variant. A tier-2 row may be opened only when PR-1 evidence shows a real device the owner needs collected whose
status is `weak_dh` or `refused_weak_dh`. That row would need its own design delta and owner approval.

**The legacy path refuses to run on paramiko older than 5.** Under paramiko 4, the stock tables already contain SHA-1,
so a legacy profile would add nothing and would blur what consent means. The check is a run-level preflight, made
before any connection:

- it reads `library.default_permits_sha1` (§3);
- when that is true and any device is effectively legacy, the run stops and names the cause: this environment's
  paramiko already permits SHA-1 for every device, and the re-lock is pending.

**Rules that keep the default path closed** (each is enforced by a test in §8):

1. **Never write into an inherited table.** For example, never `Transport._kex_info[...] = ...` or
   `t._kex_info.update(...)`, because that would change the shared class dict for every thread. Every legacy table is
   a new mapping wrapped in `MappingProxyType`. `SecurityOptions` only calls `.keys()` on these tables, which a
   mapping proxy supports [**verified, critique**].
2. **Never subclass by global registration.** `paramiko.key_classes` is an explicit list, not `__subclasses__()`
   [P12]. Defining `LegacySHA1RSAKey` registers nothing.
3. **Import lazily.** `COLLECT_PARSE_V3_23_0.py` imports `cisco_toolkit.legacy_ssh` only inside the connection
   factory, and only for a device whose *effective* profile (§5) is not `default`. A collection run with no
   effective-legacy device never imports it.
4. **No host-key or client-auth change.** `_preferred_pubkeys` stays stock, because the collector authenticates by
   password and never signs with SHA-1. Host-key policy is unchanged; see §7, threat 1.
5. **No retry.** A legacy transport is a superset of the default list, with SHA-2 tried first, so an opted-in device
   needs no retry, and a refusal is never retried (§4.4).

### 4.2 netmiko injection (one patchable factory, both paths)

netmiko 4.8.0 builds its client through `_build_ssh_client()`, which calls `self._get_ssh_client_instance()`; that
method returns `paramiko.SSHClient()`. netmiko then calls `remote_conn_pre.connect(**ssh_connect_params)`, whose keys
do not include `transport_factory` [N1 **verified**]. Neither the IOS nor the NX-OS driver overrides the hook, in
4.7.0 or 4.8.0 [**verified, critique**]. Paramiko's `SSHClient.connect` has accepted `transport_factory` since 2.12
and calls `transport_factory(sock, …)`, defaulting to `Transport` [P5 **verified**]. Paramiko 4.0.0 passes the
GSSAPI arguments too, and 5.0.0 does not, so the factory accepts and forwards keyword arguments unchanged.

`disabled_algorithms` can only remove algorithms, and `sock` is a socket, so neither can add SHA-1 or attach an
observer. The hook is the only per-connection seam. **The collector** (not the legacy module) therefore defines:

- `ObservedTransport = type("ObservedTransport", (ssh_session.ObservingTransportMixin, paramiko.Transport), {})`, the
  default path's transport;
- `_ObservedSSHClient(paramiko.SSHClient)`. Its `connect()` sets `kwargs["transport_factory"]` to a closure that builds
  the transport class and binds the session's observation sink to the new transport instance. It then writes the
  established-session record before returning (§6.1);
- `_ObservedClientMixin`, whose `_get_ssh_client_instance()` returns an `_ObservedSSHClient` for the current
  connection's sink and transport class;
- `_observed_driver_for(platform, transport_cls)`, which returns a class cached per (`cisco_ios` | `cisco_nxos`,
  transport class). The class is `type("Observed" + base.__name__, (_ObservedClientMixin, base), {})`, where
  `base = netmiko.ssh_dispatcher.CLASS_MAPPER[device_type]` [N5].

The collector gains **one** module-level factory, `_open_connection(kwargs, platform, profile, sink)`:

- It selects `ObservedTransport` when `profile == "default"`. Otherwise it imports `cisco_toolkit.legacy_ssh` lazily
  and takes `legacy_ssh.transport_for(profile)`.
- It returns `_observed_driver_for(platform, transport_cls)(**kwargs)`.

`connect_device()` calls only this factory. A structural test asserts that no other site in the collector constructs a
netmiko connection. The live-safety tests patch this one name, so both paths are intercepted (T8).

**The per-connection observation sink** (critique P3). netmiko's `__init__` accepts no extra keyword arguments, so the
sink cannot be passed through the driver constructor. The sink travels in two steps:

1. `_open_connection` puts the sink in a **thread-local** for the duration of the driver constructor and clears it in
   `finally`. `_get_ssh_client_instance()` runs in that same caller thread, reads the thread-local and binds the sink
   to the client it returns.
2. The client's transport-factory closure binds the same sink to the transport **instance**.

Step 2 is required because paramiko runs the key exchange in its own transport thread, not in the caller's thread:
`start_client` starts the thread and re-raises any saved exception in the caller [P1 P13 **verified**]. The overrides
of §4.3 run in that transport thread and write only to the sink bound to their own instance. They never read the
thread-local. A `ThreadPoolExecutor` run therefore cannot mix one device's observations into another's (T2).

**`SSHDetect` constraint.** netmiko's `SSHDetect` builds its own `ConnectHandler(device_type="autodetect")` and
cannot take the hook [N6]. Two consequences:

- A device row whose profile is not `default` **must** resolve to an explicit platform (§5).
- On the default path, a `platform: auto` device's autodetect session is **not observed**. It uses the same client
  tables as the observed main session that follows against the same server, so the main session's record is
  representative. The record says the platform came from autodetect.

### 4.3 The observation-only transport (`ssh_session.ObservingTransportMixin`, PR-1)

Paramiko's `Transport._parse_newkeys` sets `self.local_kex_init = self.remote_kex_init = None`, `self.K = None` and
**`self.kex_engine = None`**. It does so in 4.0.0 and 5.0.0 alike [P1 P13 **verified**]. `connect()` returns only after
key exchange, so reading `kex_engine.name` or a group size "after connect" yields nothing on every established
session. The fixed groups also keep their prime as the class attribute `P`, not `p` [P3 **verified**]. Revision 1's
capture plan could not have worked.

The mixin is duck-typed and imports no network library, so it lives in `cisco_toolkit/ssh_session.py` inside the
no-egress walk. It is composed with `paramiko.Transport` by the collector (default path) and by `legacy_ssh.py`
(legacy path). It overrides exactly two methods, and each calls `super()`:

- **`_parse_kex_init(self, m)`.** Before calling `super()`, it records the server's KEXINIT lists. It parses a
  **copy** of the message (`type(m)(m.asbytes())`) with paramiko's own pure parser, `self._really_parse_kex_init`
  [P1 P13 **verified**]. It also records the client's effective lists (`self.preferred_kex`, `self.preferred_keys`,
  ciphers and MACs). If `super()` raises `IncompatiblePeer`, the server lists are already in the sink, so the refusal
  can be classified from evidence (§4.4).
- **`_parse_newkeys(self, m)`.** Before calling `super()`, on the first key exchange only, it records:
  - the engine's `name`;
  - the group size, from `getattr(eng, "p", None)` for group exchange, else `getattr(eng, "P", None)` for a fixed
    group. It is `null` for elliptic-curve and Curve25519 engines, which have neither;
  - `host_key_type`, the ciphers and MACs in both directions, `agreed_on_strict_kex` and `remote_version`;
  - `len(self.session_id)`.

Both overrides take effect. The handler table binds `self._parse_newkeys` at construction, and `_negotiate_keys`
calls `self._parse_kex_init` [P1 **verified**, **verified, critique**].

**A second witness that needs no hook.** `session_id` is set once in `_set_K_H` and never cleared [P1 P13
**verified**]. Its length gives the exchange-hash family: 20 bytes is SHA-1, 32 is SHA-256, 48 is SHA-384 and 64 is
SHA-512. `host_key_type` also survives `NEWKEYS`. The derivation (§6.2) requires the engine name's hash family and the
`session_id` length to agree; a disagreement is status `unknown` with the reason "inconsistent observation". A broken
observer therefore cannot report `modern`.

**What the mixin must never contain.** No `_preferred_*`, `_*_info` or `HASHES` attribute, no other overridden
method, and no network import. T1 asserts this over the mixin's and `ObservedTransport`'s `__dict__`.

**Private-API coupling.** `_parse_kex_init`, `_parse_newkeys`, `_really_parse_kex_init` and the handler-table binding
are private. They are identical in 4.0.0 and 5.0.0 today. T7 pins them by **behaviour**: after a real handshake
against the fixture, the sink holds the expected records. No test asserts an exact version in the floating
environment (§8).

### 4.4 Failure classification: deterministic refusals are not retried

Paramiko raises `IncompatiblePeer` for six mismatches: protocol version, kex, host key, ciphers, MACs and
compression [P1 **verified**]. netmiko 4.8.0 turns any `SSHException` into `NetmikoTimeoutException`
[N1 **verified, critique**], so the original exception survives only in the `__cause__`/`__context__` chain.

`connect_device()` gains `_classify_connect_failure(exc, sink)`, owned by `ssh_session.classify_failure` and fed
**evidence first**:

1. **The sink's server lists**, when recorded. The first category whose client and server lists share no algorithm is
   the refusal category, in paramiko's own order: kex, host key, cipher, MAC.
2. **The exception chain**, otherwise. `IncompatiblePeer` or `WeakGroupRefused` anywhere in the chain is a negotiation
   refusal; its message names the category.

| Refusal | Condition | Retry |
|---|---|---|
| `refused_weak_dh` | `WeakGroupRefused` (legacy GEX floor, offered bits recorded); or a kex-category refusal where every server-offered kex method is a MODP group below 2048 bits | none: one attempt |
| `refused_legacy_only` | kex or host-key category; server lists recorded; every algorithm the server offered in that category is graded legacy (SHA-1-class) in the vocabulary (§5) | none |
| `refused_unsupported_modern` | kex or host-key category; server lists recorded; at least one offered algorithm is graded modern but this paramiko does not implement it, such as the RFC 8731 name `curve25519-sha256` [R9] (paramiko 5 registers only `curve25519-sha256@libssh.org`) or a post-quantum hybrid | none |
| `refused_cipher_mac` | cipher or MAC category | none |
| `unclassified` | a version or compression refusal; a server list holding a name the vocabulary does not grade; or a refusal with no server lists recorded | none for an `IncompatiblePeer`; see the disconnect race below |

The pseudo-algorithms `ext-info-*` and `kex-strict-*` are ignored when grading a server's kex list.

**The disconnect race** (critique P3). A server that sends `DISCONNECT` before paramiko parses its KEXINIT surfaces as
`EOFError` or `SSHException("Negotiation failed.")`, not `IncompatiblePeer` [P1 **verified**]:

- If the server's KEXINIT arrived before its `DISCONNECT`, paramiko parses it first, because the stream is ordered. The
  sink then holds the server's lists, and the refusal is classified from them as in the table, whatever exception
  surfaces, with no retry.
- If the `DISCONNECT` arrives before any server KEXINIT, there is no evidence of what the server offers. It is a
  connection failure with status `unknown`. The existing same-profile retry applies, because no password is sent before
  key exchange completes, and the profile never changes between attempts.
- Recording the `DISCONNECT` reason code would need a third override, which this design deliberately does not add.
  Field validation (§11) will show whether Cisco servers ever disconnect before sending KEXINIT.

**A refusal is recorded, then the device stops.** `connect_device()` returns immediately, as it already does for an
authentication failure. The record carries an actionable message naming the device row's profile, whether the run
named the device, and how to opt in (for `refused_legacy_only`) or that the collector lacks the device's algorithms
(for `refused_unsupported_modern` and `refused_cipher_mac`).

## 5. Consent and scope (devices.json, CLI, Atlas, AssessHub)

**One vocabulary, one owner.** `cisco_toolkit/ssh_session.py` (PR-1, no network imports) owns:

- `SSH_PROFILES`, the ordered tuple `("default", "legacy-sha1")`;
- the SSH algorithm vocabulary: every algorithm name the design grades (legacy SHA-1-class, MODP group size, modern,
  pseudo-algorithm), and the tuples of names the legacy tier adds. **SSH SHA-1 algorithm literals appear in no other
  source file** (T10, and the published claim in §7);
- the status vocabulary of §6.2.

`legacy_ssh.py` and the collector import these names; nothing restates them.

**Two-level consent** (§11, decision 2). SHA-1 can be negotiated for a device only when **both** of these name it:

| Level | Surface | Rule |
|---|---|---|
| Device | `devices.json` entry `"ssh_profile": "legacy-sha1"` | The value must be a JSON **string** in `SSH_PROFILES`. A missing key means `"default"`. Any other type or value, including `true` or `"yes"`, is a load error naming the entry by `hostname`/`ip` only, as `load_devices` already does. There are no aliases. |
| Run | `cisco-assess … --allow-legacy-ssh legacy-sha1=<host>[,<host>…]` | The profile must be a non-default name in `SSH_PROFILES`, and the list must not be empty. Each item must exactly equal one row's `hostname` or `ip`. An item that matches no row is an error before any connection, so a stale name or a typo fails loudly. The flag may be given once. Combined with `--no-collect` it is an argparse error. |

**Platform check after mapping** (critique P3). `load_devices` silently maps any platform string it does not know to
`auto` (`plat_map.get(plat_raw.strip().lower(), "auto")`). The check therefore runs on the **mapped** value: a row
whose profile is not `default` and whose mapped platform is `auto` is a load error. A legacy row with
`"platform": "asa"` is refused at load time, instead of reaching `SSHDetect` and falling back to `ios`.

**Effective profile.** A device's effective profile is `legacy-sha1` only when its row requests `legacy-sha1` and the
run flag names it. In every other case it is `default`:

- A row that requests `legacy-sha1` in a run that does not name it is collected on the **default** path. This is
  strictly safer, and still useful because many such devices also support SHA-2. If that attempt is refused, the record
  says: "the device row requests legacy-sha1, but this run's `--allow-legacy-ssh` did not name it".
- A device the run flag names whose row does not request `legacy-sha1` is also collected on the default path. It is
  printed and recorded as "named on the run flag, not requested by its row".

**Printed and recorded before connecting** (§11, decision 2). Before the first connection of a live run, the
collector prints the eligible hosts (row requests and run names) and the two mismatch lists, and writes them to the
run manifest. There is no interactive prompt. The run flag can no longer become a standing grant, because it names
hosts and every name must match.

**Why two levels:**

- A row alone can be stale consent left in an old devices.json.
- A run flag alone would be a global cap like C(4). Requiring it to name hosts scopes it to this run's devices.
- With two levels, the operator's per-run decision and the per-device scope are both explicit and both recorded.

**No automatic fallback.**

- There is no "try default, then legacy" loop anywhere. An opted-in device uses its legacy transport once, and that
  transport already prefers SHA-2.
- A device that is not opted in and is refused gets an actionable refusal. It is never retried over SHA-1.
- This is the brief's "never automatic fallback without operator consent". Consent is never inferred from a failure.

**Where consent is recorded:**

- the devices.json bytes, whose SHA-256 is already in the run manifest `inputs` (`devices_file_sha256`);
- a new manifest meta block, `ssh_transport_consent`. On a live run it holds `{run_flag: {profile, hosts_named},
  devices_requesting_legacy, devices_eligible, named_not_requested, requested_not_named, devices_negotiated_sha1}`. On a
  `--no-collect` run it is `{"mode": "offline"}` with every consent field `null`, so a re-analysis never states a
  consent it did not observe (critique P2-8). Hosts are recorded by the device's `hostname` key, the same key every
  other snapshot block uses; `redact_snapshot` keeps hostnames and pseudonymizes IP addresses wherever they appear;
- the per-device session sidecar (§6.1), which is the **only** source of a device's consent fields in the snapshot.

**Atlas.** `Atlas.exe --allow-live-network --run-engine --devices-file devices.json … --allow-legacy-ssh
legacy-sha1=lab-sw1`.

- `--allow-live-network` stays the separate process-level network grant (`webapp/backend/serve.py ::
  LIVE_NETWORK_FLAG`).
- Paramiko connects through `socket.socket.connect`, so the existing boundary applies unchanged to both paths
  [**verified, critique**].
- `portable/README-FIELD.txt` gains a "Legacy SSH devices" section in PR-3.

**AssessHub: no opt-in surface, by design.**

- AssessHub never collects live; it ingests collections with `--no-collect`. It must never write `ssh_profile` into a
  synthesized devices.json, and never pass `--allow-legacy-ssh`. A structural test enforces this: the flag string
  appears in no `webapp/backend` source.
- Its part is ingesting the session records faithfully (§6.4, PR-1) and rendering the disclosure (PR-4).
- If AssessHub ever gains a live-collection job, that is a separate row. Its form must expose the per-device profile
  and a per-run named-host acknowledgment that map one-to-one onto these engine surfaces.

## 6. Evidence, custody and disclosure

### 6.1 Session sidecar: `<device dir>/_ssh_session.json` (schema `ssh_session/1`, PR-1)

The collector writes this sidecar for **every live-attempted device**, on either path, whether it was established or
refused. It is a separate file rather than new keys in `_capture_meta.json`. That sidecar is a closed
`{command: reason}` map, and `compute_capture_integrity_from_paths` looks commands up in it, so a non-command key would
be read as a command.

```json
{
  "schema": "ssh_session/1",
  "outcome": "established",
  "attempts": 1,
  "platform_source": "device_row",
  "consent": {"device_profile": "legacy-sha1", "run_flag_profile": "legacy-sha1", "named_on_run_flag": true,
              "effective_profile": "legacy-sha1"},
  "library": {"paramiko": "5.0.0", "netmiko": "4.8.0", "transport_class": "LegacySHA1Transport",
              "default_permits_sha1": false},
  "client_offered": {"kex": ["...stock order...", "diffie-hellman-group14-sha1", "diffie-hellman-group-exchange-sha1"],
                     "host_key": ["...stock plain names...", "ssh-rsa", "...-cert-v01 variants..."]},
  "server_offered": {"kex": ["diffie-hellman-group14-sha1"], "host_key": ["ssh-rsa"],
                     "cipher_c2s": ["aes128-ctr"], "cipher_s2c": ["aes128-ctr"],
                     "mac_c2s": ["hmac-sha1"], "mac_s2c": ["hmac-sha1"]},
  "negotiated": {"kex": "diffie-hellman-group14-sha1", "kex_hash_bytes": 20, "dh_group_bits": 2048,
                 "host_key_algorithm": "ssh-rsa",
                 "cipher_c2s": "aes128-ctr", "cipher_s2c": "aes128-ctr", "mac_c2s": "hmac-sha1", "mac_s2c": "hmac-sha1",
                 "strict_kex": false, "server_software": "SSH-2.0-Cisco-1.25"},
  "host_key": {"policy": "auto-add", "verified": false},
  "refusal": null
}
```

**How each field is captured:**

- `server_offered`, `client_offered` and `negotiated` come from the observation sink (§4.3), never from the transport
  after `connect()` returns.
- `negotiated.kex_hash_bytes` is `len(session_id)`, the hook-free second witness.
- `negotiated.dh_group_bits` is the engine's `p` (group exchange) or `P` (fixed group) bit length, and `null` for an
  engine that has neither.
- `server_software` keeps only `SSH-protoversion-softwareversion`. The free-text comment after the first space
  (RFC 4253 §4.2 [R1]) is dropped, so it cannot carry identifying text.
- `refusal` carries `{category, classification, detail, offered_group_bits}` from §4.4.
- `outcome` is one of `pending`, `established`, `auth_failed`, `negotiation_refused` or `connect_failed`. `pending`
  means the session record was never completed (below).
- An **authentication failure** keeps its negotiated fields. The sink was bound to the transport, so the record no
  longer depends on netmiko keeping a transport object (`paramiko_cleanup` sets `remote_conn_pre` to `None`). This
  matters: the password crossed that session.

**A closed schema with no client identifier** (critique P2-5). The sidecar holds no hostname, no IP address and no
host-key fingerprint. The device is identified by its folder, which the collection already names. Every string is an
enum value, a version, or an algorithm name matching the RFC 4251 §6 name grammar [R8] (printable US-ASCII, no comma
or whitespace, at most 64 characters). Each list holds at most 64 names. A non-conforming name is dropped and counted,
never stored. The host-key fingerprint is **never written inside the collection tree**; host-key custody belongs to the
W61 follow-up (§7, threat 1).

**When it is written** (critique P2-6). The record is written in up to three steps, so that a device authorized for
SHA-1 can never end up with no record of that authorization, even on an offline re-analysis:

1. **Before connecting:** an exclusive create of the sidecar with `outcome: "pending"`, the consent fields and the
   `library` block. If this write fails, the device is **not connected**, and the failure is written to the run
   manifest. Nothing was negotiated, so its later status is `not_recorded`.
2. **Established sessions:** inside `_ObservedSSHClient.connect()`, after authentication succeeds and before
   `connect()` returns, the pending record is replaced by the full record. netmiko opens the shell and runs its
   session preparation only after that call, so the record exists **before the first command** reaches the device.
   That covers netmiko's own `terminal` commands and the collector's `TERMINAL_SETUP_CMDS`. If the replacement fails,
   the client closes the transport and raises `SessionRecordError`. The device is then not collected and not retried,
   the failure is written to the run manifest, and the sealed sidecar stays `pending`.
3. **Failed sessions:** in `_open_connection`'s failure path, after classification, the pending record is replaced by
   the failure record. If that replacement fails, the sidecar stays `pending` and the failure is written to the run
   manifest.

A sidecar sealed as `pending` is therefore evidence that a session was started and its record never completed. With
an effective legacy profile it derives `legacy_unrecorded`, which is **exposed** (§6.2), on the live run and on every
later re-analysis alike.

**Custody:**

- `_evidence_records` seals the sidecar as `<ssh-session-metadata>`, for **every device in devices.json** that has
  one. That includes refused devices, which never enter `all_cmd_to_files`.
- It is read only through `raw_input_custody`, after binding.
- The sidecar basename joins one owner tuple, `COLLECTION_SIDECAR_BASENAMES`, beside `CAPTURE_META_FILENAME`. Three
  restatements reconcile to it by test:
  - `tools/audit_wheel.py :: _COLLECTION_SIDECAR_BASENAMES`;
  - `tests/test_r8_client_evidence_is_ignored.py :: _COLLECTION_SIDECARS`;
  - the redaction verifier's statement about non-capture files, which deliberately stays independent under the
    existing producer-versus-verifier test (§6.4).

### 6.2 Snapshot block: `snap["ssh_sessions"]` (schema `ssh_session_set/1`, owner `cisco_toolkit.ssh_session`, PR-1)

The block has one row per device. On a live run, that is every device in devices.json. On a `--no-collect` run it is
every device folder, including a folder that holds only a sidecar (§6.4). Each row has these fields:

- `host`;
- `recorded`, which is `false` when there is no sidecar;
- `outcome`;
- `device_profile`, `named_on_run_flag` and `effective_profile`, read **only from the sealed sidecar**, never from the
  current devices.json or command line;
- `negotiated`;
- `sha1: {kex, host_key_signature, mac}`;
- `dh_group_bits` and `dh_below_2048`;
- `legacy_mac_or_cipher`: `hmac-md5`, `hmac-sha1*` or a CBC cipher was negotiated (disclosed, no finding);
- `strict_kex`;
- `host_key_verified: false`;
- `library_permits_sha1`, from the sidecar's `library.default_permits_sha1`;
- `status`, `severity` and `label` (§6.3);
- `evidence`, the sidecar's path relative to the collection root.

**Status** (critique P2-2, P2-6). The first matching row wins.

| `status` | Condition | Finding |
|---|---|---|
| `legacy_unrecorded` | A sealed sidecar still `pending` with an effective legacy profile; or, on a live run, no sidecar while the manifest consent block lists the device as eligible | `exposed`, Medium |
| `not_recorded` | No sidecar otherwise: an offline import, a collection made before W59, or a device not connected because its first record write failed | `verify` |
| `unknown` | Malformed sidecar (the parse error is kept); a `pending` sidecar on the default profile; a negotiation that was never observed (connect failure, unclassified refusal, a disconnect without server lists); an authentication failure with no observed key exchange; or an inconsistent observation (§4.3) | `verify` |
| `weak_dh` | Key exchange observed with a MODP group below 2048 bits, on either path. It takes precedence over `legacy_sha1`, and `sha1.kex` is still recorded | `exposed`, High |
| `legacy_sha1` | Key exchange observed with SHA-1 in the exchange hash (`kex_hash_bytes` 20) or an `ssh-rsa` host-key signature | `exposed`, Medium |
| `modern` | Key exchange observed: SHA-256 or better, agreed by the engine name and `kex_hash_bytes`; host-key signature not `ssh-rsa`; and either a MODP group of at least 2048 bits or a non-MODP exchange | `closed` |
| `refused_weak_dh` | Refusal classified `refused_weak_dh` (§4.4) | `exposed`, High |
| `refused_legacy_only` | Refusal classified `refused_legacy_only` | `exposed`, Medium |
| `refused_unsupported_modern` | Refusal classified `refused_unsupported_modern`: a collector gap, not a device weakness | `verify` |
| `refused_cipher_mac` | Refusal classified `refused_cipher_mac`: a collector gap, not a device weakness | `verify` |

The established statuses apply to both `established` and `auth_failed` outcomes, because the password crossed the
negotiated session either way.

A run summary carries counts per status, the run flag's profile and named hosts, and whether the collection was live
or offline.

**Absence is never health.** `not_recorded`, `unknown` and the two collector-gap refusals are explicit and never
render as `modern`. A device that the run authorized for SHA-1 and whose session record was never completed is
`legacy_unrecorded` and **exposed**, because the design cannot show it was not collected over SHA-1. This avoids the
"absence rendered as health" defect shape that `CLAUDE.md` names.

**SSOT.** `docs/ssot.md` gains a row registering `snap["ssh_sessions"]` / `ssh_session_set/1` with owner
`cisco_toolkit.ssh_session` (PR-1). `WEAKNESS_DECLARATION` gets its own row in PR-2.

### 6.3 The device finding and its label (security, migration-relevant)

`compute_software_risk` gains one surface kind, `ssh-legacy-transport`, in `_SWRISK_SURFACE_KB`.

- Its status is **projected** from `ssh_sessions`, the one owner, by the Finding column of §6.2.
- **Severity** (§11, decision 3): **Medium** for SHA-1 (`legacy_sha1`, `refused_legacy_only` and
  `legacy_unrecorded`), in line with `ssh-v1` and `telnet-vty`; **High** for a DH group below 2048 bits (`weak_dh` and
  `refused_weak_dh`), because a 1024-bit group exposes the password to a precomputation-capable passive adversary
  [O2].
- A finding carries `evidence_verbatim: false`, because the evidence is a session observation, not a config line.
- Its evidence names the negotiated kex and host-key algorithm or the refusal, plus the stronger algorithms the
  collector offered and the device lacked.
- The `why` and `recommendation` text cites RFC 9142 [R2], RFC 8332 for `rsa-sha2-256/512` [R3] and OpenSSH 8.8's
  SHA-1 chosen-prefix cost of under USD 50K [O1 **verified**]. Only `refused_legacy_only` says the device's release
  cannot do SHA-2 SSH. It recommends a management-plane modernization or replacement.
- The exact IOS XE configuration commands are quoted from Cisco's SSHv2 configuration guides [C5 C6] in the
  implementing PR, not invented here.

**The label states two facts: what was negotiated, and under which consent** (critique P2-1). Revision 1 used one label,
"collected over legacy SHA-1 SSH by explicit opt-in". That was false for every paramiko 4 session before PR-3, every
collection by an older Atlas, and every install with paramiko older than 5. `ssh_session.disclosure_sentence(row)` is
the one owner of the wording:

| Status | Effective profile | Label |
|---|---|---|
| `legacy_sha1` | `legacy-sha1` | "collected over SHA-1 SSH by explicit opt-in (device row and run flag); session integrity weakened; host key not verified" |
| `legacy_sha1` | `default` | "negotiated SHA-1 SSH without opt-in (the collector permitted SHA-1: paramiko {version}); session integrity weakened; host key not verified" |
| `weak_dh` | either | "negotiated a {bits}-bit Diffie-Hellman group, below 2048 ({with opt-in / without opt-in}); treat the collection account's password as exposed and rotate it; host key not verified" |
| `legacy_unrecorded` | `legacy-sha1` | "authorized for SHA-1 SSH by its run, but the session record was never completed; treated as collected over SHA-1" |
| `refused_legacy_only` | either | "not collected: the device offers only SHA-1-class SSH ({names}); collecting it requires the legacy-sha1 opt-in" |
| `refused_weak_dh` | either | "not collected: the device offered only a {bits}-bit Diffie-Hellman group, below the 2048-bit floor" |
| `refused_unsupported_modern`, `refused_cipher_mac` | either | "not collected: the device requires {names}, which this collector's SSH library does not implement (a collector gap, not a device weakness)" |
| `unknown`, `not_recorded` | — | "SSH session posture not recorded" |
| `modern` | either | none; the Collection Transport sheet still shows the algorithms and "host key not verified" |

The `paramiko {version}` clause is filled only when `library.default_permits_sha1` is true.

**Report surfaces:**

- A new workbook sheet, **"Collection Transport"**, has one row per `ssh_sessions` device, including the negotiated MAC
  and cipher. It is registered in the sheet registry and `sheet_schema.json`.
- The Software Risk sheet and every deliverable that already folds `software_risk` findings (punch list, explorer,
  AssessHub) carry the finding with no new projection.
- The deliverable families that summarize collection integrity add the row's label for each device that is not
  `modern`. The implementing PR finds every such site with
  `py -3.12 -m graphify affected "compute_capture_integrity_from_paths()"` and lists them in its PR description.

### 6.4 Offline re-analysis, AssessHub ingest and redaction (PR-1)

**Ingest** (critique P2-8):

- `webapp/backend/ingest.py :: _find_collection_root` counts a folder holding `_ssh_session.json` and no `show_*.txt`
  as a device that was **attempted but not collected**. Without this, a refused device's folder disappears, and its
  refusal finding with it.
- `_load_or_synthesize_devices` never writes `ssh_profile`. The snapshot's consent fields come only from the sealed
  sidecar (§6.2), so a synthesized devices.json cannot change them.
- The engine's own `--no-collect` path follows the same rule: a devices.json `ssh_profile` is validated for shape and
  otherwise ignored, and the manifest consent block takes its offline form, `{"mode": "offline"}` with `null`
  fields (§5).

**Redaction** (critique P2-5):

- The fingerprint is never in the collection tree, so `--redact-collection` has nothing to remove.
- The redaction verifier recognizes `_ssh_session.json` by its closed schema (§6.1). A sidecar that validates is
  reported as **covered by schema**: it holds only enums, versions and grammar-conforming algorithm names. A sidecar
  that fails validation stays NOT COVERED, exactly as an unknown file does today.
- Without this, every W59 collection would add one NOT COVERED file per device, and that permanent noise would bury
  the signal the disclosure exists for.

## 7. Security boundaries and threat model

**Boundary.** No SHA-1 in the kex hash or the host-key signature on the default path, in any install form. The proofs
are §8 T1, T3, T10 and T14, plus the runtime probe and the post-PR-3 refusal of §3.

**pip-audit treatment:**

- After PR-3 the lock pins paramiko 5.0.0, so PYSEC-2026-2858 no longer matches, because its last affected version
  is 4.0.0 [A1 **verified**]. The suppression and flag are removed (§3).
- pip-audit matches distributions against advisories [A4]. It cannot see first-party SHA-1 code, and `ruff.toml`
  selects only `E4/E7/E9/F`.
- PR-2 therefore adds a first-party declaration, `legacy_ssh.WEAKNESS_DECLARATION`:
  - CWE-327;
  - the upstream class reference PYSEC-2026-2858;
  - its scope: the `legacy-sha1` profile only;
  - the consent rule;
  - the disclosure fields.
- A row in `docs/ssot.md` registers it.
- A structural scan (§8 T10) and the published claim below keep SSH SHA-1 algorithm identifiers confined. Neither
  flags git-blob SHA-1 identities such as `webapp/backend/observe_ui_projection_contract.py` and
  `portable/release_contract.py`.

**Threat model.** The adversary is adjacent on the management network, the advisory's own `AV:A` vector [A1]. The
collector authenticates with passwords, inside the SSH channel.

1. **Unverified host keys dominate, on both paths, today.**
   - netmiko defaults to `ssh_strict=False`, which installs `paramiko.AutoAddPolicy()` [N1 **verified**]. The
     collector loads no known-hosts file.
   - An adjacent attacker can man-in-the-middle any session, default or legacy, and capture the password. W59 does
     not make this worse.
   - W59 discloses it as `host_key_verified: false` on every row.
   - **W59 records no host-key fingerprint.** Persisting one inside the collection tree would leak it through the
     redacted-collection path, and public scan indexes can link a fingerprint to a network. Host-key custody and
     per-device pinning (`ssh_host_key_sha256` with `RejectPolicy`, from operator-supplied pins) are the follow-up row
     **W61** (§11, decision 6).
2. **SHA-1 exchange hash and `ssh-rsa` signatures.** These weaken server authentication against a collision-capable
   adversary (OpenSSH: chosen-prefix collisions for under USD 50K [O1 **verified**]; RFC 9142 §3.4: SHA-1 methods
   "should be deprecated and phased out" [R2 **verified**]). Given threat 1, the marginal risk is integrity, not
   confidentiality, and it is labelled that way.
3. **1024-bit DH.** A precomputation-capable passive adversary can decrypt the session, including the password [O2].
   RFC 9142 §5.5 calls the 1024-bit group "too small for the symmetric ciphers used in SSH" [R2 **verified**]. W59 adds
   no 1024-bit capability; it refuses one on the legacy path and discloses one wherever it is negotiated (§1, §3).
4. **Downgrade.** Tampering with KEXINIT changes the exchange hash, which the host key signs. Downgrade therefore
   reduces to threat 1. The legacy tables apply only to opted-in devices, so the downgrade surface is bounded by
   consent.
5. **Terrapin.** Legacy devices typically lack strict kex. `strict_kex` is recorded per session [O3].
6. **Scope leakage.** One transport *instance* is created per connection from a frozen class, and each instance writes
   only to its own bound sink (§4.2). A `ThreadPoolExecutor` run mixing default and legacy devices shares no mutable
   state (§8 T1, T2).
7. **Read-only floor unchanged.** Neither `ssh_session.py` nor `legacy_ssh.py` sends a command. The AST write-sink scan
   covers both automatically as top-level `cisco_toolkit` modules.

**No-egress claim and the fifth published claim (PR-2).** `legacy_ssh.py` imports paramiko, so PR-2 adds it to
`NO_EGRESS_EXCLUDE` as the second charter exclusion. Following the `rest_collect.py` precedent, the exclusion is paired
with a published floor claim, **`legacy_ssh_confined`**, appended to `CLAIM_IDS`:

- **Method:** a source/AST scan of `cisco_toolkit/legacy_ssh.py`, re-derived on every run like
  `_claim_rest_get_only`. It holds only when all of these are true:
  - **no command send:** the module calls no netmiko or paramiko channel method (`send_command*`, `send_config*`,
    `write_channel`, `exec_command`, `invoke_shell` and the rest of the write-sink denylist);
  - **no table mutation:** it performs no store into any attribute of a class it imports from paramiko (assignment,
    augmented assignment, subscript store, `setattr`, `.update`/`.setdefault`/`__setitem__`), and every table it
    defines is a tuple or a `MappingProxyType`;
  - **identifier confinement:** across the package walk, SSH SHA-1 algorithm literals appear only in
    `ssh_session.py`'s vocabulary, the legacy-tier name tuples are imported only by `legacy_ssh.py`, and
    `hashes.SHA1` appears only in `legacy_ssh.py`.
- **States:** `HOLDS`, `VIOLATED` naming the offending line, or `NOT_EVALUATED` when the source is absent.
- `ssh_session.py` imports no network library, so it stays inside the no-egress walk and needs no exclusion.

The same PR fixes two existing restatements of the exclusion set:

- `_claim_no_egress`'s HOLDS detail hard-codes "excluded by charter: rest_collect.py";
- `test_no_network_egress_in_analysis_pipeline` hard-codes `exclude={"rest_collect.py"}`.

Both are rewritten to derive from `NO_EGRESS_EXCLUDE`. The resulting attestation golden changes are listed in §10.

## 8. Testing strategy (GitHub-hosted runners only)

**The independent peer is asyncssh, as a test-only dependency, pending the owner** (§11, pending item 2):

- An asyncssh server is a separate SSH implementation, so a mistake that is symmetric on both sides cannot pass. If
  our client hashed with SHA-256 while naming the method SHA-1, the handshake against asyncssh would fail. That
  interoperation is the known-answer test. A paramiko self-peer could not prove it.
- asyncssh registers `diffie-hellman-group14-sha1` enabled by default, and `group1-sha1` and `gex-sha1` disabled but
  selectable [S1 **verified**].
- Algorithm sets are set per connection [S2 S3]. The fixture pins **exact** lists, never defaults.

**Isolation of the fixture** (§11, pending item 2):

- asyncssh is **not** in `[dev]` and never enters the test interpreter. It is pinned with hashes in its own
  requirements file, `tools/requirements-ssh-fixture-test.txt`, beside `tools/requirements-transition-runtime-test.txt`.
  That file gets its own `pip_audit --strict -r` step in `ci.yml`, registered in the audit contract. An inline workflow
  `pip install` would fall under a declared coverage limit of that contract (`NAMED_COVERAGE_LIMITS`).
- Each hosted test leg creates a separate fixture virtualenv from that file. The fixture server
  (`tests/ssh_fixture/server.py`) runs as a **subprocess** from that venv and listens on 127.0.0.1. The tests reach it
  over loopback and import nothing from it. Test modules never import asyncssh, so collection cannot depend on it.
- The interop tests read the fixture interpreter's path from an environment variable. On a hosted runner (`CI` set) a
  missing fixture **fails** the test rather than skipping it, so the interop gate cannot pass vacuously.
- A test asserts that asyncssh is absent from `portable/windows-x64-requirements.lock` and from every
  `pyproject.toml` extra.
- The fixture's fake Cisco shell prints a synthetic prompt (`lab-sw1#`) and canned `show version` text. It contains no
  client data. The fake shell logs when it receives each command, so T16 can check ordering.
- **Non-vacuity.** A raw-socket reader of about 30 lines, in the test interpreter, parses the server's cleartext
  KEXINIT before each test, so "SHA-1-only" is proven, not assumed.
- **If the owner declines asyncssh:** the subprocess interface stays and the server changes. The Linux legs run an
  OpenSSH `sshd` with exact `KexAlgorithms`/`HostKeyAlgorithms` lists as the independent peer. The Windows legs and
  the frozen smokes use a paramiko 4.0.0 server from its own hash-pinned fixture file, restricted with
  `disabled_algorithms`. That server is not independent, which is acceptable for recording, consent and refusal tests
  but not for the known-answer property; that property is then proven on Linux only. Its file needs its own scoped,
  named PYSEC-2026-2858 suppression in the audit contract.

**T5 needs no third-party server** (critique P3). Stock asyncssh cannot serve a group below the client's request: its
server returns the smallest built-in group at or above the client's preferred size, and paramiko asks for 2048
[S8 **verified, critique**]. Patching asyncssh's private `_dh_gex_groups` would couple the test to a private name.
Instead, T5 uses a **raw RFC 4419 responder** of about 60 lines in the test interpreter [R7]. The floor refusal happens
before `KEXDH_GEX_INIT`, so the whole exchange the test needs is cleartext: version strings, KEXINIT,
`KEXDH_GEX_REQUEST` and a `KEXDH_GEX_GROUP` carrying the RFC 2409 1024-bit prime [R4]. No cryptography is needed. The
responder also proves that nothing follows the group message: no `KEXDH_GEX_INIT` and no authentication.

**Versions in the floating environment** (critique P2-7). The test legs install `.[dev]` unpinned, so the next
paramiko 5.0.x or netmiko 4.8.x release would turn an exact-version assertion red on every PR and on `main`. Exact
versions are asserted only:

- against the lock file's text (a static read);
- in the frozen `--selftest`;
- for the hash-pinned fixture file's own pins, which do not float.

In the floating environment, every seam is tested by behaviour.

| ID | PR | Test | Mutation it must catch |
|---|---|---|---|
| T1 | 1, 2 | **Pristine tables, pure observer.** Snapshot `Transport._preferred_kex`, `_kex_info`, `_preferred_keys`, `_key_info`, `_preferred_pubkeys`, `RSAKey.HASHES`, `KexGexSHA256.min_bits` and `KexGroup14SHA256.hash_algo`. Build `ObservedTransport` (PR-1) and each legacy transport (PR-2) over a `socketpair`. Assert every stock table is unchanged in identity and equality. Assert that the `__dict__` of `ObservingTransportMixin` and `ObservedTransport` holds no `_preferred_*`, `_*_info` or `HASHES` key and overrides only the two methods. Assert each legacy table is a `MappingProxyType`. | `Transport._kex_info["diffie-hellman-group14-sha1"] = ...`; a table added to the observer |
| T2 | 2 | **Isolation.** In a fresh interpreter, a default-only collection against the fixture leaves `cisco_toolkit.legacy_ssh` out of `sys.modules`. A mixed run with workers=2 records each device's own transport class, and each sidecar holds only its own session's observations. | Eager import in the collector; a sink read from the thread-local inside the transport thread |
| T3 | 1, 2 | **Interop with a SHA-1-only server** (group14-sha1, `ssh-rsa`). PR-1: the default path (floating paramiko 5) is refused as `refused_legacy_only` with exactly **one** attempt, and the sidecar holds the server's lists. PR-2: `legacy-sha1` establishes with kex `diffie-hellman-group14-sha1`, `kex_hash_bytes` 20, `dh_group_bits` 2048 and host key `ssh-rsa`; status `legacy_sha1`; label "by explicit opt-in". | Classification removed (3 attempts); SHA-1 entries dropped; group size read after `NEWKEYS` (null) |
| T4 | 2 | **Preference.** A server offering SHA-1 and SHA-2 under `legacy-sha1` negotiates SHA-2, and the status is `modern` (opted in, SHA-1 not used). | SHA-1 entries prepended |
| T5 | 2 | **GEX floor.** The raw responder offers a 1024-bit group for `diffie-hellman-group-exchange-sha1` under `legacy-sha1`. Status `refused_weak_dh` with `offered_group_bits` 1024, **exactly one attempt**, and the responder receives no `KEXDH_GEX_INIT` and no authentication. Separately, the fixture's stock 2048-bit group exchange under `legacy-sha1` negotiates gex-sha1 with `dh_group_bits` 2048. | Floor override removed; check placed after `super()` (GEX_INIT sent); a plain `SSHException` (retried 3 times, `unknown`) |
| T6 | 2 | **Consent matrix.** Every (row profile, named on the run flag) pair gives the right effective profile. Load errors for a non-string or unknown profile, and for a legacy profile whose **mapped** platform is `auto` (including `"asa"`). A run-flag host that matches no row is an error before any connection. The eligible and mismatch lists are printed and in the manifest before the first connection. `--no-collect` with `--allow-legacy-ssh` is an error. | Truthiness coercion; platform checked before mapping; unmatched names ignored; flag without a host list accepted |
| T7 | 1 | **netmiko and paramiko seam contract, by behaviour.** A spy proves that `_build_ssh_client` calls `_get_ssh_client_instance`. The observed driver's MRO is (mixin, `CLASS_MAPPER` class). `_ObservedSSHClient.connect` forces `transport_factory`. After a real handshake against the fixture, the sink holds the server lists, the engine name and the group size. The floating environment's stock tables contain no SHA-1 (`permits_sha1` false). Exact versions are asserted only against the lock text. | The hook renamed upstream (simulated); `_parse_newkeys` no longer the handler-table entry (simulated) |
| T8 | 1, 2 | **Live-safety seam.** `_open_connection` is the only constructor of a netmiko connection (AST), and patching it intercepts the default path (PR-1) and the legacy path (PR-2). This extends `test_collect_parse_live_safety.py`. | A direct `ConnectHandler(...)` or `_observed_driver_for(...)(...)` call in `connect_device` |
| T9 | 2 | **Attestation.** `NO_EGRESS_EXCLUDE` contains `legacy_ssh.py`. The no-egress method and detail text, and the doctrine test, derive from the set. `legacy_ssh_confined` HOLDS on the tree, turns `VIOLATED` under each of three planted mutations (a store into a paramiko table, a `send_command` call, a SHA-1 literal in another module), and is `NOT_EVALUATED` without the source. | The hard-coded `rest_collect.py` string restored; the claim reduced to a constant |
| T10 | 1, 2 | **SHA-1 identifier scope.** Among shipped `.py` files (wheel and bundle denominators, collector included), SSH SHA-1 algorithm literals appear only in `ssh_session.py`'s vocabulary; the legacy-tier name tuples are imported only by `legacy_ssh.py`; `hashes.SHA1` appears only in `legacy_ssh.py`; `hashlib.sha1` appears only there and in the declared git-blob identity sites. | `"ssh-rsa"` added to a default-path module |
| T11 | 3 | **Audit contract.** The suppression registry has no entry for this ID and the lock pins paramiko 5.0.0. A named-but-unused suppression fails. | Suppression left behind |
| T12 | 1 | **Offline owner.** Each sidecar maps to the right `ssh_sessions` row for every status in §6.2, including each refusal class, a `pending` record on each profile, and `legacy_unrecorded`. Consent fields come only from the sidecar. A `--no-collect` run's consent block is the offline form with every consent field `null`. A malformed sidecar gives `unknown` with the parse error. An inconsistent observation (engine name SHA-256, `kex_hash_bytes` 20) gives `unknown`. Every label matches §6.3, including the "without opt-in" form. The sidecar's closed schema rejects a hostname, an IP address, a fingerprint and an out-of-grammar name. The banner comment is stripped. | Absent block rendered `modern`; consent read from devices.json; one label for both consent states |
| T13 | 3 | **Frozen bundle, legacy** (hosted `windows-2025` portable job). `Atlas.exe --selftest` adds a `legacy-ssh-backend` check: the frozen app imports `cisco_toolkit.legacy_ssh`, finds the stock tables pristine and `permits_sha1` false, asserts the lock's exact versions, and verifies one embedded SHA-1 PKCS#1 v1.5 RSA signature vector with the bundled `cryptography`. A frozen run with `--allow-legacy-ssh legacy-sha1=lab-sw1` against the loopback fixture records `legacy_sha1` by opt-in. **Negative controls:** without `--allow-live-network`, a legacy-profile device at the non-loopback TEST-NET-1 address `192.0.2.1` is blocked by the network boundary; and T14's default-profile run is refused (below). | `cisco_toolkit.legacy_ssh` missing from `hidden_imports()`; the boundary bypassed on the legacy path |
| T14 | 1, 3 | **Frozen disclosure smoke** (critique P1-2; hosted `windows-2025` portable job). PR-1: Atlas built from the PR-1 tree (still paramiko 4.0.0), default profile, no opt-in, against the SHA-1-only fixture. It must establish and record status `legacy_sha1`, effective profile `default`, `default_permits_sha1` true and the "without opt-in" label. From PR-3 the same smoke is a **negative control**: `refused_legacy_only`, exactly one attempt, `default_permits_sha1` false. | The observer not wired on the default path; PR-1's headline claim never executed |
| T15 | 1 | **Ingest and redaction.** AssessHub ingest of a collection with a sidecar-only folder keeps that device and its refusal finding. The synthesized devices.json carries no `ssh_profile`. `--redact-collection` reports a valid sidecar as covered by schema and a non-conforming one as NOT COVERED. No file in the collection tree contains a host-key fingerprint. | Sidecar-only folder dropped; consent re-derived from the synthesized devices.json |
| T16 | 1, 2 | **Record before the first command.** The fake shell finds the device's completed sidecar already on disk when its first command arrives. A forced failure of the first write leaves the device unconnected (the fixture sees no connection). A forced failure of the post-authentication write closes the session with no command sent, records the failure in the manifest, is not retried, and leaves the sealed sidecar `pending`: status `unknown` on the default profile (PR-1) and `legacy_unrecorded`, exposed, on a legacy profile (PR-2), including after a `--no-collect` re-analysis. | Record written after session preparation; write failure ignored; a `pending` record rendered `not_recorded` |
| T17 | 1 | **Disconnect race.** The raw responder (a) disconnects before sending KEXINIT, giving `unknown` and the existing same-profile retry with no profile change; and (b) sends a KEXINIT with no common kex followed at once by `DISCONNECT`, giving the list-based `refused_legacy_only` with no retry. | Every disconnect retried; every disconnect classified as a refusal; classification by exception type only |

Every interop test runs on both the Linux and Windows hosted legs of the existing matrix, each with its own fixture
venv. The existing required test jobs gain the fixture-venv step, so the required-check contexts do not change. No test
depends on a host crypto policy: the Red Hat OpenSSL-3 SHA-1 policy [C7] is not present on the hosted images, and T13
proves the bundled backend. No test is run locally (standing hosted-only rule).

## 9. Portability

- **Pure Python.** The new code uses `hashlib.sha1` and `cryptography`'s `hashes.SHA1` with PKCS#1 v1.5 verify, both
  already in the bundle (`cryptography==50.0.1`). There are no new runtime dependencies, no native code and no
  optional host features. Option A's study notes that Windows has no OS crypto policy here: the wheel's statically
  bundled OpenSSL decides. cryptography 50.0.1's wheels use OpenSSL 4.0.2, and neither changelog lists a removal of
  SHA-1 RSA verification [**verified, critique**]. T13 proves it on the frozen bundle.
- **PyInstaller.** `cisco_toolkit.ssh_session` is imported eagerly by the collector. `cisco_toolkit.legacy_ssh` is
  imported lazily, so it joins `portable/atlas_bundle.py :: hidden_imports()` with a rationale comment, as
  `cisco_toolkit.manifest` does today. netmiko is already collected whole (`collect_submodules("netmiko")` in
  `portable/atlas.spec`).
- **Network boundary.** No change. Paramiko connects through `socket.socket.connect`, which the runtime hook guards.
  This is the decisive difference from option B.
- **Licensing.** Paramiko is LGPL-2.1 and already in the legal-review queue. The modules subclass it and override
  constants and one checking method. They copy no paramiko code, including paramiko 4.0.0's `kex_group1.py` and its
  test vectors [P10]. The RFC 2409 prime used by T5's responder is a published RFC constant [R4]. The test-only asyncssh
  licence is not distributed.
- **Release coupling.** PR-3, the re-lock, ends Atlas's silent SHA-1. PR-2 must merge before PR-3 so that no Atlas
  release strands SHA-1-only devices without the opt-in. The dependencies in §10 guarantee this.

## 10. Phased implementation plan (PR boundaries and dependencies)

Each PR is its own board row, branches from current `main`, and needs the rule-7 scans, exact-head hosted gates,
independent refutation (Codex) and a supervisor merge with a merge commit.

```
PR-0 design ──► PR-1 disclosure ──► PR-2 legacy transport ──► PR-3 re-lock
                     │
                     ├──► PR-4 AssessHub rendering
                     └──► W61 host-key pinning (separate follow-up row)
External gates: W45 and W54 merged before PR-1's regeneration is dispatched;
the owner's asyncssh answer before PR-1 merges; field validation before README-FIELD says "supported".
```

| PR | Branch (proposed) | Depends on | Scope | Hosted evidence needed |
|---|---|---|---|---|
| **PR-0** | `claude/w59-legacy-ssh-design` | — | This document and the board row | Design refutation (done for revision 1; revision 2 needs a short re-check of §4.2–§4.4 and §6) |
| **PR-1** | `claude/w59-ssh-session-disclosure` | PR-0 merged. Its golden/sample regeneration waits for **W45** (the open engine/sample train) and **W54** (`claude/w31-route-concerns`, the hosted engine-output route fixes) to merge. Merge also waits for the owner's asyncssh answer (§11). | Disclosure on the current stack; works on paramiko 4 and 5. `cisco_toolkit/ssh_session.py` (no network imports): `SSH_PROFILES`, the algorithm and status vocabularies, `ObservingTransportMixin`, the sink, the closed sidecar schema, `classify_failure`, `permits_sha1`, the sidecar-to-row derivation and `disclosure_sentence`. Collector: `ObservedTransport`, `_ObservedSSHClient`, `_open_connection` on the default path, the thread-local hand-off, the record-before-first-command write, refusal classification with no retry, the `default_permits_sha1` probe (recorded only), the manifest `ssh_transport_consent` block (offline form on `--no-collect`), custody sealing including refused devices, and the `COLLECTION_SIDECAR_BASENAMES` owner with its reconciles. Snapshot `ssh_sessions` block, the `ssh-legacy-transport` surface, the Collection Transport sheet and the two-fact labels. Ingest of sidecar-only folders; redaction recognition of the sidecar. SSOT row. Fixture file, fixture venv and audit step. Tests T1 (observer half), T3 (default half), T7, T8 (default half), T10 (vocabulary half), T12, T14, T15, T16 (default half) and T17. The synthetic sample collection gains three sidecars: one `legacy_sha1` on the default profile, one `modern` and one sidecar-only `refused_legacy_only` folder. | Full hosted matrix; the `windows-2025` portable job with T14; the golden and sample regenerated through the hosted engine-output route; then a Codex Atlas Scope re-bind |
| **PR-2** | `claude/w59-legacy-ssh-transport` | PR-1 merged. If PR-1 and PR-2 are both ready before PR-1's regeneration, they may ride one train for a single regeneration and one Scope re-bind (the W45 precedent). | Tier 1 only. `cisco_toolkit/legacy_ssh.py` (paramiko only; frozen tables; `WeakGroupRefused` floor before `KEXDH_GEX_INIT`; `transport_for(profile)`). The `ssh_profile` field with the post-mapping platform check; `--allow-legacy-ssh legacy-sha1=<hosts>` with print-and-record before connecting; the legacy branch of `_open_connection`; the run-level preflight refusal on paramiko < 5 (`default_permits_sha1` true with any effective-legacy device); `NO_EGRESS_EXCLUDE` with derived texts; the fifth published claim `legacy_ssh_confined`; `WEAKNESS_DECLARATION` and its ssot row; the `hidden_imports()` entry. Tests T1 (legacy half), T2, T3 (legacy half), T4, T5, T6, T8 (legacy half), T9, T10 and T16 (legacy half). | Full hosted matrix; golden and sample regenerated through the hosted route (or the shared train); Codex Scope re-bind |
| **PR-3** | `claude/w59-relock-paramiko5` | PR-2 merged | The hosted-generated lock: netmiko 4.8.0, paramiko 5.0.0, `ruamel-yaml` dropped. `pyproject.toml` and `requirements.txt` floors (`netmiko>=4.8,<5`, `paramiko>=5.0,<6`). The `portable/release_contract.py` census. Suppression and flag removal, with the T11 converse check. The live-run refusal when `default_permits_sha1` is true. The `--selftest` probes. T13 with its negative controls; T14 becomes a negative control. README-FIELD "Legacy SSH devices" section. Release note (§11, decision 4). | The `windows-2025` portable build and four-step smoke, plus T13 and T14; a pip-audit run with no suppression. No golden change is expected; the hosted route confirms it. |
| **PR-4** | `claude/w59-assesshub-transport` | PR-1 merged. Independent of PR-2 and PR-3. | AssessHub renders `ssh_sessions` on the device page and the Trust screen through `cisco_toolkit/ui_projection.py`. This needs a schema delta, native re-pin, generated OpenAPI and a hosted dist handoff, coordinated with the rows that hold `ui_projection`. | webapp-ci exact head; hosted dist handoff |

Revision 1's PR-4 (the 1024-bit tier) is dropped by §11, decision 1, and its PR-5 is renumbered PR-4. Host-key pinning
is the follow-up row **W61**, which depends on PR-1. It is not part of W59.

**Persisted outputs each PR is expected to change.** The supervisor runs the hosted regenerations, so each PR records
the expected changes here and in its description:

- **PR-1, golden and sample:**
  - the attestation `no_egress_import_graph` and `no_llm_runtime` module counts, for the new
    `cisco_toolkit/ssh_session.py`;
  - a new top-level `ssh_sessions` block;
  - the manifest's `ssh_transport_consent` in its offline form on the `--no-collect` builds;
  - one `ssh-legacy-transport` software-risk row per device, which is `verify` for every golden device (no sidecars)
    and follows the three synthetic sidecars in the sample. The risk counts and punch-list totals move with them;
  - the new "Collection Transport" sheet and its `sheet_schema.json` entry;
  - in the sample, the three sidecars change the collection's source receipts (hashes and byte counts) in the custody
    and evidence sections. `build_sample.py` must write them with LF bytes, as the W36 fix established.
- **PR-1, other tracked files:** `tests/fixtures/atlas-r2-byte-custody-policy.v1.json`, because the LF scope gains one
  `cisco_toolkit/**/*.py` path. It is recomputed with the pure helpers of `tests/test_transition_schema_assets.py`. If
  the fixture requirements file falls in a declared LF policy domain, the same recomputation covers it.
- **PR-2, golden and sample:** the attestation block gains the `legacy_ssh_confined` claim (four claims become five);
  the no-egress method and detail name both exclusions; the `no_llm_runtime` count grows by one. The
  `no_egress_import_graph` count does not, because `scan_imports` skips an excluded module. **Other tracked files:** the
  LF receipt gains one more path; `tests/test_attestation.py`'s literal `CLAIM_IDS` list changes.
- **PR-3:** no golden or sample change expected. The lock, release census and SBOM change.

**Acceptance gate outside CI.** Before README-FIELD may call legacy mode "supported", it needs operator field
validation against real SHA-1-only IOS, IOS XE and NX-OS devices. Cisco generations differ: for example, IOS XE 17.10
removed `group14-sha1` from its defaults [C5]. Until then every surface says "CI-validated, not field-validated"
(§11, pending item 1).

**Explicitly out of scope:**

- host-key pinning (W61);
- a 1024-bit tier (§11, decision 1);
- DSA/`ssh-dss` devices, which stay uncollectable because paramiko 4.0 already removed DSA [study C];
- ASA and other platforms the collector does not drive;
- collecting `show ip ssh` / `show ssh server` as configuration-surface corroboration. That is a candidate follow-up
  row, because it changes the command registries and the golden;
- any AssessHub live collection.

## 11. Decisions and pending owner items

### Decisions (supervisor, owner-delegated engineering calls, 2026-10-09)

These replace revision 1's open questions 1, 2, 3, 6, 7 and 8.

1. **Tier 1 only.** No `legacy-sha1-dh1024` profile, no `group1-sha1` and no 1024-bit group exchange. A 1024-bit tier
   is reconsidered only if PR-1 evidence shows a real device that needs it (§4.1).
2. **Two-level consent.** The device row's `"ssh_profile": "legacy-sha1"` **and** a per-run
   `--allow-legacy-ssh legacy-sha1=<host list>`. The eligible hosts are printed and recorded before connecting. There
   is no prompt and never an automatic retry (§5).
3. **Severities.** Medium for SHA-1 negotiated (and for a device that offers only SHA-1); High for a DH group below
   2048 bits (§6.3).
4. **Release note.** After the re-lock (PR-3), SHA-1-only devices are refused unless opted in. The release that
   carries PR-3 says so, together with the "CI-validated, not field-validated" status.
5. **Default-path MACs and ciphers.** Paramiko 5's stock `hmac-sha1`, `hmac-md5` and CBC options stay, and are
   disclosed per session (§3, §6.2).
6. **Host-key pinning** becomes its own follow-up row, **W61** (§7, threat 1).

### Pending the owner

1. **Field validation on real SHA-1-only gear.** Who runs it, and when? Until it is done, every release says
   "CI-validated, not field-validated", and README-FIELD does not call legacy mode supported.
2. **asyncssh as a test-only dependency** (EPL-2.0 OR GPL-2.0-or-later [S4]). The design isolates it in a hash-pinned
   test requirements file with its own audit step, run as a subprocess from its own venv (§8). If the owner declines,
   the subprocess interface is kept and the peer changes: an OpenSSH Linux fixture, with the Windows legs as described
   in §8. PR-1 cannot merge until this is answered, because it adds the fixture file.

An upstream report of paramiko 5's GEX floor gap (§3) is optional. It is a public post, so it needs the owner's
authority; nothing in W59 depends on it.

## 12. Sources

Paramiko:

- [P1] paramiko 5.0.0 `transport.py`: https://github.com/paramiko/paramiko/blob/5.0.0/paramiko/transport.py
- [P2] paramiko 5.0.0 `rsakey.py`: https://github.com/paramiko/paramiko/blob/5.0.0/paramiko/rsakey.py
- [P3] paramiko 5.0.0 `kex_group14.py`: https://github.com/paramiko/paramiko/blob/5.0.0/paramiko/kex_group14.py
- [P4] paramiko 5.0.0 `kex_gex.py`: https://github.com/paramiko/paramiko/blob/5.0.0/paramiko/kex_gex.py
- [P5] paramiko 5.0.0 `client.py`: https://github.com/paramiko/paramiko/blob/5.0.0/paramiko/client.py
- [P6] paramiko commit a448945 (`ssh-rsa` SHA-1 removed): https://github.com/paramiko/paramiko/commit/a4489456b6f65281e172380cc4826cee5e851dbb
- [P7] paramiko commit 9bf5fca (SHA-1 kex removed): https://github.com/paramiko/paramiko/commit/9bf5fcae57e6ca995275037eea9d6305f70d7cdb
- [P8] paramiko commit 6fa1556 (GEX `min_bits` 2048): https://github.com/paramiko/paramiko/commit/6fa1556
- [P9] paramiko changelog: https://www.paramiko.org/changelog.html
- [P10] paramiko 4.0.0 `kex_group1.py` (reference only; not copied): https://github.com/paramiko/paramiko/blob/4.0.0/paramiko/kex_group1.py
- [P11] PyPI paramiko 5.0.0 metadata: https://pypi.org/pypi/paramiko/5.0.0/json
- [P12] paramiko 5.0.0 `__init__.py` (`key_classes`): https://github.com/paramiko/paramiko/blob/5.0.0/paramiko/__init__.py
- [P13] paramiko 4.0.0 `transport.py` (stock kex list with `group1-sha1`; `_parse_newkeys`; `_really_parse_kex_init`; `start_client`; `preferred_keys`): https://github.com/paramiko/paramiko/blob/4.0.0/paramiko/transport.py
- [P14] paramiko 4.0.0 `kex_gex.py` (`min_bits = 1024`): https://github.com/paramiko/paramiko/blob/4.0.0/paramiko/kex_gex.py
- [P15] paramiko 5.0.0 `message.py` (`asbytes`, `rewind`): https://github.com/paramiko/paramiko/blob/5.0.0/paramiko/message.py
- [P16] paramiko 5.0.0 changelog source: https://raw.githubusercontent.com/paramiko/paramiko/5.0.0/sites/www/changelog.rst

netmiko:

- [N1] netmiko v4.8.0 `base_connection.py`: https://github.com/ktbyers/netmiko/blob/v4.8.0/netmiko/base_connection.py
- [N2] netmiko v4.8.0 `pyproject.toml`: https://github.com/ktbyers/netmiko/blob/v4.8.0/pyproject.toml
- [N3] netmiko v4.7.0 `pyproject.toml`: https://github.com/ktbyers/netmiko/blob/v4.7.0/pyproject.toml
- [N4] netmiko v4.8.0 release notes: https://github.com/ktbyers/netmiko/releases/tag/v4.8.0
- [N5] netmiko v4.8.0 `ssh_dispatcher.py`: https://github.com/ktbyers/netmiko/blob/v4.8.0/netmiko/ssh_dispatcher.py
- [N6] netmiko v4.8.0 `ssh_autodetect.py`: https://github.com/ktbyers/netmiko/blob/v4.8.0/netmiko/ssh_autodetect.py
- [N7] netmiko issue #3892 (`netmiko[par4]` as the near-term workaround): https://github.com/ktbyers/netmiko/issues/3892
- [N8] netmiko v4.8.0 IOS and NX-OS drivers (no hook override): https://github.com/ktbyers/netmiko/blob/v4.8.0/netmiko/cisco/cisco_ios.py, https://github.com/ktbyers/netmiko/blob/v4.8.0/netmiko/cisco/cisco_nxos.py

Advisories and tooling:

- [A1] OSV PYSEC-2026-2858: https://api.osv.dev/v1/vulns/PYSEC-2026-2858
- [A2] GHSA-r374-rxx8-8654: https://github.com/advisories/GHSA-r374-rxx8-8654
- [A3] oss-security disclosure: https://seclists.org/oss-sec/2026/q2/414
- [A4] pip-audit: https://pypi.org/project/pip-audit/

RFCs:

- [R1] RFC 4253 §4.2, §7.1, §8.1: https://www.rfc-editor.org/rfc/rfc4253
- [R2] RFC 9142 §1.1, §3.4, §5.5, Table 12: https://www.rfc-editor.org/rfc/rfc9142
- [R3] RFC 8332: https://www.rfc-editor.org/rfc/rfc8332
- [R4] RFC 2409 §6.2: https://www.rfc-editor.org/rfc/rfc2409
- [R5] RFC 3526 §3: https://www.rfc-editor.org/rfc/rfc3526
- [R6] RFC 6194 §3.3: https://www.rfc-editor.org/rfc/rfc6194
- [R7] RFC 4419 (group exchange): https://www.rfc-editor.org/rfc/rfc4419
- [R8] RFC 4251 §6 (algorithm naming): https://www.rfc-editor.org/rfc/rfc4251
- [R9] RFC 8731 (`curve25519-sha256`): https://www.rfc-editor.org/rfc/rfc8731

Attacks and SSH implementations:

- [O1] OpenSSH 8.8 release notes: https://www.openssh.org/txt/release-8.8
- [O2] Logjam, "Imperfect Forward Secrecy": https://weakdh.org/
- [O3] Terrapin: https://terrapin-attack.com/

asyncssh and Python:

- [S1] asyncssh `kex_dh.py`: https://raw.githubusercontent.com/ronf/asyncssh/develop/asyncssh/kex_dh.py
- [S2] asyncssh `connection.py`: https://raw.githubusercontent.com/ronf/asyncssh/develop/asyncssh/connection.py
- [S3] asyncssh API: https://asyncssh.readthedocs.io/en/latest/api.html
- [S4] asyncssh licence (`pyproject.toml`): https://raw.githubusercontent.com/ronf/asyncssh/develop/pyproject.toml; EPL-2.0 text: https://www.eclipse.org/legal/epl-2.0/
- [S5] asyncssh 2.24.1 on PyPI: https://pypi.org/project/asyncssh/2.24.1/
- [S6] CPython 3.12 asyncio: https://github.com/python/cpython/blob/3.12/Lib/asyncio/windows_events.py, https://github.com/python/cpython/blob/3.12/Lib/asyncio/proactor_events.py, https://github.com/python/cpython/blob/3.12/Lib/asyncio/base_events.py
- [S7] scrapli 2026.10.8 files (no Windows wheel): https://pypi.org/project/scrapli/2026.10.8/#files
- [S8] asyncssh v2.24.1 `kex_dh.py` (server group selection): https://github.com/ronf/asyncssh/blob/v2.24.1/asyncssh/kex_dh.py
- [S9] PyPI asyncssh 2.24.1 metadata (licence, `cryptography>=48.0.1`): https://pypi.org/pypi/asyncssh/2.24.1/json

Other routes, peer tools and Cisco:

- [C1] Microsoft OpenSSH overview: https://learn.microsoft.com/en-us/windows-server/administration/openssh/openssh-overview, and https://learn.microsoft.com/en-us/troubleshoot/windows-server/system-management-components/cant-install-openssh-features
- [C2] Win32-OpenSSH issues: https://github.com/PowerShell/Win32-OpenSSH/issues/1726, https://github.com/PowerShell/Win32-OpenSSH/issues/2115
- [C3] paramiko-insecure: https://github.com/mithro/paramiko-insecure
- [C4] orb-agent PR #667: https://github.com/netboxlabs/orb-agent/pull/667
- [C5] Cisco Catalyst 9200 IOS XE 17.15 SSHv2 configuration guide: https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9200/software/release/17-15/configuration_guide/sec/b_1715_sec_9200_cg/secure_shell_version_2_support.html
- [C6] Cisco IOS 15-E SSHv2 configuration guide: https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/sec_usr_ssh/configuration/15-e/sec-usr-ssh-15-e-book/sec-secure-shell-v2.html
- [C7] Red Hat OpenSSL 3 SHA-1 policy: https://bugzilla.redhat.com/show_bug.cgi?id=2060343
- [C8] APNIC, SSH key-exchange failures with legacy devices: https://blog.apnic.net/2026/07/03/ssh-key-exchange-failures-when-managing-legacy-network-devices/

Repository facts were read on `origin/main` `6390b66c`:

- `COLLECT_PARSE_V3_23_0.py`: `connect_device`, `CONNECT_MAX_ATTEMPTS`, `_is_auth_error`, `autodetect_platform`,
  `load_devices` (including `plat_map`), `collect`, `_evidence_records` and `collect_one`;
- `cisco_toolkit/capture_integrity.py`;
- `cisco_toolkit/attestation.py`: `CLAIM_IDS`, `NO_EGRESS_EXCLUDE`, `_claim_no_egress`, `_claim_rest_get_only`,
  `_claim_no_llm` and `compute_attestation`;
- `cisco_toolkit/analyze.py :: compute_software_risk`;
- `cisco_toolkit/html.py :: redact_snapshot`;
- `tests/test_readonly_and_no_egress.py`, `tests/test_collect_parse_live_safety.py`,
  `tests/test_python_dependency_audit_contract.py`, `tests/test_attestation.py` and
  `tests/fixtures/atlas-r2-byte-custody-policy.v1.json`;
- `webapp/tests/test_atlas_redaction.py`;
- `.github/workflows/ci.yml`;
- `requirements.txt`, `portable/release_contract.py`, `portable/windows-x64-requirements.lock`,
  `portable/network_boundary.py`, `portable/atlas.spec` and `portable/atlas_bundle.py`;
- `webapp/backend/serve.py` and `webapp/backend/ingest.py` (`_find_collection_root`, `_load_or_synthesize_devices`);
- `pyproject.toml`.

## 13. Critique dispositions (revision 2)

The independent critique of revision 1 found no P0. Every finding is applied:

| Finding | Summary | Applied in |
|---|---|---|
| P1-1 | The session record could not be read after connect: `_parse_newkeys` clears the engine; fixed groups keep `P` | §4.3 (observer on both paths, `session_id` witness, `P`/`p`), §6.1, §3, T1, T3, T7, T12; the NOW.md handoff line is corrected |
| P1-2 | PR-1's headline promise was never executed by a gate | T14 (PR-1 frozen smoke on paramiko 4; negative control from PR-3) |
| P2-1 | One opt-in label was false for sessions without opt-in | §6.3 two-fact labels, T12 |
| P2-2 | `refused_no_modern` inferred a weakness from absence | §4.4 classification from recorded server lists, §6.2 statuses, T3, T12 |
| P2-3 | The GEX floor ran after `KEXDH_GEX_INIT`, as a plain `SSHException`, and was retried three times | §4.1 (`WeakGroupRefused` before sending, one attempt), T5 |
| P2-4 | "Any install form" was not enforced | §3 (`requirements.txt`, `release_contract.py` census, runtime probe, post-PR-3 refusal), T13 |
| P2-5 | The fingerprint leaked through the redacted-collection path | §6.1 (no fingerprint in the tree; closed schema), §6.4 redaction, §7 threat 1 (W61), T15 |
| P2-6 | A missing record for a legacy device fell back to `verify` | §6.1 write timing (a `pending` record before connecting, completed before the first command), §6.2 `legacy_unrecorded` → exposed, also on re-analysis, T16 |
| P2-7 | Exact-version assertions in the floating environment | §8 (lock text and frozen self-test only), T7 |
| P2-8 | AssessHub lost refused devices and the consent fields | §5 (offline consent block), §6.2, §6.4 ingest, T15 |
| P2-9 | Today's 1024-bit exposure was understated | §1 |
| P3 | asyncssh GEX fixture approach | §8 (raw RFC 4419 responder; no private asyncssh name) |
| P3 | Host-key order wording | §4.1 |
| P3 | The no-egress exclusion had no published claim | §2, §7 (`legacy_ssh_confined`), T9 |
| P3 | Platform check before mapping | §5, T6 |
| P3 | The run flag could become a standing grant | §5 (named hosts, every name must match, printed and recorded), T6 |
| P3 | The per-connection observation sink was unspecified | §4.2 (thread-local in the caller, bound to the transport instance), T2 |
| P3 | T13 lacked negative controls | T13, T14 |
| P3 | asyncssh supply chain | §8 (hash-pinned file, own audit step, subprocess venv) |
| P3 | No SSOT row for `ssh_sessions` | §6.2 |
| P3 | Disconnect race | §4.4, T17 |
