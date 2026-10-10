# W60: shareable redaction -- credential grammar, residual sweep and verifier (2026-10-09, rounds 3-4 2026-10-10)

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

## Round 3: what the round-2 review found, and the fail-safe rules that close it

The round-2 review ran 2,154 invented cases through round 2 (`409b854e`) and through `origin/main`
6390b66c. It reported 381 cases that leaked and certified, regressed against main, were certified raw,
or changed verdict. Every one of them is now a corpus row (367 must-redact, 14 qualifier-shaped), along
with every line its report quotes and an R1 pin matrix. Round 3 changes only the existing owner
(`cisco_toolkit/html.py`) and its restatement (`webapp/backend/redaction_verify.py`). It adds no module.

- **R1 (P1): a keyword INSIDE a wrapped value is no clause start.** `_redact_starts_clause` and
  `_sweep_starts_clause` accepted any keyword found inside the candidate token. Round 2 had widened
  keywords to camelCase and numbered names, so a wrapped `Secret99Qz`, `Password2026x`, `md5KeyQ` or
  `BgpSecret!77` read as a new clause. The producer left the value and the verifier certified it: 138
  regressions against main. Now a token starts a clause only when a grammar anchor or keyword begins at
  the token's core and covers all of it. A credential field name with its own separator (`pw=Q9x`) is no
  longer a clause start after a dangling clause either: it is the value. A token the line's own sweep
  only partly replaced (`BgpSecret<redacted>`) is taken whole, in the continuation, the cross-line
  grammar and table cells alike. The same rule decides dangling: a keyword that only sits inside a word
  (`Secret99Qz`) no longer makes its own line dangle and cost the next line its first word. A cross-line
  clause has to start a token (`S3cret$Key` holds no `key` clause).
- **R2: the prose-comma guard is positional.** A keyword counts as prose only when it directly follows a
  comma (`Authentication MD5, key-string`), or follows an English word from `_REDACT_PROSE_PREV`
  (`check configured username and password`). A comma anywhere earlier
  (`User:admin, logged command:username x password 0`) no longer drops the wrapped value.
- **R3: a clause never ends in a qualifier.** A qualifier, or a soft stop word, is the VALUE when it ends
  the line or stands directly before a clause-continuing word with its operand (`privilege`, `role`,
  `authorization`; for the bare `key` family also `address`/`hostname`). Examples: `enable secret 0 none`,
  `username adm secret 0 md5`, `key-string enc`, ` ikev1 pre-shared-key local`,
  `username ops password md5 privilege 15`, `crypto isakmp key enc address X`. `origin/main` redacted
  every one of these. Round 2 kept them, and in the last two forms it replaced the clause word instead of
  the value. The exceptions are explicit. A lone type digit, or FortiGate's upper-case `ENC`, that ends a
  line while more lines follow still starts a wrapped value. HARD stop words, a family's structural words
  that may end a complete line, stay structural: `ntp server X key 1 prefer`, Huawei
  `authentication-mode aaa`, `mpls ldp password required`, `key config-key ascii|password-encrypt`, an
  FHRP `authentication md5`.
- **Credential cells are values by POSITION.** A show-table row is recognised by its row shape. Its
  credential cell is chosen by field index, plus every field overlapping the credential column (fail
  safe), so a keyword inside the cell no longer ends the table. Round 2 ended the table there and
  certified the value. The shapes: NX-OS community (2-4 fields with a column gap), AireOS (an IPv4
  address second), `show crypto isakmp key` (keyring, peer, key; or keyring, address, mask, key), NX-OS
  `show snmp host` (the fields after the type). A line whose credential column already holds the
  placeholder is a row whatever its shape, so residue beside it is refused. A strict GENERIC header also
  opens a table: three or more Title-case columns separated by two or more blanks, one of which names a
  credential (`Device  Username  Password  Enable`). chap-secrets takes field 3 by position. A CSV header
  counts the exact short names (`pass`, `key`, `auth`) as credential columns. A second CSV header of
  another width opens a region of its own.
- **Placeholders in the wrong place.** A YAML block-scalar indicator (`|`, `>-`, ...) is never a grammar
  value, so the block opens and its lines are swept. A YAML credential key with an inline value also
  opens a block: more-indented lines continue the plain scalar. An unquoted `pass`/`pw`/`pin` key names a
  password (`_REDACT_RAW_UNQUOTED_EXACT`). The one token after an HTTP authorization scheme (`Bearer`,
  `Basic`, `SSWS`, ...) is swept whatever it spells (`Authorization: Bearer ro`).
- **Wrap continuations.** A column-0 continuation of a wrapped value takes its first token even when a
  clause-trailing word follows it (`<tail> RO 99`, `<tail> address 203.0.113.9`, `_REDACT_CONT_TRAILERS`).
  It never takes a `key=value` / `key:` field. It does not chain on from a lone placeholder line unless
  the token holds letters and digits. The lower-case exemptions are now a CLOSED list of command words
  (`_REDACT_COMMAND_WORDS`): after an ambiguous key ID and on a one-token tail line, any other word is the
  value, so a lower-case wrapped tail is redacted too. `password=` with nothing after it no longer
  dangles. A PuTTY `Private-Lines: N` that undercounts its body keeps sweeping the base64 lines after it.
- **Families neither main nor round 2 covered.** IOS-XR HSRP `authentication <str>` (line start, lower
  case, one token; the structural one-word forms are void) and VRRP `text-authentication`. NHRP, FHRP
  `authentication text` and the AireOS `config radius|tacacs ... add` / `config mgmtuser|netuser add`
  families are followed across a wrap. SNMPv3 `priv <cipher>` on a line of its own. IOS-XE YANG
  `<community-config><name>X</name>` on one line: a non-structural child of a credential-named element.
  `rootpw`, `bindpw`, `*_authtok`, RFC 2307 / htpasswd `{SSHA}`/`{SHA}` hashes. `echo user:X | chpasswd`,
  a `.pgpass` line, `ipmitool -P`, `smbclient -U user%X`, `net use ... X`, and an expect `send` after a
  password prompt. Free-text anchors `string is|:`, and `login|username <user> /`. Huawei
  `snmp-agent community read|write <name>` and AireOS `config snmp community create <name>`.
- **Over-redaction the review measured.** Kept now: SSH2 syslog `crypto cipher`, NX-OS rmon default
  descriptions and owners (the trap community is still redacted), IKEv2 `Auth sign|verify: PSK`, the
  NX-OS `show snmp user` header, AireOS `Credentials Caching`, `auth via`, `(psk tunnel)`,
  `password reset`, `available`, AireOS `config radius auth add` ports, and `Authentication Servers`.
- **Fail-closed disagreements now agree.** These are certified after the scrub: a JSON value on the line
  after its key, a triple-quoted value, FortiGate `set password enc`, and `set password ENC` at the end of
  the text.
- **Linear on keyword runs.** The previous-token lookups in the keyword anchor and the dangle reader were
  O(n) per keyword, so a single 45 KB line of repeated keywords took seconds (round 2: 1.3 s, quadratic).
  They now use one token index per line.

**Verifier independence, decided.** The supervisor's rule stands: the verifier checks exactly what the
sweep guarantees, from the same closed lists, pinned equal by
`test_the_verifier_restates_the_producers_closed_lists`. The review's complaint was mirrored BLINDNESS,
not mirrored lists. Every exemption the two sides share is now an exact word or a positional shape: the
whole-token clause start, the comma directly before a keyword, the closed command-word list. None of
them is a substring or a shape guess. The verifier also has positional checks of its own: table, chap
and CSV cells by field index and column, the YAML block opened by an inline value, and residue beside a
placeholder in a wrapped value or a cell. Its independent JSON-field and FortiGate checks stay.
Measured: of the review's 2,154 cases, the verifier now certifies no raw input that still holds its
secret (round 2 certified 291).

## Round 4: the final review's three residual classes

The third fresh-corpus review of round 3 (`b07fff18`) found 0 regressions against main and 893 more secrets
removed than main. It reported three classes that still leaked and certified. None of them is a regression.
Round 4 closes each one in the existing owner and its restatement, with no new module or import.

- **P2: net-snmp argument vectors, read by STRUCTURE.** snmpd.conf(5) defines `trapsess [SNMPCMD_ARGS] HOST`
  (an inform is `trapsess -Ci`) and `proxy [-Cn CONTEXTNAME] [SNMPCMD_ARGS] HOST OID`
  (<https://www.net-snmp.org/docs/man/snmpd.conf.html>). Their `-c`, `-A` and `-X` operands
  (<https://www.net-snmp.org/docs/man/snmpcmd.html>) were outside the closed tool list, so they leaked and
  the verifier certified them. A line is now an SNMP argument vector, from its first token, when it holds one
  of net-snmp's own option and operand pairs: `-v 1|2c|3`, `-l noAuthNoPriv|authNoPriv|authPriv`,
  `-a|-x <USM protocol>` (`_REDACT_SNMP_PROTOCOLS`) or `-3m|-3M|-3k|-3K`
  (`_REDACT_SNMP_ARGV_SHAPE_RE`). It does not matter which directive, wrapper script or log record carries
  it. When a vector names none of those options and relies on snmp.conf defaults, the SNMPCMD_ARGS
  directives at the line start still mark it: `trapsess`, `proxy`, and the review's `informsess`
  (`_REDACT_SNMP_DIRECTIVE_RE`). `informsess` is not a net-snmp directive; it is read the same way, fail safe.
  - On a vector, the `-c`, `-A` and `-X` operands are values, and so are the `-3m|-3M|-3k|-3K` key operands.
  - An `-a`/`-x` operand is kept when it is a protocol name, and otherwise redacted as a value, fail safe.
    net-snmp-create-v3-user(1) spells `-a AUTHPASS -x PRIVPASS -X DES|AES`
    (<https://www.net-snmp.org/docs/man/net-snmp-create-v3-user.html>).
  - The closed command list gains `net-snmp-create-v3-user`, `net-snmp-config` and encode_keychange(1)
    (`-O`/`-N` passphrases, <https://www.net-snmp.org/docs/man/encode_keychange.html>). snmptrapd.conf(5)
    has no SNMPCMD_ARGS directive. Its `createUser` and `authCommunity` were already keyword lines.
- **P3: net-snmp positional credentials.** net-snmp saves a printable octet string `"quoted"` and any other
  as lowercase `0x` hex (snmplib/read_config.c `read_config_save_octet_string`). The entropy rule needs
  upper case, so it never read a persisted localized key, whatever its length; the review's "32+ hex keys
  are caught" did not hold for this format. The persistent `usmUser` line's AUTH KEY and PRIV KEY are now
  values by field index (snmplib/snmpusm.c `usm_save_user`: status, storage type, engine ID, name, security
  name, clone-from, auth protocol, auth key, priv protocol, priv key, public string). So is snmpd.conf(5)
  `smuxpeer OID PASS` (`_REDACT_SNMP_POSITIONAL`). An empty `""` field is no value.
- **P3: an authorization scheme that ends its line.** A credential header (`Authorization`,
  `Proxy-Authorization`, an `X-...-Token|Api-Key|Auth...` header) whose scheme (`_REDACT_SWEEP_SCHEMES`)
  ends the line now DANGLES (`_REDACT_SCHEME_OPEN_RE`). The next non-blank line's first blank-delimited token
  is the credential, whatever it spells. The verifier demands the placeholder there.

Every rule is restated in the verifier and pinned equal (`_REDACT_SNMP_PROTOCOLS`, `_REDACT_SNMP_POSITIONAL`,
`_REDACT_ARGV_OPTIONS`, and the four new patterns). The verifier also adds the four patterns to
`_INLINE_SECRET_RES`.

**Pushed history.** GitHub push protection refused the first push. The synthetic Slack-format sentinel of
corpus row `w58r2-review:C30` (`xoxb-` followed by digit groups) matched its Slack token detector. The row is
respelled `xoxb-FakeSlackNotAToken-abcdefghij`; the producer's token-format rule still matches it, main still
leaves it, and the scrubbed result is still `<redacted>`. Because the branch had never been pushed, every
local commit since round 1 was rewritten for that one string, and nothing else changed. The reviewed commits
this record cites are mapped as follows: round 2 `409b854e` is pushed as `607b6f0e`, and round 3 `b07fff18`
is pushed as `d05ff1aa`. The pre-rewrite history is kept on this host at
`refs/preserved/w60-pre-push-rewrite-0f008ca3`.

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

`tests/fixtures/redaction_grammar_corpus.json` (round 3):

- **1,422 must-redact** rows. 842 rows are carried from round 2. 580 are new: 367 cases the round-2
  review reported, 17 further lines its report quotes, and 196 rows of the R1 pin matrix (each dangling
  credential clause x {neutral, camelCase-keyword, numbered-keyword, keyword+punctuation} value, the
  keyword dangling at the end of the line). 42 carried expectations are re-pinned to round 3. The
  differences are listed under "What changed downstream".
- **14 qualifier-shaped** rows (new kind). Each secret is spelled like a word its line also uses as
  structure (`snmp-server host X version 2c host`, `username adm secret 0 secret`), so it is checked by
  its whole-word count, which must drop.
- **146 must-keep** rows, byte-identical and certified. One round-2 over-redacted row, an SSH2 syslog
  capture, is now kept whole.
- **30 over-redacted** rows, each pinned to its result with a note.
- **`main_6390b66c`** on every row: `origin/main`'s own `_redact_config_values` output, captured by
  running git-archived 6390b66c (not a frozen copy of its code). The 1,018 carried values were
  re-captured from a fresh archive and match byte for byte.
- **Round 4 (`w60-review-r4`):** 29 must-redact rows (16 net-snmp vectors, 4 positional lines, 8 scheme
  wraps, 1 encode_keychange), 20 must-keep negative controls and 2 over-redacted rows. The negative controls
  are look-alike lines: another tool's `-A`/`-X`/`-c` (curl, ssh, iptables, tar, ping), a daemon's
  `-c FILE`, `proxy-arp`, a noAuthNoPriv `trapsess`, an empty-key `usmUser`, a USM MIB walk, `smuxpeer`
  without a password, `WWW-Authenticate: Basic`, OAuth `token_type`, and scheme prose. The totals are now
  1,451 must-redact, 166 must-keep, 32 over-redacted and 14 qualifier-shaped rows. main 6390b66c leaves
  every round-4 secret in place.

**Measured on the final code** (production functions only, in scratch folders):

- **Corpus.** 0 listed secrets survive. 1,422/1,422 raw must-redact rows are refused and 1,422/1,422
  scrubbed rows certified, through `redact_collection_dir` and `verify_collection_secret_scrub` on
  scratch trees. The tail probe is refused wherever no `notail` flag is set. Every row is idempotent,
  and the whole corpus as one capture is a certified fixpoint.
- **Main parity.** Main removed 844 listed secrets (831 by substring, 13 qualifier-shaped by word
  count). Round 3 removes all 844.
- **The round-2 review's 2,154 cases** (its harness, re-run). 0 certified leaks, 0 regressions against
  main, 0 raw inputs certified, 0 producer outputs refused. 893 secrets that main left are removed.
- **R1 generalisation matrix.** 27,540 cases: 51 dangling clauses x 27 value shapes x 10 trailing words
  x LF/CRLF. 0 failures: the value is gone, the raw text is refused, the output is certified and
  idempotent, and the next line survives.
- **Randomized multi-line battery.** Every corpus, show, dangle and review segment, joined with CR, LF
  or CRLF. 12,000 cases on the final code (plus about 44,000 on intermediate builds), 0 failures.
- **Every assertion of the test module** was re-computed by hand-restated scratch checks, not by running
  the tests.
- **Round 4, on the final code.**
  - Corpus: 1,451/1,451 must-redact rows lose every listed secret, are refused raw and certified after
    the scrub, and are idempotent. The whole corpus as one capture is a certified fixpoint with no
    surviving strong secret. Every round-4 row also went through `redact_collection_dir` and
    `verify_collection_secret_scrub` on scratch trees.
  - Main parity: unchanged (every secret main removed stays removed).
  - Vector matrix: 15,652 cases (11 carriers x 8 version/level/protocol forms x 7 secret options x 7
    value shapes x attached/separate x LF/CRLF, wherever a route applies). 0 failures: the value is gone,
    the raw text is refused, the output is certified and idempotent, and the next line survives.
  - Scheme matrix: 15,876 cases (9 header spellings x 7 schemes x 14 token shapes x 6 continuation
    forms x LF/CRLF/CR). Every token is gone, every raw text is refused, and every output is certified
    and idempotent. In 3,024 cases the wrapped token is itself a value-required keyword (`key`, `secret`,
    `password`, `community`). There the producer's raw-line fail safe also takes the next line's first
    word (over-redaction, listed below).
  - Differential against round 3 (`b07fff18`): 0 changed outputs over 17,780 string literals of every
    redaction-related test file, 13 tracked capture files, and the engine's synthetic collection (96
    files). `redact_snapshot` of the golden and sample snapshots is byte-identical to round 3.

## What changed downstream

- **Golden and sample: byte-identical by construction.** Neither runs with `--redact` or
  `--redact-collection`, and no module or import was added. The `bisect` standard-library import in
  both files is the only new import.
- **Over-redaction on the golden and sample `--redact` outputs** (`redact_snapshot`, pure calls): the
  same as round 2.
  - Golden: 48 of 21,615 key and string leaves differ from main's redacted output; 50 strings carry a
    placeholder (main 33).
  - Sample: 195 of 111,523 leaves differ from main; 184 strings carry a placeholder (main 135). Two
    sample leaves now keep the word `via` that round 2 removed.
  - All of it is engine-authored prose. Both results certify.
- **Ordinary show and configuration output** (the round-2 review's 33 files): round 3 changes 21 lines,
  main changes 36. Only three kinds of line differ from main:
  - `set snmp trap-group <redacted>`: the trap-group name is the trap community.
  - The NX-OS rmon defaults lose the trap community `public` and nothing else.
  - `show key chain` loses `"(not displayed)"`.
- **The engine's synthetic collection** (the golden input, 1,052 lines): main changes 4 lines, round 3
  changes 5, the same five as round 2. All 96 captures certify.
- **The corpus's 42 re-pinned expectations:**
  - The AireOS RADIUS/TACACS+ port is kept now.
  - The rmon description and owner are kept.
  - A qualifier that ends a wrapped clause is now redacted too (`ip ospf message-digest-key 1
    <redacted>` / `<redacted>`, `snmp-server host 10.1.1.1 <redacted>` / ...). This is the R3 rule,
    fail safe.
  - Misaligned synthetic table rows also lose the neighbouring cell that overlaps the credential
    column.
- **Other redaction test files.** 2,085 string literals from the ten other files were collected by AST
  and run through round 2 and round 3. Five outputs differ, all of them docstrings or a test label.
  This check found, and round 3 fixed, a `.pgpass` rule that had read a MAC address as a password line.
- **Performance** (pure calls, keyword-dense text; this host was noisy):
  - About 120-160 us per line for the scrub and 100-140 us per line for the verifier, against round 2's
    85-155 and 75-135 on the same text and the same host.
  - A 20,000-keyword single line now takes 0.3 s and grows linearly. Round 2 took 1.3 s for 5,000
    keywords and grew quadratically.
  - `redact_snapshot` of the sample takes about 2.5 s.

## Residual limits (documented, not closed)

1. **A credential spelled exactly like structure** survives:
   - a word of the closed allowlist in a tail;
   - a HARD stop of its family (`prefer`, `required`, `ascii` after `key config-key`, ...);
   - an exact keyword or command word where a wrapped value would stand
     (`snmp-server community` / `KEY RO`);
   - a slot operand;
   - a punctuation-only secret.

   A secret spelled like a qualifier or a soft stop word is now redacted where it ends its clause (R3).
2. **Kw-less positional values** outside the closed forms are caught only if high-entropy. The closed
   forms are the four show tables, the strict generic header, CSV, chap-secrets, `.pgpass`, the argv
   list, net-snmp argument vectors, `usmUser` and `smuxpeer`, and an expect `send` after a password
   prompt. Anything else, such as an unknown vendor table whose header is not strict, or a free-form note
   without a prose anchor, is not. In particular:
   - a non-net-snmp tool's own options (Nagios `check_snmp -C`, a vendor CLI);
   - an SNMP vector with no version, level, protocol or key option, outside a listed tool or directive;
   - a vector cut by a terminal wrap (an argv operand is read on its own line only).
3. **High entropy is a heuristic.** These are missed:
   - a 24-31 character random token split by `/` into short segments;
   - a low-entropy pasted secret;
   - a hex secret under a digest- or identifier-named snapshot key.
4. **Over-redaction is real.** See "What changed downstream".
   - Engine prose in `--redact` deliverables.
   - Show-output legends, BGP/Junos policy communities, public keys, labelled hashes in show tables and
     session IDs.
   - A qualifier that ends a wrapped clause, and the next line's first word after a clause that really
     ends in a qualifier.
   - The neighbour cell of a misaligned table row.
   - On a line read as an SNMP vector, any `-c`/`-A`/`-X` operand: `-X DES` in net-snmp-create-v3-user,
     or another tool's `-c` beside a stray `-v 1` (`lsof -v 1 -c snmpd`).
   - After an authorization scheme that ends its line, the next line's first token, whatever it is
     (`Authorization: Basic` / `Host: ...`). When that token is itself a value-required keyword, the next
     line's first word as well (the producer's raw-line fail safe).
   - A base64-looking line after a PuTTY body.
   - `--no-collect` re-analysis of a scrubbed folder loses those values.
5. **Terminal wraps.**
   - A wrap takes one token, or one token before a clause-trailing word.
   - It does not chain through a lone placeholder line unless the next token holds letters and digits.
   - A JSON key, colon and value on three lines is not followed by the producer; the verifier refuses
     it.
   - **Producer-only fail-safe.** In some wraps the producer reads the clause from the line as it was
     before its own scrub: when the scrub replaced the keyword (inside a credential block or a table
     cell), or replaced the qualifier at the end of the line (R3). The verifier cannot see that clause
     on the output and does not demand the next value. There the guarantee is the producer's alone.
6. **Shareable artifacts** keep their line-start, value-only scan plus PEM. The sweep closes residue
   there; the verifier does not re-detect it.
7. **Captures scrubbed by an older build** cannot be repaired. Re-collect, or hand-scrub the lines the
   verifier names.
8. **W58r2 coupling.** `evidence_retention` (not on `main`) fingerprints `_INLINE_SECRET_RES`, which now
   holds the round-3 grammar, so the retention digest changes on merge. Exact-head hosted CI on the
   merged result is required.

## Not verified

- **No pytest, no engine run, no build** (owner GITHUB-ONLY rule). The test module was AST-checked and
  linted. Every assertion in it was re-computed with the production functions in a scratch folder by
  hand-restated checks. It has never executed as a test.
- **The other redaction test files** were checked only by the literal differential above, not
  re-computed assertion by assertion.
- **Round 4's three new test functions** were re-computed once by executing their extracted statement bodies
  as scratch code (no pytest, no import of the test module). The changed pins and corpus checks were
  restated by hand.
- **The full `--redact` pipeline** (HTML/XLSX/DOCX certification) was not run. Only `redact_snapshot`,
  the snapshot verifier and the raw-capture path were exercised by pure calls.
- **Real client captures.** Every input here is synthetic. The round-2 review's corpora were re-run
  through its own harness, not re-derived.
- **Hosted CI** on every supported interpreter (3.10 to 3.14) and both platforms is required before
  merge.
