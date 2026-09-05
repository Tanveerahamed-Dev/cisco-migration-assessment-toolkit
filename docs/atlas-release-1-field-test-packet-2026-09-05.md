# Atlas Release 1 Windows x64 field-test packet

Status: external/physical evidence template. Empty fields remain **not verified**; do not convert this document into a pass by filling it with agent assertions.

## Exact candidate identity

- Version/tag: `null`
- Source commit/tree: `null` / `null`
- Portable ZIP SHA-256: `null`
- Member-manifest/SBOM/provenance digests: `null` / `null` / `null`
- Authenticode per-member publisher/timestamp records and publisher set: `null`
- Test operator and managed-device asset reference: `null` / `null`

## Required physical sequence

1. Reverify the ZIP and every embedded member before extraction. Record the verifier receipt.
2. Verify every `.exe`, `.dll`, and `.pyd` with Windows Authenticode policy and record each member's publisher, signature, timestamp subject, and verification result. `Atlas.exe` and every member newly signed by this release lane must use the selected trusted RSA identity plus `/fd SHA256 /tr <RFC3161 URL> /td SHA256`; preserved vendor-signed runtime members retain their own independently verified publisher/timestamp evidence rather than being falsely relabelled as the Atlas publisher. A self-signed test is not acceptable release evidence. Microsoft documents the signing/timestamp options and explains why timestamping matters: [SignTool](https://learn.microsoft.com/en-us/windows/win32/seccrypto/signtool), [Authenticode timestamping](https://learn.microsoft.com/en-us/windows/win32/seccrypto/time-stamping-authenticode-signatures).
3. On a clean Windows 11 x64 device with Smart App Control enforcement recorded, test the exact downloaded candidate and the exact USB copy. Smart App Control can supersede reputation checks and applies to executable files beyond browser downloads; FAT/exFAT is not an unsigned bypass: [SmartScreen reputation](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation), [Smart App Control](https://learn.microsoft.com/en-us/windows/apps/develop/smart-app-control/overview).
4. Export the applicable AppLocker/App Control policy and record the exact allow/block result. Prefer a publisher rule for signed updates; an unsigned/hash rule is exact-version maintenance, never a broad allow rule for a user-writable USB path. Confirm that `Atlas.exe` exposes populated `OriginalFilename`, `ProductName`, and version resources before attempting a FilePublisher rule: [AppLocker rules](https://learn.microsoft.com/en-us/windows/security/application-security/application-control/app-control-for-business/applocker/working-with-applocker-rules), [App Control rule selection](https://learn.microsoft.com/en-us/windows/security/application-security/application-control/app-control-for-business/design/select-types-of-rules-to-create).
5. On a host with Python/pip absent and its NIC disconnected, run `Atlas.exe --selftest`, `--version`, `--run-engine --help`, and the loopback HTTP/API/SPA smoke. Confirm the Atlas PID listens only on IPv4/IPv6 loopback.
6. Repeat from at least two drive letters and a non-ASCII Windows profile/install path, at 100% and 150% display scaling.
7. Run demo, hostile synthetic, and saved offline-capture flows. Produce the complete registry-owned artifact family, then run redaction and exact manifest verification. Record all `NOT ASSESSED`, warnings, omissions, and operator corrections.
8. Exercise a disposable near-full volume and a read-only/write-locked target. Atlas must refuse loudly without changing the active application or database.
9. Interrupt the update after staging, data movement, old-tree rename, and new-tree activation. Re-run recovery after every interruption. Require a complete old or new tree, byte-identical client `data\`, and no mixed runtime.
10. Interrupt a database write on disposable evidence, confirm corruption refusal, restore the verified backup, and reconcile campaigns/snapshots/executions/receipts. Exercise explicit application rollback; preserve any newer database before restoring the pre-update copy.
11. Enable BitLocker To Go on the actual removable drive, store recovery information away from the drive, unlock it on another authorized managed machine, and perform a recovery drill. Microsoft supports NTFS/FAT/FAT32/exFAT removable data drives but treats recovery custody as a separate control: [BitLocker FAQ](https://learn.microsoft.com/en-us/windows/security/operating-system-security/data-protection/bitlocker/faq), [BitLocker configuration](https://learn.microsoft.com/en-us/windows/security/operating-system-security/data-protection/bitlocker/configure).
12. Before any live collection, obtain the AAA owner's confirmation that the 2026-07-05 credential was rotated. Then require an explicit operator action and a dedicated read-only account; network enablement alone is not collection authority.
13. A field operator records acceptance/PIR for this exact bounded pilot. This is one pilot, not general qualification, publication, adoption, or GA.
14. Before publishing the new portable ZIP, obtain a qualified redistribution review for its bundled IEEE-derived OUI registry and Cisco bulletin-derived lifecycle facts. These source/pack bytes already exist in the intentionally public repository and earlier public wheel/source assets; this gate neither makes them private nor declares that earlier distribution approved. The review must decide the new portable notice/set and identify any remediation required for existing public assets. IANA registry data is documented as CC0, but that does not decide the other datasets or the proprietary product's channel decision. Record the exact reviewed pack hashes and outcome; a draft candidate is not public-distribution approval.

## Illustrative field worksheet (not a gate receipt)

The JSON below is a note-taking shape only. No tracked parser, schema, signature policy, or release
consumer treats it as authority. The portable qualification receipt keeps every field activity in
its closed `external_pending` list, and an accountable release decision must inspect the underlying
records for the exact candidate. Do not relabel this worksheet as machine-validated evidence.

```json
{
  "schema": "atlas.portable-physical-qualification/1",
  "candidate": null,
  "operator": null,
  "managed_device_policy_evidence": null,
  "authenticode": null,
  "smartscreen_smart_app_control": null,
  "applocker_app_control": null,
  "python_absent": null,
  "internet_absent_loopback_only": null,
  "drive_and_unicode_matrix": null,
  "display_scaling": null,
  "full_and_read_only_media": null,
  "update_interruptions": null,
  "database_recovery_and_rollback": null,
  "bitlocker_to_go_and_recovery": null,
  "aaa_rotation_confirmation": null,
  "independent_human_peer_review": null,
  "operator_acceptance": null,
  "third_party_dataset_redistribution_legal_review": null,
  "field_qualified": false
}
```

Final public publication remains blocked while any required underlying record is missing/failing or while independent human review is absent; the illustrative worksheet values themselves have no authority. Owner approval, agent review, green CI, an admin merge, hashes, or GitHub attestations cannot substitute for those facts. The v1 candidate also has no supported public-promotion lane.
