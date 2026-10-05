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
