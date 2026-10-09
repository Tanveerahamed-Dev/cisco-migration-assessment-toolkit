# W60: shareable redaction -- credential grammar, residual sweep and verifier (2026-10-09)

**This was a privacy defect in shipped redaction.** `Atlas.exe --redact-folder` (whose output is
meant to be shareable), `--redact-collection` and AssessHub ingest scrub raw captures with
`cisco_toolkit.html.redact_collection_dir`. That scrub left real credentials in place for a whole class
of configuration lines, and the independent verifier,
`webapp.backend.redaction_verify.verify_collection_secret_scrub`, certified those captures as
scrubbed. The same function (`_redact_config_values`) also feeds `redact_snapshot` and the `--redact`
workbook, so `--redact` deliverables carried the same residue wherever such a line reached them. Treat
any collection or `--redact` deliverable produced before this change as not credential-safe until it
has been scrubbed and verified again with this build (see "Captures scrubbed by an older build").

Branch `claude/w60-redaction-grammar` (board row W60). Static and pure-function evidence only: no test,
build or engine run.

## Round 1: the decision

The first W60 commit (030472a6) replaced the deny-list with a per-family qualifier GRAMMAR. Two
independent reviews (W60, and the W58r2 retention scan's corpus) then found 95 and 74 lines that still
leaked, 18 of them **regressions against `origin/main` 6390b66c** (a numeric key such as
`ip ospf authentication-key 12345678` was read as a key ID and certified). A grammar is a deny-list of
value slots: every slot it models wrongly is a certified leak, and its verifier, written as the same
kind of list, certifies the same leak.

**Supervisor decision: shareable redaction must FAIL SAFE.** Losing a value in a shared copy is
acceptable; leaking a secret is not. So round 1 keeps the grammar (fixed, and never weaker than main on
any corpus line) and adds a RESIDUAL SWEEP whose failure direction is inverted: a word it does not know
is REDACTED. The verifier checks exactly what the sweep guarantees, from the same closed lists.

## The defect (unchanged history)

The original scrub was a deny-list of `keyword + optional type digit + ONE token` patterns. It replaced
the token right after the keyword even when that token was a **qualifier**, and the credential
survived one token further on. Several value-bearing forms had no pattern at all. The verifier's rule
was "the first token after a recognised keyword is the placeholder", so it certified all of them.

| Input line | `origin/main` 6390b66c (certified) | Round 1 |
|---|---|---|
| `enable password level 15 Plain99pw` | `enable password <redacted> 15 Plain99pw` | `enable password level 15 <redacted>` |
| `enable secret level 15 0 Plain99pw` | `enable secret <redacted> 15 0 Plain99pw` | `enable secret level 15 0 <redacted>` |
| `username admin secret sha512 $6$...` (EOS) | `username admin secret <redacted> $6$...` | `username admin secret sha512 <redacted>` |
| `config wlan security wpa akm psk set-key ascii Wlc99psk 1` | `... set-key <redacted> Wlc99psk 1` | `... set-key ascii <redacted> 1` |
| `Enable password is Hunter2pw` | `Enable password <redacted> Hunter2pw` | `Enable password is <redacted>` |
| `SNMP community string : Hunter2pw` | `SNMP community <redacted> : Hunter2pw` | `SNMP community string : <redacted>` |
| ` super password level 15 cipher Hw99pw` (Huawei) | `... password <redacted> 15 cipher Hw99pw` | `... level 15 cipher <redacted>` |
| ` ip nhrp authentication Dmvpn99` | unchanged | ` ip nhrp authentication <redacted>` |
| `snmp-server host 192.0.2.10 public` | unchanged | `snmp-server host 192.0.2.10 <redacted>` |
| ` path scp://admin:Passw0rd99@10.1.1.1/cfg` | unchanged | ` path scp://admin:<redacted>@10.1.1.1/cfg` |
| ` key-octet-string 7 075E...4D cryptographic-algorithm AES_128_CMAC` | unchanged | ` key-octet-string 7 <redacted> cryptographic-algorithm AES_128_CMAC` |
| ` ospf authentication-mode md5 1 cipher Hw99ospf` (Huawei) | unchanged | `... md5 1 cipher <redacted>` |
| ` ip ospf authentication-key 12345678` | ` ip ospf authentication-key <redacted>` | same (W60's first cut leaked it) |
| `enable secret<VT>Fake99vt` | `enable secret<VT><redacted>` | same (W60's first cut leaked it) |
| `rmon event 1 log trap Fake99rmon ...` | unchanged | `rmon event 1 log trap <redacted> description <redacted> owner <redacted>` |
| `logged command:snmp-server community clear Fake99 RO` (syslog) | `... community <redacted> Fake99 RO` | `... community clear <redacted> RO` |
| `Authorization: Bearer Fake99tok` | unchanged | `Authorization: Bearer <redacted>` |
| `export CISCO_REST_PASS=Fake99env` | unchanged | `export CISCO_REST_PASS=<redacted>` |

## The producer: one function, two passes

`cisco_toolkit/html.py :: _redact_config_values` (no new module). Lines are split ONLY on CR/LF and
rejoined with their original separators, so every byte the scrub does not replace is unchanged.

**Pass 1 -- the credential GRAMMAR** (`_REDACT_SECRET_RES`, `_redact_family`). KEYWORD, an atomic
QUALIFIER RUN, VALUE, per family: password/secret/passphrase forms, SNMP communities (every SNMP
context, the Junos block, the show prose forms, `community-map`/`community-name`/`trap-group`), the
positional trap-host community, SNMPv3 `auth`/`priv`, TACACS+/RADIUS keys, `key-string`,
`key-octet-string`, `pre-shared-key`, `shared-key`, MACsec, wireless PSKs, NHRP/FHRP/NX-OS text
authentication, Huawei `authentication-mode`/`privacy-mode`, OSPFv3 `authentication|encryption ipsec
spi`, EIGRP `hmac-sha-256`, and the bare `key` family. Round-1 fixes:

- **Numbers are ordered**, never a repeatable "any integer" qualifier: a key ID only directly before a
  hash label or `--`, a type digit only when another token follows it, and a bare 0-15 at the end of a
  `key` line is a key ID. This closes the 18 numeric-key regressions.
- Added qualifiers: ASA `community 0|8`, IOS-XR `clear|encrypted` (community, host, SNMPv3 user), `des56`,
  `sha2-224..512`, LDP `fallback`; PAN-OS `pre-shared-key key`; FortiGate `api-key`, `secret-key`,
  `key-string`. Stop words: LDP `option|rollover`, `authentication`, `strength`, key `inbound|outbound`.
- A private-key armor token is never a value (the PEM rule owns the block).
- Grammar anchors carry bounded lazy spans (`{0,200}`) and lines over 2,048 characters skip the grammar
  (the linear sweep still runs), so a pathological line cannot stall a run.

**Pass 2 -- the RESIDUAL SWEEP** (`_redact_sweep_line`). Every list is CLOSED and restated in the
verifier; `tests/test_redaction_grammar_corpus.py` pins each pair equal.

1. **Keyword tails.** The FIRST credential keyword on a line (`_REDACT_SWEEP_KEYWORDS`: password,
   passwd, passphrase, pass-phrase, secret, enablesecret, psk(secret), pre-shared-key, phash,
   auth/priv-pwd, authpwd/privpwd, community (+ -string/-name/-map, ro/rw-community, com2sec),
   trap-group, securityname, createuser, key (+ key-string, private-key, secret-key, api-key),
   token/idtoken/bearer/ssws, auth, cipher/plain/ascii/hex, set-key, cak/ckn, v3user/mgmtuser/netuser,
   pkcs12, cvauth/ingestauth, credentials, authentication-key/-keyid/-mode, privacy-mode,
   encrypted-password, environment-variable names `*_pw|*_pwd|*_pass|*_password|*_secret|*_token|*_key`,
   the HTTP headers `Authorization`/`Cookie`/`X-*-Token`/`X-*-API-Key`, and the multi-word anchors
   `snmp-server host`, `nhrp authentication`, `standby|vrrp|glbp [N] authentication`,
   `authentication text|mode`, `... ipsec spi`, `rmon event`, `event manager environment`,
   `cli command`, `user:`/`groupname:` in `show snmp host|group`). Every token after it is replaced
   unless it is structural: a word of the closed allowlist `_REDACT_SWEEP_ALLOW` (exact words, never
   prefixes: encodings and hash labels, SNMP access/model/notification words, address/host/vrf/port
   words, roles and levels, `0`-`15`, `128|192|256`, `2c`, Junos punctuation, a short list of prose
   function words and authorization schemes), an IPv4/IPv6 literal, an interface name, a synthetic
   pseudonym, the placeholder, pure punctuation; or the one integer operand of a slot word
   (`udp-port 162`, `RO 10`, `timeout 5`) or the one name operand of `key-chain|keychain|chain|vrf|
   use-vrf|filter-vrf`. A keyword followed directly by a closed VOID word is structural
   (`key chain|generate|name|data|id|...`, `password encryption|policy|...`, IOS route-map
   `set|match community`, Huawei `authentication-mode hwtacacs|local|...`, `community complexity-check`,
   `pre-shared-key key-chain`).
2. **Private-key blocks** (stateful): `-----BEGIN ... PRIVATE KEY-----` with nothing after it opens a
   block whose body lines become the placeholder up to the `END` armor (or the end of the text, fail
   safe); content beside armor on one line (the JSON-escaped `\n` form) becomes the placeholder.
3. **URL userinfo** with any characters (`/`, `:`, `@`, empty user): everything after the first `:` up to
   the LAST `@` of the URL token; a userinfo without `:` is replaced whole. Secret-named query values
   (`sig`, `token`, `access_token`, `api_key`, `password`, ...) too.
4. **XML elements** whose name contains a credential keyword: the element value.
5. **Credential columns** of a closed list of show tables (NX-OS `show snmp community` and
   `show snmp host`, IOS `show crypto isakmp key`, AireOS `show snmpcommunity`) and of CSV files whose
   header names a credential column; table cells keep their width.
6. **Junos `## SECRET-DATA`** lines and FortiGate `config system snmp community` / `set name`.
7. **High-entropy tokens anywhere**: >= 24 base64/base64url characters with a 16+ character segment
   (split on `-`, `_`, `/`) mixing upper case, lower case and digits whose character classes change at
   least every 2.5 characters on average; >= 32 contiguous hex digits; and a closed list of credential
   token formats (GitHub, GitLab, Slack, Stripe, `sk-`, AWS key IDs, Google API keys, OAuth `ya29.`,
   JWT). **Decided exemptions:** a digest or fingerprint LABELLED as such directly before it
   (`sha256:`, `SHA256 hash`, `"md5": "`), an SSH public key after its algorithm name, an interface
   name, a pseudonym; in a `--redact` snapshot, hex under a JSON key that names a digest or an
   identifier (`*_sha256`, `*digest*`, `*hash*`, `*_id`), because those are the engine's own content
   bindings and join keys and redacting them breaks every receipt that cites them (a credential-named
   key is redacted whole before this pass). A path (`/interfaces/core1/Vlan30`) and a camelCase
   identifier (the ACI class in `topology/HDfabricOverallHealth5min-0`) are not random.
8. **Terminal wrap**: a line whose last swept token is a cipher/hash/encoding word, or a cipher name
   plus a number that is not a key size (`priv aes 1`), sweeps the next line whole.
9. **One lexical model**: lines end only at CR/LF; VT, FF, FS..US, NEL, NBSP and every Unicode space,
   U+2028/2029, a BOM and a non-UTF-8 byte (U+DC80..U+DCFF) separate tokens -- in the grammar, the sweep
   and the verifier alike. A non-UTF-8 byte run beside a placeholder is folded into it.

## The verifier

`webapp/backend/redaction_verify.py` restates both passes; it does not import the producer.

**Raw captures** (`verify_collection_secret_scrub` -> `_raw_capture_credential_findings`): every line,
no exemptions (banner bodies, descriptions, comments and syslog records are swept like any other
line). A capture is refused if, on any line:

- a grammar value slot is not the placeholder (`credential value (<family>)`);
- after the first non-void credential keyword, any token is neither structural nor a slot operand
  (`credential residue after a credential keyword`) -- the sweep's exact guarantee;
- a private-key body, URL userinfo/secret query value, credential XML element, table or CSV credential
  cell, or a high-entropy token is not the placeholder;
- a FortiGate secret attribute carries anything but placeholders (or private-key armor whose block the
  PEM rule verifies).

The W60 first cut's tail allowlist, its free-text exemption and its "placeholder outside the grammar"
rule are gone: the sweep check subsumes them (a pre-W60 output such as
`enable password <redacted> 15 Plain99pw` is refused because `Plain99pw` follows the keyword).

**Shareable artifacts** (`_scan_text`: snapshot JSON, OOXML text, HTML, text artifacts): the line-start
value scan as before, plus private-key material. The sweep guarantee is NOT asserted there: the engine
writes authored prose after the scrub (the design blueprint is computed from the redacted snapshot), so
the guarantee does not hold on those surfaces and asserting it would refuse every `--redact` run.

`_INLINE_SECRET_RES` is kept as a tuple of every compiled verifier pattern, because the D10
evidence-retention branch (W58r2) digests it at import time.

## Corpus and pins

`tests/fixtures/redaction_grammar_corpus.json`:

- **408 must-redact** lines: the W60 builder's 183, every line of the W60 review (131) and of the W58r2
  review corpus (94), across IOS/IOS-XE, NX-OS, ASA, AireOS/C9800, IOS-XR, EOS, Junos, FortiGate,
  Huawei, PAN-OS, net-snmp, REST/API logs, PEM, URLs, show tables, CSV, and odd encodings. Each carries
  its exact output and fake secrets; 17 carry `notail` (the first placeholder is not keyword-governed:
  URL userinfo, a whole high-entropy token, a user name before the keyword).
- **113 must-keep** lines, byte-identical and certified.
- **30 over-redacted** lines: must-keep candidates (17 of the builder's 102, 13 of the review's 42) that
  the fail-safe sweep rewrites; each is pinned to its result with a note. Examples:
  `Key: U - Unicast, ...` (show storm-control legend), BGP `Community: 65000:100 no-export`, Junos
  policy `community CNAME members ...`, `tunnel key 12345`, `key 01`, EOS `ssh-key ssh-rsa <public key>`,
  `snmp-server host X use-vrf management`, prose such as `Do not share your password with anyone.`
- **`main_6390b66c`** on every row: origin/main's own `_redact_config_values` output, captured by
  running git-archived 6390b66c (not a frozen copy of its code).

**Measured on the corpus** (real `redact_collection_dir` + `verify_collection_secret_scrub` on scratch
trees): 0 secrets survive; 408/408 raw lines refused; 408/408 scrubbed lines certified; the tail probe
refused on 391/391 keyword-governed rows; 113/113 must-keep and 30/30 over-redacted lines certified;
idempotent on every row. **Main parity: of the 146 corpus secrets main 6390b66c removed, the new scrub
removes 146**; main left a secret in 268 of the 408 must-redact rows, all now removed.

## What changed downstream

- **Golden and sample: byte-identical by construction.** Neither runs with `--redact` or
  `--redact-collection`; no module or import was added.
- **Over-redaction on the golden and sample `--redact` outputs** (`redact_snapshot`, pure calls): the
  golden snapshot differs from main's redacted output in 45 of 8,974 string leaves (46 strings carry a
  placeholder, 33 on main), the sample in 208 of 49,488 (178 vs 135); all are engine-authored prose
  (remediation text, detector titles, design doctrine). Every token main removed from those leaves is
  still removed except non-secret words main had wrongly taken (`encryption`, `in`, `is`, `strings`,
  `for`, `or`, `mismatch`). No key or list shape changes; both results certify.
- **The engine's synthetic collection** (the golden input, 1,052 lines): main changes 4 lines; round 1
  changes 5 (adds the `show storm-control` legend line), and the new verifier certifies all 96 captures.
- **Performance** (pure calls, this workstation, noisy): a 210,000-line keyword-dense synthetic capture
  scrubs in 5.9 s (W60 first cut 2.9 s) and verifies in 5.9 s (4.0 s); `redact_snapshot` of the sample
  takes 2.5 s (main 3.0 s).

## Residual limits (documented, not closed)

1. **A credential spelled exactly like an allowlisted word** in a tail (`RO`, `1`, `the`, `cipher`, ...)
   or like a void word right after its keyword survives; so does a slot's integer or name operand.
2. **Kw-less positional values** outside the closed table/CSV/forms list (an unknown vendor table, a
   free-form "admin / Fake99" note) are caught only if high-entropy.
3. **High entropy is a heuristic**: a 24-31 character random token split by `/` into short segments, a
   low-entropy pasted secret, or a hex secret under a digest/identifier-named snapshot key is missed.
4. **Over-redaction is real** (see above): engine prose in `--redact` deliverables, show-output legends,
   BGP/Junos policy communities, keychain IDs above 15, public keys, `rmon`/EEM text. The engine's
   `--no-collect` re-analysis of a scrubbed folder loses those values.
5. **Terminal wraps** are recognised only after a cipher/hash/encoding word or a truncated key size.
6. **Shareable artifacts** keep their line-start, value-only scan plus PEM; the sweep closes residue
   there, the verifier does not re-detect it.
7. **Captures scrubbed by an older build** cannot be repaired: the scrub cannot reconstruct an
   overwritten qualifier. The new verifier refuses such files (`enable password <redacted> 15 X`).
   Re-collect, or hand-scrub the named lines.
8. **W58r2 coupling**: `evidence_retention` (not on `main`) fingerprints `_INLINE_SECRET_RES`; the tuple
   now names the new grammar, so the retention digest changes on merge. Exact-head hosted CI on the
   merged result is required.

## Not verified

- No pytest, no engine run, no build. The test module was AST-checked and linted, and every assertion
  in it was re-computed with the production functions in a scratch folder; it has never executed as a
  test.
- The full `--redact` pipeline (HTML/XLSX/DOCX certification) was not run; only `redact_snapshot`, the
  snapshot verifier and the raw-capture path were exercised by pure calls.
- Real client captures: every input here is synthetic.
- Hosted CI on every supported interpreter (3.10 to 3.14) is required before merge.
