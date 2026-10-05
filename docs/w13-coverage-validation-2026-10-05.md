# W13 coverage provenance and device rollups

Started from main `0568c7ac`. This source checkpoint implements G42/G12; runtime
validation, the hosted-built SPA, exact-head protected checks and a fresh unchanged
300 ms performance receipt are **not verified** yet.

The existing coverage owner now provides a pure exact-device/axis index and an
unpersisted fold. Duplicate identities, malformed identity rows, contradictory
states, mismatched dimension/source and nonboolean abstentions refuse admission.
The fold requires the complete matching axis universe, including all three core
axes. Fleet-only architecture abstentions never become a device row. No stored
matrix output, sample, golden or toolkit module was added or regenerated.

Device coverage retains `{axis,state}` and adds separately addressed dimension,
verdict-source and abstention facts. Inventory and the device page share the
worst-state and abstained-axis fold. Unknown devices remain bare; blind devices,
absent axes, failed phases and ambiguous joins remain withheld. An all-covered
fold and zero abstentions remain unverified because the existing matrix can emit
covered from silent source records. This scope exposes provenance and preserves
that defect boundary; it does not certify that capture or parse ran.

Independent source review caught an invalid limitation address, an enum-order
integration mismatch and the admission of a fleet-only architecture state under
a device. Those authoring defects were corrected before the checkpoint. Helper
matches return only fresh admitted scalar fields, avoiding unvalidated recursive
copies. New tests include producer controls, exact-identity mutations, full-axis
reconciliation, original-index custody, host/phase states and closed native/stock
shapes. Tests were authored for hosted execution; no local test, browser, SPA
build, benchmark or frozen smoke was run.

The closed schema adds only `CoverageStateFact`, `CoverageDimensionFact`,
`CoverageVerdictSourceFact` and `DeviceCoverageRollup`, and extends only
`CoverageItem`, `DeviceRow` and `DevicePage`. Its established keyword domain,
provider version, private resolver guard, transport list paths, limitation IDs
and counts remain fixed. OpenAPI types were regenerated through the offline
authoring exporter. The independently reviewed structural delta selects native
profile hashes:

- view: `f235a3e2299ce759cb7e217d460637d86621f604ab88cb55c8b107e0f5d4102b`
- list: `dad24260d96b9bd51f4426b98201c650f953a777db7305178e4aabba1d993476`

Targeted Ruff and frontend typechecking passed. The first direct two-file mypy
probe reported 82 errors; explicit identity type narrowing corrected the three
new index errors. The final working-source probe and an immutable `0568c7ac`
shadow-file baseline both report the same 79-error multiset in these nongated
modules. Both nonzero exits and the initial negative diagnostic are retained;
this is not a full-project type pass and does not replace the existing protected
mypy job. All required and applicable hosted
checks remain mandatory. The latency producer now additionally hashes the new
coverage owner; request shapes, timing arithmetic, runner and 300 ms threshold
are unchanged.

The first PR carries the W13 board row. A source-bound hosted frontend handoff
must be independently checked before importing its generated distribution;
bootstrap stale-dist failures remain evidence, not exemptions. On #599's owner
merge, save W13 at a clean commit and switch to W10b's independently split B3/A6
repairs and the C6 documentation correction. Then resume W13, then #593.
Release publication, qualification, signing, tags, deployment, devices and the vault are
outside this work.

## Bootstrap evidence and proof corrections

Draft #600 published bootstrap `2df3bb57` after index/stable-tree privacy,
every new commit message/per-parent patch and PR-body marker gates passed.
The complete hosted webapp run `37343049346` passed, including backend,
frontend unit/type/build, browser and Windows visual jobs. Protected distribution
job `111874671698` failed immutable-byte checks on stale tracked SPA output;
portable job `111874670995` also exited on regenerated frontend differences.
The old failure logs remain retained; neither is waived.

Before reading artifact receipts, independently selected producer `29516390`,
tree `1efd0590`, bootstrap head and all 144 Git input hashes. Hosted artifact
`11358808660` passes API/archive digest, the closed seven-file inventory, five
generated member hashes, source records and independently retrieved Node
24.19.0/npm 11.17.0 setup evidence. Archive SHA-256:
`4c60c670f0a77bbd6ab2953d60e72c23319e54f8fd5fc2abede0fd809b70bc17`,
552,136 bytes. It remains review input for that immutable bootstrap only;
it was not imported or transferred to the follow-up source.

Independent source review then found invalid mocked coverage rows (missing
required pointers and a parse/source/state mismatch) and a native parity gap
for the real coverage-list branch. Corrected fixtures keep three core-axis
abstentions inside a nine-axis denominator; architecture abstentions are fleet-only.
Additional real-list controls retain the list
validator for valid, withheld and hostile metadata. These proof corrections
require fresh hosted execution and a newly source-bound SPA before import;
the bootstrap passes do not certify them. Local targeted lint/typechecking
passes; runtime tests remain unverified on the correction.

Correction `281da097` obtained a fresh successful hosted frontend job
`111885233304` in run `37346164243`; frontend browser/Windows visual jobs also
passed. Independently selected tested producer `4920d7b2`, equal tree `ce9bee14`
and all 144 committed inputs before reading receipts. Artifact `11360228164`
passes API/archive SHA-256
`bf9ad6f36ba4f88a791e07a66eedcb6ccd49d9c3fc0241ddfeae6bc321ff9b29`,
552,136 bytes, the closed seven-file/five-member set, source records, member
hashes, privacy/index references and independently fetched Node 24.19/npm 11.17
job logs. The consumer's exact clean frontend inputs matched before import.
Imported only the five verified generated members and removed three obsolete
ordinary generated files inside the owned dist directory. The changed final
source requires a new hosted rebuild, all exact-head gates and a fresh 300 ms
receipt; no old acceptance or qualification is transferred.

## Current-main integration and preserved manual-run negatives

#599 owner-merged as `3f8ce101`. Integration merge `beaa9929` has parents
`2c3e955f` and `3f8ce101`; only NOW required manual resolution. Independent
Git-tree review confirms every other blob matches automatic parent selection,
all 441 Scope paths equal main, both parent handoff histories survive, W10 is
removed and W10b/W13 remain. The latest owner instruction requires #600 to
finish before W10b; old source receipts do not certify this integrated source.

The earlier manual run `37348127602` passed its performance job but failed the
distribution frontend test and Windows suite job. The latter's check annotation
reports hosted-runner communication loss; its suite step remained nonterminal
and logs returned 404 twice, so no complete test-assertion verdict is established.
The distribution log records a real pagination-test failure: the first coverage
page remained visible while the test timed out finding the parse-axis group.
Root cause is unconfirmed; observing mounted DOM before the reset/abort effect
settles is the leading timing hypothesis. Preserve the failing log and the
separate passing PR/frontend runs.

The test now awaits React mount/click work, holds the page response explicitly,
checks one exact device/pointer/offset request and an un-aborted signal, then
releases the response and retains all existing row, metadata and full-rollup
assertions. Default timeouts remain unchanged. This is a test-fixture correction,
not evidence that production pagination was defective. Targeted typechecking
passes; hosted runtime verification remains required on the new source.
