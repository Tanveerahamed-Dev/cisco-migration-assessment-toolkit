# W60: the redaction credential grammar and its verifier (2026-10-09)

**This was a privacy defect in shipped redaction.** `Atlas.exe --redact-folder` (whose output is
meant to be shareable), `--redact-collection` and AssessHub ingest scrub raw captures with
`cisco_toolkit.html.redact_collection_dir`. That scrub left real credentials in place for a whole class
of configuration lines, and the independent verifier,
`webapp.backend.redaction_verify.verify_collection_secret_scrub`, certified those captures as
scrubbed. The same grammar (`_redact_config_values`) also feeds `redact_snapshot` and the `--redact`
workbook, so `--redact` deliverables carried the same residue wherever such a line reached them. Treat
any collection or `--redact` deliverable produced before this change as not credential-safe until it
has been scrubbed and verified again with this build (see "Captures scrubbed by an older build").

Branch `claude/w60-redaction-grammar` (board row W60). Static and pure-function evidence only: no test,
build or engine run.

## The defect

The scrub was a deny-list of `keyword + optional type digit + ONE token` patterns. It replaced the
token right after the keyword, even when that token was a **qualifier**. The credential then survived
one token further on. Separately, several value-bearing forms had no pattern at all. The verifier's
rule was "the first token after a recognised keyword is the placeholder", so it certified every line
in the first group, and it never looked at the second.

Every line below was produced by the real `redact_collection_dir` and checked by the real
`verify_collection_secret_scrub` in a scratch folder. The synthetic credentials are fake.

| Input line | Before (`origin/main` 6390b66c), certified | After this change |
|---|---|---|
| `enable password level 15 Plain99pw` | `enable password <redacted> 15 Plain99pw` | `enable password level 15 <redacted>` |
| `enable password level 15 0 Plain99pw` | `enable password <redacted> 15 0 Plain99pw` | `enable password level 15 0 <redacted>` |
| `enable secret level 15 0 Plain99pw` | `enable secret <redacted> 15 0 Plain99pw` | `enable secret level 15 0 <redacted>` |
| `username admin secret sha512 $6$...` (EOS) | `username admin secret <redacted> $6$...` | `username admin secret sha512 <redacted>` |
| `config wlan security wpa akm psk set-key ascii Wlc99psk 1` | `... set-key <redacted> Wlc99psk 1` | `... set-key ascii <redacted> 1` |
| `wireless security wpa psk set-key ascii 0 Wlc99psk` (C9800) | `... set-key <redacted> 0 Wlc99psk` | `... set-key ascii 0 <redacted>` |
| `Enable password is Hunter2pw` | `Enable password <redacted> Hunter2pw` | `Enable password is <redacted>` |
| `SNMP community string : Hunter2pw` | `SNMP community <redacted> : Hunter2pw` | `SNMP community string : <redacted>` |
| ` local-user admin password cipher Hw99pw` (Huawei) | `... password <redacted> Hw99pw` | `... password cipher <redacted>` |
| ` super password level 15 cipher Hw99pw` (Huawei) | `... password <redacted> 15 cipher Hw99pw` | `... level 15 cipher <redacted>` |
| ` snmp-agent community read Huawei99` (Huawei) | `... community <redacted> Huawei99` | `... community read <redacted>` |
| ` key config-key password-encrypt Master99` | ` key <redacted> password-encrypt Master99` | ` key config-key password-encrypt <redacted>` |
| ` ip nhrp authentication Dmvpn99` | unchanged (no pattern) | ` ip nhrp authentication <redacted>` |
| ` ip nhrp authentication 7 0822455D0A16` | unchanged | ` ip nhrp authentication 7 <redacted>` |
| `snmp-server host 192.0.2.10 public` | unchanged | `snmp-server host 192.0.2.10 <redacted>` |
| ` snmp-server host 10.1.1.1 traps Comm99v1` | unchanged | ` snmp-server host 10.1.1.1 traps <redacted>` |
| ` path scp://admin:Passw0rd99@10.1.1.1/cfg` | unchanged | ` path scp://admin:<redacted>@10.1.1.1/cfg` |
| `  enrollment url http://ca:Ca99pw@10.1.1.1/` | unchanged | `  enrollment url http://ca:<redacted>@10.1.1.1/` |
| `  cli copy running-config ftp://u:Kr99pw@1.1.1.1/b.cfg` | unchanged | `  cli copy running-config ftp://u:<redacted>@1.1.1.1/b.cfg` |
| ` key-octet-string 0123...CDEF cryptographic-algorithm AES_128_CMAC` | unchanged | ` key-octet-string <redacted> cryptographic-algorithm AES_128_CMAC` |
| ` key-octet-string 7 075E...4D cryptographic-algorithm AES_128_CMAC` | unchanged | ` key-octet-string 7 <redacted> cryptographic-algorithm AES_128_CMAC` |
| ` ospf authentication-mode md5 1 cipher Hw99ospf` (Huawei) | unchanged | `... md5 1 cipher <redacted>` |
| ` ospf authentication-mode md5 1 plain Hw99ospf` (Huawei) | unchanged | `... md5 1 plain <redacted>` |

Every "after" line is certified, and every cleartext input line is now refused by the verifier. The
"before" column was certified in every row. Other rows from the same probe set behave the same way:
SNMPv3 `auth`/`priv` passwords, `wpa-psk`, HSRP/VRRP/GLBP text keys, Huawei `shared-key cipher` and
`usm-user`, and IOS-XR `key-string password`.

## The grammar (producer)

`cisco_toolkit/html.py :: _REDACT_SECRET_RES` is now a table of **keyword families**. Each family is
KEYWORD, then a QUALIFIER RUN, then the VALUE (`_redact_family`):

- **The qualifier run is per family and is consumed atomically.** It is captured inside a lookahead
  and re-matched by a backreference, which is Python 3.10's spelling of an atomic group. Examples:
  `level N`, type digits, `sha512`/`scrypt`/hash labels, `ENC`, `encrypted`/`clear`,
  `cipher`/`plain`/`simple`/`irreversible-cipher`, `ascii`/`hex`, `read`/`write`/`create`,
  `vrf X`, `traps`/`informs`, `version 1|2c`, key IDs, and the prose separators `:`, `=`, `=>`
  and `is`. The engine can never hand a qualifier back to become the value. A qualifier also counts at
  the end of a line, so `key 1` under a keychain or `ntp trusted-key 1` is a key ID and is left alone.
- **The value is the first token after the run.** It is a quoted string or a bare token, and is
  replaced whole.
- **Structural follow-words end the grammar.** Where the value would stand, these mean there is no
  credential: `key chain X`, `password encryption aes`, `Key name:` (any `Label:` token),
  `key id is 1`, `crypto key generate rsa`, `ntp server X key 1 prefer`, `ssh key rsa 2048`,
  `authentication-mode hwtacacs`, `ip ssh server algorithm authentication publickey password keyboard`,
  and English prose (`password for user`, `Do not share your password with anyone`). EOS
  `ssh-key ssh-rsa <public key>` is not a secret.
- **Families.**
  - Password forms: `password`/`passwd`/`secret`/`passphrase`, with every compound such as `area-`,
    `domain-`, `hello-`, `lsp-`, `encrypted-` and `webauth-http-`. ASA puts `encrypted`/`pbkdf2`
    after the value.
  - SNMP: `snmp-server community` in every SNMP context (IOS/NX-OS/ASA, Junos `set snmp`, Huawei
    `snmp-agent`, AireOS `config snmp community`, the Junos line-start `community X {`, and the show
    forms `SNMP community string : X` and `Community name: X`); the positional trap-host community
    `snmp-server host H [vrf X] [traps|informs] [version 1|2c] <C>`; SNMPv3 `auth`/`priv`; AireOS
    `v3user`; Huawei `securityname`.
  - Keys: TACACS+/RADIUS keys, `key-string`, `key-octet-string`, `pre-shared-key`, Huawei
    `shared-key`, MACsec `cak`/`ckn`, and the bare `key` family (keychains, `authentication-key`,
    `message-digest-key`, `crypto isakmp key`, `failover key [hex]`, `show key chain`'s
    `key 1 -- text "X"`).
  - Wireless: `wpa-psk`/`wpa2-psk`, and AireOS/C9800 `set-key`.
  - Authentication modes: NHRP, HSRP/VRRP/GLBP (IOS and EOS `peer`), the NX-OS line-start
    `authentication text`, Huawei `[area-|domain-]authentication-mode` and `privacy-mode`, OSPFv3
    `authentication ipsec spi N sha1|md5`, EIGRP named-mode `authentication mode hmac-sha-256`, and
    `show standby`'s `Authentication text, string "X"`.
  - Vendor and URL forms: AireOS RADIUS/TACACS+ `add` and `mgmtuser`/`netuser`; FortiGate
    `set <closed attribute set> [ENC]`; URL userinfo (`scheme://user:<redacted>@host`, keeping the
    user and taking the password up to the last `@`).
- **Line-bounded.** Every family uses `[ \t]`, never `\s`. The old patterns crossed a newline and
  redacted the first token of the next line (`ntp trusted-key 1` followed by a newline).
- **Speed.** The text is processed one `\n` line at a time, and only lines that name a family keyword
  are run through the table (`_REDACT_LINE_PREFILTER`). Joining on `\n` is byte-exact; `\r` and
  surrogate-escaped bytes stay inside their line.

## The verifier

`webapp/backend/redaction_verify.py` restates the grammar independently (`_CRED_FAMILIES`). It does not
import the producer, and the producer does not import it. It reads each line as KEYWORD, QUALIFIER
RUN, VALUE, TAIL.

**Raw captures** (`verify_collection_secret_scrub`, via `_raw_capture_credential_findings`): every
family anchor anywhere in the line, plus URL userinfo.

- **Value:** a recognised value that is not the placeholder is `credential value`.
- **Tail (closed allowlist):** after the placeholder, every token must be one of:
  - a structural follow-word (`_CRED_TAIL_WORDS`);
  - a slot keyword plus its one operand (`_CRED_TAIL_SLOTS`: `level`, `privilege`, `role`, `view`,
    `ipv6`, `address`, `udp-port`, `version`, `authorization`, `cryptographic-algorithm`, ...);
  - an address or synthetic pseudonym;
  - another placeholder;
  - a token inside another credential clause on the same line whose value is the placeholder
    (`password 0 <redacted> secret 0 <redacted>`);
  - one positional ACL after `RO|RW` or `ipv6 <nacl>`;
  - a family's own integer (a community ACL number, the trailing NTP or `set-key` WLAN digit).

  Anything else is `credential residue after the placeholder`. This is an allowlist, not a denylist of
  secret shapes. An unknown follow-word **refuses**, which is the deliberate direction: a refused scrub
  is re-checked by a person, a certified leak is not.
- **Closed world:** the scrub is the only author of the placeholder in a raw capture. A placeholder that
  no clause explains is `placeholder outside the credential grammar`.
- **Free text:** banner bodies (tracked by delimiter, bounded at 400 lines when the delimiter never
  closes), `description`/`remark`/`alias`/`comment` lines, `!`/`#` comments and syslog records
  (`%FAC-N-MNEMONIC:`) keep the value check and the closed-world check but skip the tail allowlist,
  because English follows a credential word there.

**Shareable artifacts** (`_scan_text`: snapshot strings, OOXML text, HTML): only the line-start anchors
the module always checked, now with the same qualifier/stop grammar for the VALUE (`artifact` anchors).
No tail check and no closed world here, because authored prose, generated code and free-text device
fields share these surfaces. A description beginning `password reset ...` is redacted by the producer
and must not refuse a deliverable. The producer's grammar is what closes the residue class on these
surfaces. The strict FortiGate whole-value rule is unchanged on both paths.

## Corpus and pins

`tests/fixtures/redaction_grammar_corpus.json` holds 183 must-redact lines and 102 must-keep lines. The
must-redact lines cover IOS/IOS-XE, NX-OS, ASA, AireOS and C9800 WLC, IOS-XR, Arista EOS, Junos,
FortiGate, Huawei and show-output prose. Each carries its exact expected output and the fake secrets
that must not survive. `tests/test_redaction_grammar_corpus.py` drives them through the real
`redact_collection_dir` and `verify_collection_secret_scrub`:

- the verifier refuses the raw line and certifies the scrubbed line;
- it refuses the scrubbed line with `Leak99tail` inserted after the placeholder, which proves the
  verifier parsed that family rather than passing it by default;
- the scrub is idempotent;
- every reported leak line stays in the corpus;
- every verifier family is exercised by at least one corpus line, with the speed filters on.

**False-positive pins** (must-keep, byte-identical and certified):

- show-output labels: `Key name: TP-self-signed-1234`, `Key Data:`, `Youngest key id is 1`,
  `Password encryption: enabled`, `Last key change: never`, `Key: U - Unicast, B - Broadcast`
  (`show storm-control`), `Community: 65000:100 no-export` (`show ip bgp`), `Unknown community name`;
- configuration: `service password-encryption`, `password encryption aes`, `key chain X`, `key 01`,
  `mka pre-shared-key key-chain KC`, `standby 1 authentication md5 key-chain X`, IBNS
  `authentication port-control auto` / `host-mode` / `order` / `priority`, `ntp trusted-key 1`,
  `ntp server X key 1 prefer`, `crypto key generate rsa`, `set community 65000:100 additive`,
  `send-community both`, `snmp-server host X version 3 priv user`, NX-OS `use-vrf` / `source-interface`
  host lines, Huawei `authentication-mode hwtacacs local`, FortiGate `set keylife 86400`;
- banner prose.

**Pre-existing exact pins re-checked by pure calls:** every exact `_redact_config_values` assertion in
`tests/test_redaction_secrets.py`, `tests/test_redact_corpus.py` and `tests/test_redact_collection.py`,
and the Atlas qualification's synthetic collection, give the same output as before. That includes
`pre-shared-key local <redacted>`, `key 7 <redacted>`, `... md5 7 <redacted>`,
`set passphrase <redacted>`, the CP1252 byte-fidelity capture and
`snmp-server community <redacted> RO`. No existing test expectation was edited.

## What changed downstream

- **Golden and sample: byte-identical by construction.** Neither `tests/test_pipeline_golden.py ::
  _golden` nor `webapp/sample_data/build_sample.py` runs with `--redact` or `--redact-collection`. No
  module was added, so the attestation module counts are unchanged, and no import was added.
- **The engine's synthetic collection** (`tests/synthetic_fixtures.write_collection`): the scrub
  changes the same 4 lines as before, and the new verifier certifies all 96 captures.
- **`--redact` deliverable prose.** `redact_snapshot` of the golden snapshot differs from the old
  output in 22 string leaves, and of the sample in 85. No key or list shape changes, and the credential
  scan of both results is clean. The differences are less over-redaction, for example
  `Password encryption service` (a CIS control title, formerly `Password <redacted> service`), BGP
  community prose, `send-community extended`, `authentication-key mismatch` and
  `pre-shared key or certificate`. A few prose words are redacted where the old grammar left a
  neighbour, for example `cleartext password: <redacted>`, where a finding names a local user after a
  colon.
- **Engine string constants** (27,893, a proxy for authored deliverable text): the new artifact scan
  flags 1, a docstring the old scan also flagged; the old scan flagged 2.
- **Performance** (pure-call timings on this workstation): `redact_snapshot` of the sample takes 2.3 s
  (was 2.8 s). On a synthetic 31 MB capture where a quarter of the lines are credential lines, the
  scrub takes 9.2 s (was 8.8 s) and the verifier 14.7 s (was 2.8 s, while checking far less).

## Residual limits

These are documented, not closed:

1. **Tabular show output** carries no keyword on the value line, so the grammar cannot see it. This
   was already true. Examples: NX-OS `show snmp community`, `show crypto isakmp key`, AireOS tables.
2. **Multi-line values.**
   - PEM bodies are not recognised (FortiGate `set private-key "-----BEGIN ..."` followed by lines).
     The verifier refuses the first line, which it already did.
   - IOS cleartext passwords containing spaces are only partly consumed. The verifier refuses unless
     the remaining word is itself a credential clause.
3. **Grammar ambiguity.**
   - A credential equal to a qualifier or stop word is not recognised: a single digit, `cipher`,
     `level`, `is`, `for`, ....
   - A purely numeric value directly after a bare `key` is read as a key ID (keychain `key 12345`,
     GRE `tunnel key 12345`).
   - The producer and the verifier read both of these the same way.
4. **Not modelled:**
   - EEM `action ... cli command "<text>"`;
   - OSPFv3 `encryption ipsec spi ... esp ... <KEY>`;
   - FortiGate `config system snmp community` / `set name "<community>"` (context-dependent).
     `set community` is not a FortiOS secret form, and the IOS route-map `set community` is
     deliberately left alone.
5. **Over-redaction kept:**
   - The Huawei v3 `securityname` (a user name) is redacted.
   - A prose word after `password`/`secret` that is not a stop word is still redacted.
6. **Fail-closed refusals.** An unlisted follow-word after a placeholder refuses the scrub
   verification. Two cases:
   - an IOS community ACL name without `RO`/`RW`;
   - a notification type missing from the list after a trap-host community.

   Extend `_CRED_TAIL_WORDS` / `_CRED_TAIL_SLOTS`, and add the corpus line, with the evidence.
7. **Shareable artifacts** keep their line-start, value-only scan: residue there is closed by the
   producer, not re-detected.
8. **Captures scrubbed by an older build.** The scrub cannot reconstruct a qualifier the old build
   overwrote. Re-running it leaves, for example, `enable password <redacted> 15 Plain99pw`; the new
   verifier refuses that file. Re-collect, or hand-scrub the named lines.
9. `webapp/backend/evidence_retention.secondary_credential_findings` is not on `main`, so it was not
   exercised here.

## Not verified

- No pytest, no engine run, no build. The new test module was AST-checked for collection sanity and
  linted, and its assertions were re-stated as pure calls in a scratch folder. It has never executed
  as a test.
- The full `--redact` pipeline (HTML/XLSX/DOCX certification) was not run. Only the snapshot path and
  the shareable-text scan were exercised by pure calls.
- Behaviour on real client captures is not measured. Every input here is synthetic.
- Hosted CI on every supported interpreter (3.10 to 3.14) is required before merge.
