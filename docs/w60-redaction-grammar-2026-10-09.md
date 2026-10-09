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

## Round 2: the guarantee restated, and what the round-1 review found outside it

The round-1 review reported 232 more leaking lines (every one is now a must-redact corpus row). They
showed that "a word the sweep does not know is redacted" held only AFTER A LISTED KEYWORD: a secret with
no listed keyword before it, on a later line than its key, or in a column or argument position, was a
deny-list miss again, and round 1 had also lost origin/main's terminal-wrap behaviour. Round 2 states
the guarantee exactly -- **fail safe after a listed credential keyword or credential field name, and
inside a closed list of positional forms; everything else is the grammar and the entropy rule** -- and
widens each list:

- **Keyword families (P1).** Keywords are found inside camelCase and numbered compounds
  (`authPassword`, `md5Key`, `snmpV2Community`, `password2`, `passwordHash`), and the families the review
  named are anchored (Junos `plain-text-password-value`, FortiGate `password2`/`passwd`,
  `radius-common-pw`, PIM `hello-authentication`, `ldap-server ... manager`, LTE `chap`, `authkey`,
  net-snmp sink lines, tac_plus `login = cleartext`, NTP key files, `ephone ... pin`). The exact
  lists are `_REDACT_SWEEP_KEYWORDS`, `_REDACT_SECRET_ANCHORS` and the corpus.
- **Credential field names (P2).** One vocabulary for snapshot keys and raw text: the snapshot owner
  `_REDACT_SECRET_KEYS` / `_REDACT_SECRET_TOKENS`, plus the raw-text extras (`_REDACT_RAW_TOKEN_EXTRAS`,
  and for a quoted key or XML name `_REDACT_RAW_QUOTED_EXACT`), applied by `_redact_credential_name` to
  JSON/YAML/INI keys, XML elements and attributes, form bodies and percent-encoded payloads. Registered
  in `docs/ssot.md`; the verifier's copy is pinned equal.
- **Shell arguments (P2):** `curl -u user:X`, `sshpass -p X`, `mysql -pX`, net-snmp `-c`/`-A`/`-X`.
- **Multi-line credential blocks (P2):** a JSON key, XML element or YAML key naming a credential that
  opens a block (RESTCONF, NETCONF, vManage templates, YAML block scalars and lists, a JSON value on the
  next line): every line inside is swept. Private-key blocks now also cover SSH2 / RFC 4716 armor and
  PuTTY `Private-Lines: N` bodies (P3).
- **Positional forms (P3):** the closed show-table list, CSV/TSV/`;`/`|` files whose header names a
  credential column (a region ends at the first line that is not row-shaped), pppd chap-secrets, crypt(3)
  hashes and shadow fields anywhere.
- **Terminal wraps (P2, the round-1 regressions).** origin/main's cross-line `\s+` caught a value a
  terminal wrap moved to the next line. Round 2 restores that as an explicit model: a line DANGLES when
  its last value-required keyword is followed only by qualifiers (`snmp-server community`,
  `enable secret 0`, `set password ENC` -- the FortiGate refusal, P3), and the first non-qualifier token
  of the next non-blank line is redacted; the grammar is re-read across the join for exactly the families
  main crossed (`_REDACT_SECRET_CROSS`); a split `snmp-server` / `host` and a split keyword are joined; a
  lone token after a value is the value's tail. A wrap takes ONE token, as main's `\s+` did, never a
  token that starts a clause of its own (a key ID before `key-string`, `edit`/`next`, `snmp-server`), and
  a type digit that ends the text is the value. A wrap continues into a credential-block line too, and,
  fail safe and producer-only, is also read from the previous line AS IT WAS when the scrub replaced the
  keyword it hangs on.
- **Free text (P3).** Description/remark/comment lines and banner bodies add the informal anchors people
  type (`pw X`, `pwd: X`, `creds admin/X`, `account ops / X`); show-output prose (`Authentication MD5,
  key-string`) is not a clause.
- **Qualifier collisions (P3):** void words are checked per keyword (`key chain`, `password encryption`),
  numbers stay ordered, and a lone qualifier-shaped word after a keyword is the value
  (`enable secret level`, `snmp-server community RO`), except a hash or encoding word, which dangles.
- **Verifier independence (P3).** Besides restating the producer's lists, the verifier parses every
  embedded JSON document and checks each credential-named field with the snapshot rule
  (`_is_secret_key`), and applies a credential-named-field rule and a dangle-aware FortiGate rule of its
  own. A layout the line rules cannot follow (key, colon and value on three lines) is refused although
  the producer sees nothing there.

Every multi-line state (blocks, banners, CSV, chap-secrets, tables, wraps) is advanced from the SCRUBBED
lines on both sides, so the verifier reaches the producer's plan from the output alone; armor, PuTTY
headers and table headers are plan lines the scrub never alters. Each line is a fixpoint of its own
sweep, and the scrub is idempotent.

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
8. **Terminal wraps** (replaced in round 2, see above): round 1 swept the next line whole after a
   cipher/hash/encoding word; round 2 takes the one wrapped value of a dangling clause instead, and also
   restores the cross-line grammar origin/main had.
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

`tests/fixtures/redaction_grammar_corpus.json` (round 2):

- **842 must-redact** rows: the W60 builder's 183, every line of the W60 round-0 review (131), the
  W58r2 review corpus (94), the round-1 review (232: config lines, controller/REST payloads, YAML, PEM,
  CSV, shell, multi-line show captures) and 202 terminal-wrap rows (a corpus clause cut at a space where
  origin/main removed the secret across the line end and only the wrap rules remove it). Platforms: IOS 220,
  wrap 202, Huawei 45, NX-OS 37, Junos 35, ASA 32, FortiGate 30, AireOS 27, REST 26, IOS-XR 24, EOS 23,
  show 21, PAN-OS 19, odd encodings 17, PEM 10, and 46 rows across URL/API/C9800/net-snmp/YAML/CSV/
  banner/token/shadow/shell/PPP/tac_plus/NTP/RADIUS forms. Each carries its exact output and fake secrets.
- **145 must-keep** rows, byte-identical and certified.
- **31 over-redacted** rows: must-keep candidates the fail-safe rules rewrite, each pinned to its result
  with a note. Round 1's 30 examples stand (`Key: U - Unicast, ...`, BGP `Community: 65000:100`, Junos
  policy communities, `tunnel key 12345`, `key 01`, EOS `ssh-key ssh-rsa <public key>`, prose such as
  `Do not share your password with anyone.`); round 2 adds multi-line show captures (`show key chain`,
  `show logging` after `cipher`, `show authentication sessions` session IDs, labelled image hashes in a
  table, a running-config's `snmp-server host ... priv <user>`).
- **`main_6390b66c`** on every row: origin/main's own `_redact_config_values` output, captured by
  running git-archived 6390b66c (not a frozen copy of its code).

**Measured on the corpus** (real `redact_collection_dir` + `verify_collection_secret_scrub` on scratch
trees, pure calls): 0 secrets survive; 842/842 raw rows refused; 842/842 scrubbed rows certified;
145/145 must-keep and 31/31 over-redacted rows certified; idempotent on every row; the whole corpus as
one capture is a certified fixpoint. **Main parity: of the 464 corpus secrets main 6390b66c removed, the
new scrub removes 464**; main left a secret in 400 must-redact rows, all now removed. The round-1
review corpus re-run (232 rows, 28 show captures, 5 dangle captures): 0 certified leaks, 0 regressions
against main, every scrubbed capture certified. A wrap probe (2,013 cases: each must-redact clause cut
at every token boundary) finds 0 secrets main removed that the new scrub leaves, and the verifier
refuses none of the producer's own outputs. A randomized battery (multi-line mixes of every corpus,
show and dangle segment with CR, LF and CRLF separators) checks idempotence, certification and secret
removal: 82,500 cases on the final code, 0 failures. An earlier 60,000-case battery found 5 cases (a
wrap inside a credential block, a keyword the block sweep itself replaced); they are fixed and pinned
by `test_a_wrap_survives_the_scrub_of_its_own_line`.

## What changed downstream

- **Golden and sample: byte-identical by construction.** Neither runs with `--redact` or
  `--redact-collection`; no module or import was added.
- **Over-redaction on the golden and sample `--redact` outputs** (`redact_snapshot`, pure calls, round
  2): the golden snapshot differs from main's redacted output in 48 of its 21,615 key and string leaves
  (50 strings carry a placeholder, 33 on main, 46 in round 1), the sample in 195 of 111,523 (184 vs 135;
  round 1 178); all are engine-authored prose (remediation text, detector titles, design doctrine). Every
  token main removed from those leaves is still removed except non-secret words main had wrongly taken
  (`encryption`, `in`, `is`, `strings`, `for`, `or`, `mismatch`). No key or list shape changes; both
  results certify.
- **The engine's synthetic collection** (the golden input, 1,052 lines): main changes 4 lines; round 2
  changes 5 (adds the `show storm-control` legend line), and the new verifier certifies all 96 captures.
- **Performance** (pure calls, this workstation, linear in lines): on a keyword-dense synthetic capture
  the scrub costs about 53 us per line (main 6, round 1 16) and the verifier about 42 us per line
  (round 1 17), so a million-line collection scrubs in about a minute and verifies in under one;
  `redact_snapshot` of the sample takes about 3 s (main 1.7 s). A 20,000-character single line stays at
  0.02 s.

## Residual limits (documented, not closed)

1. **A credential spelled exactly like an allowlisted word** in a tail (`1`, `the`, `cipher`, ...) or
   like a void word right after its keyword survives, as does a WRAPPED value spelled like a
   value-required keyword or a command word (`key-string`, `snmp-server`, `edit`); so does a slot's
   integer or name operand, and a punctuation-only secret.
2. **Kw-less positional values** outside the closed table/CSV/chap/forms list (an unknown vendor table, a
   free-form "admin / Fake99" note without a prose anchor) are caught only if high-entropy.
3. **High entropy is a heuristic**: a 24-31 character random token split by `/` into short segments, a
   low-entropy pasted secret, or a hex secret under a digest/identifier-named snapshot key is missed.
4. **Over-redaction is real** (see above): engine prose in `--redact` deliverables, show-output legends,
   BGP/Junos policy communities, keychain IDs above 15, public keys, `rmon`/EEM text, session IDs and
   labelled hashes in show tables, the first word of a line after a dangling clause. The engine's
   `--no-collect` re-analysis of a scrubbed folder loses those values.
5. **Terminal wraps** take ONE token, as main's `\s+` did: a value wrapped across more than one line
   break, or a lower-case remainder after an ambiguous key ID (`ntp server X key 1` / `fakesecret`) or a
   lone command word, is not taken. Wraps on AireOS `config ...` lines are not modelled. A JSON key,
   colon and value on three lines is not followed by the producer (the verifier refuses it, see above).
   Where the producer reads a wrap from a line as it was before its own scrub (a keyword replaced inside
   a credential block or a table cell), the verifier cannot see that keyword on the output and does not
   demand the placeholder: there the guarantee is the producer's alone.
6. **Shareable artifacts** keep their line-start, value-only scan plus PEM; the sweep closes residue
   there, the verifier does not re-detect it.
7. **Captures scrubbed by an older build** cannot be repaired: the scrub cannot reconstruct an
   overwritten qualifier. The new verifier refuses such files (`enable password <redacted> 15 X`).
   Re-collect, or hand-scrub the named lines.
8. **W58r2 coupling**: `evidence_retention` (not on `main`) fingerprints `_INLINE_SECRET_RES`; the tuple
   now names the new grammar, so the retention digest changes on merge. Exact-head hosted CI on the
   merged result is required.

## Not verified

- No pytest, no engine run, no build (owner GITHUB-ONLY rule). The test module was AST-checked and
  linted, and every assertion in it was re-computed with the production functions in a scratch folder;
  it has never executed as a test. The same holds for the pre-existing redaction test files, whose
  redaction assertions were re-computed the same way.
- The full `--redact` pipeline (HTML/XLSX/DOCX certification) was not run; only `redact_snapshot`, the
  snapshot verifier and the raw-capture path were exercised by pure calls.
- Real client captures: every input here is synthetic.
- Hosted CI on every supported interpreter (3.10 to 3.14) is required before merge.
