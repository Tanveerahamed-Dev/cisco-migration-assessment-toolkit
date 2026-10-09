# W55 supply-chain and CI hygiene train (2026-10-09)

Branch `claude/supply-chain-hygiene`, cut from `origin/main` `6390b66c` (#629). Items (b) to (e) are four
independent fixes, one commit each. Item (a) is deferred to an owner decision and changes no file except this
record. No local test, build, engine, npm or browser run took place (owner GitHub-only rule). The local checks
were static: `py_compile`, `ruff`, AST scans, YAML parsing of the edited workflow and Dependabot files, and
read-only lookups of primary sources (the PyPI JSON API, the OSV API, upstream GitHub releases, pull requests and
changelogs, the CodeQL alert API, and the job logs of the latest `main` CI run). The hosted gates decide.

## (a) PYSEC-2026-2858: deferred to an owner decision (legacy SSH reach vs LOW-severity SHA-1 advisory)

**Status: deferred, nothing changed.** This branch leaves the advisory exactly as `origin/main` `6390b66c`
carries it. `portable/windows-x64-requirements.lock` still pins netmiko 4.7.0 and paramiko 4.0.0. The
shipped-lock audit step in `.github/workflows/ci.yml` still runs with the named `--ignore-vuln PYSEC-2026-2858`,
and its `NAMED_PIP_AUDIT_SUPPRESSIONS` entry in `tests/test_python_dependency_audit_contract.py` stays. All three
files are byte-identical to `main`.

A re-lock to netmiko 4.8.0 / paramiko 5.0.0 was prepared as local commit `b8def26b`. It was dropped from this
branch by supervisor decision, pending the owner. It closes a LOW-severity advisory, but it removes collection
reach on legacy gear, and legacy gear is the population a brownfield migration tool is built for. The commit was
never pushed. It is kept on this host only, at `refs/preserved/w55-paramiko5-relock-b8def26b`.

**The advisory.** PYSEC-2026-2858 (aliases CVE-2026-44405, GHSA-r374-rxx8-8654): paramiko's `rsakey.py` allows
SHA-1. OSV records every release up to and including 4.0.0 as affected (`last_affected: 4.0.0`). Its CVSS v3
vector is `AV:A/AC:H/PR:N/UI:N/S:C/C:N/I:L/A:N`: adjacent network, high complexity, low integrity impact only.
That vector computes to a base score of 3.4, which is Low (computed here from the vector). On 2026-10-09 OSV
reported no advisory for paramiko 5.0.0, netmiko 4.8.0 or netmiko 4.7.0.

**Why the stick is still on paramiko 4.0.0.** netmiko 4.7.0 requires `paramiko<5.0,>=3.5.0`. netmiko 4.8.0
(2026-09-21) requires `paramiko>=3.5.1` and moves that cap into an opt-in `par4` extra (`paramiko<5.0,>=4.0`).
A re-lock is therefore possible, but it is a choice. `pyproject.toml` and `requirements.txt` declare
`netmiko>=4.1,<5`, so a floating (non-Atlas) install already resolves netmiko 4.8.0 / paramiko 5.0.0 and already
lacks SHA-1. The CI installed-environment audit needs no suppression for that reason. Today only the Atlas stick
keeps legacy SSH reach.

**What paramiko 5.0.0 removes** ([changelog](https://www.paramiko.org/changelog.html), 5.0.0, 2026-05-09):

- SHA-1 key exchange: `diffie-hellman-group1-sha1`, `diffie-hellman-group14-sha1` and
  `diffie-hellman-group-exchange-sha1`;
- RSA signatures with SHA-1 (`ssh-rsa` as a signature algorithm), in upstream commit
  [`a4489456`](https://github.com/paramiko/paramiko/commit/a4489456b6f65281e172380cc4826cee5e851dbb)
  ("Remove SHA1 support from RSA key handling");
- 1024-bit moduli for `diffie-hellman-group-exchange-sha256`: the minimum rises to 2048 bits (RFC 9142);
- GSSAPI support.

The changelog marks the first two as backwards incompatible for systems that cannot use the SHA-2 forms.

**Collection reach at stake.** The collector reaches devices only through netmiko (`ConnectHandler`,
`SSHDetect`). No module imports paramiko directly. With paramiko 5.0.0, two device shapes fail before login:

| Device offers | paramiko 5.0.0 error |
|---|---|
| only SHA-1 key exchange | `Incompatible ssh peer (no acceptable kex algorithm)` |
| SHA-2 key exchange, but only an SHA-1 `ssh-rsa` host-key signature | `Incompatible ssh peer (no acceptable host key)` |

`connect_device` (`COLLECT_PARSE_V3_23_0.py`) treats either error as a non-authentication connection failure.
It retries `CONNECT_MAX_ATTEMPTS` (3) times, logs `[FAIL] Connection failed to <host> after 3 attempt(s): <error>`
and skips the device. The gap is therefore visible in the run log, not silent. Older Cisco IOS trains are the
expected population. That expectation comes from the upstream reports below; it is not a field measurement.

**Precedent and upstream guidance.**

- netboxlabs/orb-agent [PR #667](https://github.com/netboxlabs/orb-agent/pull/667) (merged 2026-09-30) caps its
  device-discovery package at `paramiko>=4,<5` for this reason. A development image had picked up paramiko 5.0.0,
  and older devices such as IOS switches that offer only SHA-1 key exchange then failed before login.
- The netmiko maintainer documents the same failure after 4.8.0
  ([ktbyers/netmiko#3892](https://github.com/ktbyers/netmiko/issues/3892)) and points affected users to
  `netmiko[par4]`, which pins paramiko 4, the affected line.

**Options for the owner.**

1. **Keep paramiko 4.0.0 on the stick (the current `main` state).** Legacy SSH reach stays. The named suppression
   stays, scoped to the shipped lock only. Revisit when a fixed 4.x release appears or the field population no
   longer needs SHA-1.
2. **Re-lock to netmiko 4.8.0 / paramiko 5.0.0** (the preserved `b8def26b`). It carries PyPI-verified wheel and
   sdist digests, drops ruamel-yaml (netmiko 4.8.0 made it an optional extra), moves `EXPECTED_BUNDLED_PYTHON`,
   and retires the suppression with a stale-entry rule. This closes the advisory, and SHA-1-only devices become
   uncollectable from the stick. Before merge it would need a `portable/README-FIELD.txt` note naming both errors
   above and the device-side remedy (enable SHA-2 key exchange and `rsa-sha2-256`/`rsa-sha2-512` host-key
   signatures), plus the hosted `Dependency audit` and `Build and qualify Atlas.exe` gates.
3. **Re-lock, plus an explicitly marked legacy collection path** for SHA-1-only devices. This is a design
   question, not a lock edit.

## (b) Windows runner pin: `windows-latest` to `windows-2025`, protected names unchanged

`ci.yml` ran two Windows legs on the floating `windows-latest` label: the required `Tests · py3.12 ·
windows-latest` leg (matrix `include`) and the opt-in projection measurement (matrix `os`). Both now select
`windows-2025`, the label the other GitHub-hosted Windows jobs already pin (`Installed transition runtime ·
pinned Windows profile`, both portable jobs and the visual-regression job).

The test job keeps every protected display name byte-identical, in the same way #607 kept `ubuntu-latest`
while running `ubuntu-24.04`: its name expression maps each pinned image back to its historical label,

```
${{ matrix.os == 'ubuntu-24.04' && 'ubuntu-latest' || matrix.os == 'windows-2025' && 'windows-latest' || matrix.os }}
```

Actions evaluates `&&` before `||`, so the six legs publish exactly the six `Tests · …` contexts in
`.github/portable-required-main-checks.json`, which also equal the live `main` branch-protection list read on
2026-10-09 (15 contexts). A static evaluation of the edited workflow reproduces them.

`tests/test_release_supply_chain.py` now carries `_WINDOWS_IMAGE` and an alias table, evaluates the display
expression per leg from that table, and pins both Windows matrices to `windows-2025`. New rejections: a
floating `windows-latest` leg (whose context name would not change, so only the strategy pin catches it), a
different Windows image, a floating performance runner, and the old Linux-only name expression (which would
publish `Tests · py3.12 · windows-2025`, a context no rule requires, and wedge every merge). A separate test
holds the expression text equal to the alias table.

**Image evidence.** In the latest `main` CI run (`37922698382`, head `6390b66c`), the `windows-latest` job
(`113794187896`) and the `windows-2025` job (`113795139628`) both ran image `windows-2025-vs2026`, version
`20260925.250.1`, on Windows Server 2025. The pin is therefore a no-op for today's image and stops a future
`windows-latest` migration from moving a required check onto an unreviewed image. A label still does not
freeze image revisions.

**Owner record.** The 2026-10-02 owner decision in `docs/NOW.md` says #586's optional measurement job "uses
GitHub-hosted `windows-latest`", and the W2d handoff records that runner as expressly requested. The pin keeps
the job GitHub-hosted, and the self-hosted-runner guard is unchanged, but the literal label changes. The board
therefore carries a dated note under that decision, pending owner confirmation. If the owner prefers the
literal label, reverting only the measurement leg means reverting its `ci.yml` matrix value and its pin in
`tests/test_release_supply_chain.py`; the required `Tests · …` contexts are unaffected either way.
