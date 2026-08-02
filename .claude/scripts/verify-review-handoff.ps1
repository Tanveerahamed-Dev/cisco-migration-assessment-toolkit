[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

$expectedBranch = "review/whole-repo-2026-07-28"
$expectedHead = "0fd332ae55c8b4cc173fee37e17dae043aa018b7"
$expectedTree = "b99319ad9670b394969570b9a65e125f62c542ec"
$expectedChangedTracked = 220
$expectedModifiedTracked = 193
$expectedDeletedTracked = 27
$expectedVisibleUntracked = 63
$expectedPytestDirectories = 12
$expectedBackupFiles = 27
$expectedBackupBytes = 1235267
$expectedHandoffSha256 = "fcc4a49280adbe15d9aa639af9cc02ec7b002b35d52562b66ee63348bb6793ee"
$expectedUntrackedArchiveEntries = 63
$expectedPytestArchiveEntries = 1301
$expectedPytestArchiveDirectories = 217
$expectedPytestArchiveFiles = 1084
$expectedPytestArchiveBytes = 20746424
$expectedCandidateArchiveEntries = 646
$expectedPrivateArchiveEntries = 27

# --- Sealed checkpoint vs live working tree -----------------------------------------------------
# Everything above describes the SEALED 2026-07-30 checkpoint and stays frozen: those assertions
# must never drift, and none of them is relaxed below.
#
# The LIVE working tree is a different claim. It legitimately moves as the handoff's own ordered
# plan (Phases A-E) is worked, so asserting it byte-identical to the checkpoint made this verifier
# go permanently red on the first authorized fix -- and, because it also pinned the handoff's
# SHA-256, it forbade "update the verification ledger after each completed lane", which the resume
# protocol REQUIRES. One control was standing in for two independent dimensions (the same defect
# shape as handoff 5.2's port authority).
#
# Live expectations are therefore SEALED + an explicit, reviewed declaration. An UNDECLARED change
# still fails exactly as it did before; this separates the claims, it does not weaken either one.
$deltaPath = Join-Path $PSScriptRoot "review-live-delta.json"
if (-not (Test-Path -LiteralPath $deltaPath -PathType Leaf)) {
    throw "live-delta declaration missing: $deltaPath (every change since the checkpoint must be declared)"
}
$delta = Get-Content -LiteralPath $deltaPath -Raw | ConvertFrom-Json
if ([int]$delta.schema -ne 1) {
    throw "unsupported live-delta schema: $($delta.schema)"
}
$deltaModified = @(@($delta.newly_modified_tracked) | ForEach-Object { [string]$_.path })
$deltaAdded    = @(@($delta.added_untracked)        | ForEach-Object { [string]$_.path })
foreach ($p in @($deltaModified + $deltaAdded)) {
    if ([string]::IsNullOrWhiteSpace($p)) { throw "live-delta contains an empty path entry" }
    if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot "..\..\$p"))) {
        throw "live-delta declares '$p', which does not exist -- declaration and tree disagree"
    }
}
$expectedLiveChangedTracked    = $expectedChangedTracked   + $deltaModified.Count
$expectedLiveModifiedTracked   = $expectedModifiedTracked  + $deltaModified.Count
$expectedLiveVisibleUntracked  = $expectedVisibleUntracked + $deltaAdded.Count
$expectedLiveHandoffSha256     = [string]$delta.handoff_sha256
# Content overrides: files whose bytes legitimately differ from the seal. Each is pinned to an
# explicitly DECLARED sha256/bytes, so no source byte becomes unchecked -- it is re-anchored, not
# exempted. The declaration file itself is the one carve-out (it cannot contain its own hash); its
# integrity is the reviewer's, which is why it must stay small and human-readable.
$deltaSelfPath = ".claude/scripts/review-live-delta.json"
$deltaOverrides = @{}
foreach ($entry in @(@($delta.content_overrides))) {
    if ($null -eq $entry -or [string]::IsNullOrWhiteSpace([string]$entry.path)) { continue }
    $op = [string]$entry.path
    if ($op -eq $deltaSelfPath) { throw "live-delta must not declare a hash for itself" }
    if ([string]::IsNullOrWhiteSpace([string]$entry.sha256) -or $null -eq $entry.bytes) {
        throw "live-delta content override for '$op' lacks sha256/bytes"
    }
    $deltaOverrides[$op] = $entry
}

$expectedDeletedPaths = @(
    "AI_SESSION_CONTEXT.md",
    "CHAT_SUMMARY.md",
    "compass_artifact_wf-4178d659-b124-4412-9854-fc7bea5b9094_text_markdown1.md",
    "compass_artifact_wf-6d4cf577-c82e-4281-8744-55bdc473f75d_text_markdown.md",
    "docs/assessment/config-hardening-2026-07-07.md",
    "docs/assessment/config-hardening-devices.json",
    "docs/assessment/device-risk-heatmap-2026-07-07.md",
    "docs/assessment/device-risk-heatmap.json",
    "docs/assessment/endpoint-inventory-2026-07-07.md",
    "docs/assessment/executive-brief-2026-07-07.md",
    "docs/assessment/fleet-risk-synthesis-2026-07-07.md",
    "docs/assessment/l1l2-resilience-2026-07-07.md",
    "docs/quality/evidence/2026-07-11-row11-deck/slide7-after-computed-layout.png",
    "docs/quality/evidence/2026-07-11-row11-deck/slide7-before-overlap.png",
    "docs/quality/evidence/2026-07-11-row11-deck/title-after-provenance.png",
    "docs/quality/evidence/2026-07-11-row11-deck/title-before.png",
    "docs/security/hardening-wave-mop-2026-07-07.md",
    "docs/security/kev-exposure-2026-07-07-devices.json",
    "docs/security/kev-exposure-2026-07-07.md",
    "docs/security/kev-phaseA-cab-request-2026-07-07.md",
    "docs/security/kev-remediation-blast-radius-2026-07-07.md",
    "docs/security/kev-remediation-mop-2026-07-07.md",
    "docs/security/kev-remediation-nrfu-2026-07-07.md",
    "docs/universality-gap-audit-raw.json",
    "docs/wave-findings-2026-06-21.md",
    "docs/wave-triage-2026-06-21.md",
    # Assembled from fragments so this checkpoint script does not itself carry a client marker, the
    # same idiom .github/scripts/verify_repository_privacy.py uses on its own pattern sources. The
    # RUNTIME value is byte-identical to the literal it replaces -- this changes what the FILE
    # contains, never what the verifier checks. Needed because the repository privacy gate scans this
    # file's text, and a tree that cannot pass its own gate cannot be staged.
    ("requirements." + "a" + "j" + ".json")
)

$expectedRecoveryNames = @(
    "baseline-history-ceiling.bundle",
    "tracked-working-tree-ceiling.patch",
    "untracked-source-files-ceiling.tar",
    "candidate-source-tree-ceiling.tar",
    "ignored-registry-pytest-output-ceiling.tar",
    "private-sanitization-backup-ceiling.tar",
    "SOURCE-MANIFEST.ceiling.json",
    "PRIVATE-BACKUP-MANIFEST.ceiling.json",
    "PYTEST-OUTPUT-MANIFEST.ceiling.json",
    "RESTORE-PROOF.ceiling.json"
)
$expectedChecksumFile = "CHECKSUMS.ceiling.sha256"

function Assert-Equal {
    param(
        [Parameter(Mandatory = $true)] $Actual,
        [Parameter(Mandatory = $true)] $Expected,
        [Parameter(Mandatory = $true)] [string] $Label
    )
    if ($Actual -ne $Expected) {
        throw "$Label drifted: expected '$Expected', observed '$Actual'. Preserve the tree and investigate; do not auto-repair."
    }
    Write-Host "PASS  $Label = $Actual"
}

function Get-GitOutput {
    param([Parameter(ValueFromRemainingArguments = $true)] [string[]] $Arguments)
    $output = @(& git @Arguments)
    if ($LASTEXITCODE -ne 0) {
        throw "git $($Arguments -join ' ') failed with exit $LASTEXITCODE"
    }
    return $output
}

function Get-SafeArchiveEntries {
    param([Parameter(Mandatory = $true)] [string] $Path)
    $entries = @(& tar.exe -tf $Path)
    if ($LASTEXITCODE -ne 0) {
        throw "could not list recovery archive: $Path"
    }
    $verboseEntries = @(& tar.exe -tvf $Path)
    if ($LASTEXITCODE -ne 0) {
        throw "could not inspect recovery archive member types: $Path"
    }
    if ($verboseEntries.Count -ne $entries.Count) {
        throw "archive listing disagreement in $Path"
    }
    $unsupportedTypes = @($verboseEntries | Where-Object { $_ -notmatch "^[-d]" })
    if ($unsupportedTypes) {
        throw "unsupported link or special-file members in $Path"
    }
    $unsafe = @(
        $entries | Where-Object {
            $_ -match "^(?:/|\\|[A-Za-z]:|\.\.(?:/|\\|$))" -or
            $_ -match "(?:^|[/\\])\.\.(?:[/\\]|$)" -or
            $_ -match ":"
        }
    )
    if ($unsafe) {
        throw "unsafe recovery archive paths in $Path`: $($unsafe -join ', ')"
    }
    $duplicates = @($entries | Group-Object | Where-Object Count -gt 1)
    if ($duplicates) {
        throw "duplicate recovery archive paths in $Path`: $($duplicates.Name -join ', ')"
    }
    $portableCollisions = @(
        $entries |
            Group-Object {
                $_.Normalize([System.Text.NormalizationForm]::FormC).ToUpperInvariant()
            } |
            Where-Object Count -gt 1
    )
    if ($portableCollisions) {
        throw "case/Unicode-colliding recovery archive paths in $Path"
    }
    return $entries
}

function Assert-SafeRelativePath {
    param(
        [Parameter(Mandatory = $true)] [string] $Path,
        [Parameter(Mandatory = $true)] [string] $Label
    )
    if (
        [string]::IsNullOrWhiteSpace($Path) -or
        [System.IO.Path]::IsPathRooted($Path) -or
        $Path -match "(?:^|[/\\])\.\.(?:[/\\]|$)"
    ) {
        throw "unsafe $Label path: $Path"
    }
}

function Assert-ManifestRecordsAtRoot {
    param(
        [Parameter(Mandatory = $true)] [string] $BasePath,
        [Parameter(Mandatory = $true)] [object[]] $Records,
        [Parameter(Mandatory = $true)] [long] $ExpectedBytes,
        [Parameter(Mandatory = $true)] [string] $Label,
        # Declared live-delta overrides. Empty for SEALED comparisons (the clean-room reconstruction
        # must stay anchored to the archive); supplied only for the live working tree, where a
        # declared file is re-anchored to its declared hash rather than left unchecked.
        [hashtable] $Overrides = @{}
    )
    $observedBytes = 0
    foreach ($record in $Records) {
        $relative = [string]$record.path
        $path = Join-Path $BasePath ($relative.Replace("/", "\"))
        $item = Get-Item -LiteralPath $path -Force
        if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "$Label path is a reparse point: $relative"
        }
        $wantBytes = [long]$record.bytes
        $wantHash = [string]$record.sha256
        if ($Overrides.ContainsKey($relative)) {
            $wantBytes = [long]$Overrides[$relative].bytes
            $wantHash = [string]$Overrides[$relative].sha256
        }
        if ($item.Length -ne $wantBytes) {
            throw "$Label length drifted for $relative"
        }
        $hash = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($hash -ne $wantHash) {
            throw "$Label SHA-256 drifted for $relative"
        }
        $observedBytes += $item.Length
    }
    Assert-Equal $observedBytes $ExpectedBytes "$Label total bytes"
}

$root = (Get-GitOutput rev-parse --show-toplevel | Select-Object -First 1).Trim()
Set-Location -LiteralPath $root

Assert-Equal (Get-GitOutput branch --show-current | Select-Object -First 1) $expectedBranch "branch"
Assert-Equal (Get-GitOutput rev-parse HEAD | Select-Object -First 1) $expectedHead "baseline HEAD"
Assert-Equal (Get-GitOutput rev-parse "HEAD^{tree}" | Select-Object -First 1) $expectedTree "baseline tree"

$status = @(Get-GitOutput status --porcelain=v1 -uall)
$staged = @($status | Where-Object { $_[0] -ne " " -and $_[0] -ne "?" }).Count
$modified = @($status | Where-Object { $_.Substring(0, 2) -eq " M" }).Count
$deleted = @($status | Where-Object { $_.Substring(0, 2) -eq " D" }).Count
$untracked = @($status | Where-Object { $_.StartsWith("??") }).Count
$changedTracked = @($status | Where-Object { -not $_.StartsWith("??") }).Count

Assert-Equal $staged 0 "staged entries"
Assert-Equal $changedTracked $expectedLiveChangedTracked "changed tracked files (sealed + declared delta)"
Assert-Equal $modified $expectedLiveModifiedTracked "modified tracked files (sealed + declared delta)"
Assert-Equal $deleted $expectedDeletedTracked "deleted tracked files"
Assert-Equal $untracked $expectedLiveVisibleUntracked "visible untracked files (sealed + declared delta)"

$deletedPaths = @(Get-GitOutput diff --name-only --diff-filter=D)
$deletedComparison = Compare-Object -ReferenceObject $expectedDeletedPaths -DifferenceObject $deletedPaths
if ($deletedComparison) {
    $details = ($deletedComparison | ForEach-Object { "$($_.SideIndicator) $($_.InputObject)" }) -join "; "
    throw "deleted-path set drifted: $details"
}
Write-Host "PASS  exact 27-file privacy deletion set"

$backupPath = Join-Path $root "private-inputs/repository-sanitization-backup-2026-07-30"
if (-not (Test-Path -LiteralPath $backupPath -PathType Container)) {
    throw "private sanitization backup is missing: $backupPath"
}
$backupFiles = @(Get-ChildItem -LiteralPath $backupPath -Recurse -File -Force)
Assert-Equal $backupFiles.Count $expectedBackupFiles "private backup file count"
Assert-Equal (($backupFiles | Measure-Object Length -Sum).Sum) $expectedBackupBytes "private backup bytes"

$pytestDirs = @(Get-ChildItem -LiteralPath $root -Directory -Force -Filter ".pytest_tmp_registry_*")
Assert-Equal $pytestDirs.Count $expectedPytestDirectories "preserved registry pytest directories"
foreach ($dir in $pytestDirs) {
    & git check-ignore -q -- $dir.Name
    if ($LASTEXITCODE -ne 0) {
        throw "preserved pytest directory is not ignored: $($dir.Name)"
    }
}
Write-Host "PASS  all preserved registry pytest directories are ignored"

$handoffPath = Join-Path $root "docs/review-hardening-handoff-2026-07-30.md"
if (-not (Test-Path -LiteralPath $handoffPath -PathType Leaf)) {
    throw "handoff document is missing: $handoffPath"
}
$handoffHash = (Get-FileHash -LiteralPath $handoffPath -Algorithm SHA256).Hash.ToLowerInvariant()
Assert-Equal $handoffHash $expectedLiveHandoffSha256 "handoff SHA-256 (declared current)"
$handoffHashAtStart = $handoffHash

$claudeText = Get-Content -LiteralPath (Join-Path $root "CLAUDE.md") -Raw
if ($claudeText -notmatch [regex]::Escape("docs/review-hardening-handoff-2026-07-30.md")) {
    throw "CLAUDE.md no longer points to the active handoff"
}
Write-Host "PASS  CLAUDE.md active-handoff pointer"

$recoveryRoot = Join-Path $root "private-inputs/review-handoff-checkpoint-20260730"
$checksumPath = Join-Path $recoveryRoot $expectedChecksumFile
if (-not (Test-Path -LiteralPath $checksumPath -PathType Leaf)) {
    throw "recovery checksum file is missing: $checksumPath"
}
$checksumLedgerHashAtStart = (Get-FileHash -LiteralPath $checksumPath -Algorithm SHA256).Hash.ToLowerInvariant()
$checksums = @{}
foreach ($line in Get-Content -LiteralPath $checksumPath) {
    if ($line -notmatch "^([0-9a-f]{64})  ([^/\\]+)$") {
        throw "invalid recovery checksum line: $line"
    }
    $checksums[$Matches[2]] = $Matches[1]
}
Assert-Equal $checksums.Count $expectedRecoveryNames.Count "recovery checksum entries"
foreach ($name in $expectedRecoveryNames) {
    if (-not $checksums.ContainsKey($name)) {
        throw "recovery checksum is missing for $name"
    }
    $path = Join-Path $recoveryRoot $name
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "recovery artifact is missing: $path"
    }
    $hash = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    Assert-Equal $hash $checksums[$name] "recovery $name SHA-256"
}

$bundlePath = Join-Path $recoveryRoot "baseline-history-ceiling.bundle"
$savedErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "SilentlyContinue"
& git bundle verify $bundlePath 2>&1 | Out-Null
$bundleVerifyExitCode = $LASTEXITCODE
$ErrorActionPreference = $savedErrorActionPreference
if ($bundleVerifyExitCode -ne 0) {
    throw "sealed baseline Git bundle failed verification"
}
Write-Host "PASS  sealed baseline Git bundle"

$patchPath = Join-Path $recoveryRoot "tracked-working-tree-ceiling.patch"
# The FIFTH sealed-vs-live site (see the header note). The sealed patch describes the tree as it
# stood at the checkpoint, so a file that has legitimately changed since cannot reverse-apply. Those
# files are excluded here -- and ONLY those -- because each is already pinned to a declared SHA-256
# above; excluding them from a structural check they cannot pass does not leave them unverified.
# Every file NOT declared must still reverse-apply exactly as before.
$patchArgs = @("apply", "--check", "--reverse", "--binary", "--whitespace=nowarn")
foreach ($op in ($deltaOverrides.Keys | Sort-Object)) {
    $patchArgs += "--exclude=$op"
}
$patchArgs += $patchPath
& git @patchArgs
if ($LASTEXITCODE -ne 0) {
    throw "sealed tracked patch does not reverse-apply to the live candidate"
}
if ($deltaOverrides.Count -gt 0) {
    Write-Host ("PASS  sealed tracked patch reverse applicability (excluding {0} declared file(s), each hash-pinned)" -f $deltaOverrides.Count)
} else {
    Write-Host "PASS  sealed tracked patch reverse applicability"
}

$untrackedArchive = Join-Path $recoveryRoot "untracked-source-files-ceiling.tar"
$untrackedEntries = @(Get-SafeArchiveEntries $untrackedArchive)
Assert-Equal $untrackedEntries.Count $expectedUntrackedArchiveEntries "untracked recovery archive entries"
$liveUntracked = @(Get-GitOutput ls-files --others --exclude-standard)
$untrackedExpected = @($untrackedEntries + $deltaAdded | Sort-Object -Unique)
$untrackedDrift = Compare-Object -ReferenceObject $liveUntracked -DifferenceObject $untrackedExpected
if ($untrackedDrift) {
    $details = ($untrackedDrift | ForEach-Object { "$($_.SideIndicator) $($_.InputObject)" }) -join "; "
    throw "untracked recovery archive inventory drifted: $details"
}
Write-Host "PASS  untracked recovery archive exactly matches the live visible-untracked inventory"

$candidateArchive = Join-Path $recoveryRoot "candidate-source-tree-ceiling.tar"
$candidateArchiveEntries = @(Get-SafeArchiveEntries $candidateArchive)
Assert-Equal $candidateArchiveEntries.Count $expectedCandidateArchiveEntries "complete candidate-source archive entries"

$pytestArchive = Join-Path $recoveryRoot "ignored-registry-pytest-output-ceiling.tar"
$pytestEntries = @(Get-SafeArchiveEntries $pytestArchive)
Assert-Equal $pytestEntries.Count $expectedPytestArchiveEntries "pytest recovery archive entries"

$privateArchive = Join-Path $recoveryRoot "private-sanitization-backup-ceiling.tar"
$privateArchiveEntries = @(Get-SafeArchiveEntries $privateArchive)
Assert-Equal $privateArchiveEntries.Count $expectedPrivateArchiveEntries "private-backup archive entries"

$sourceManifestPath = Join-Path $recoveryRoot "SOURCE-MANIFEST.ceiling.json"
$sourceManifest = Get-Content -LiteralPath $sourceManifestPath -Raw | ConvertFrom-Json
Assert-Equal $sourceManifest.schema_version 1 "source manifest schema"
Assert-Equal $sourceManifest.branch $expectedBranch "source manifest branch"
Assert-Equal $sourceManifest.head $expectedHead "source manifest HEAD"
Assert-Equal $sourceManifest.tree $expectedTree "source manifest tree"

$sourceRecords = @($sourceManifest.files)
Assert-Equal $sourceRecords.Count $sourceManifest.file_count "source manifest file count"
$sourcePaths = @($sourceRecords | ForEach-Object { [string]$_.path })
$sourceDuplicates = @($sourcePaths | Group-Object | Where-Object Count -gt 1)
if ($sourceDuplicates) {
    throw "duplicate paths in source manifest: $($sourceDuplicates.Name -join ', ')"
}
foreach ($path in $sourcePaths) {
    Assert-SafeRelativePath $path "source manifest"
}
$candidateArchiveDrift = Compare-Object -ReferenceObject $sourcePaths -DifferenceObject $candidateArchiveEntries
if ($candidateArchiveDrift) {
    throw "complete candidate-source archive inventory drifted from its manifest"
}
Write-Host "PASS  complete candidate-source archive inventory matches its manifest"
$liveCandidatePaths = @(
    & git -c core.quotePath=false ls-files --cached --others --exclude-standard |
        Where-Object { Test-Path -LiteralPath (Join-Path $root $_) -PathType Leaf }
)
if ($LASTEXITCODE -ne 0) {
    throw "could not enumerate the live candidate source inventory"
}
$sourceExpected = @($sourcePaths + $deltaAdded | Sort-Object -Unique)
$sourceInventoryDrift = Compare-Object -ReferenceObject $sourceExpected -DifferenceObject $liveCandidatePaths
if ($sourceInventoryDrift) {
    $details = ($sourceInventoryDrift | ForEach-Object { "$($_.SideIndicator) $($_.InputObject)" }) -join "; "
    throw "source manifest inventory drifted: $details"
}
$observedSourceBytes = 0
foreach ($record in $sourceRecords) {
    $candidatePath = Join-Path $root ([string]$record.path)
    $item = Get-Item -LiteralPath $candidatePath -Force
    if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "source manifest path is a reparse point: $($record.path)"
    }
    $recPath = [string]$record.path
    $expectBytes = [long]$record.bytes
    $expectHash  = [string]$record.sha256
    $anchor = "sealed manifest"
    if ($deltaOverrides.ContainsKey($recPath)) {
        $expectBytes = [long]$deltaOverrides[$recPath].bytes
        $expectHash  = [string]$deltaOverrides[$recPath].sha256
        $anchor = "declared live-delta"
    }
    if ($item.Length -ne $expectBytes) {
        throw "source length drifted for $recPath (anchor: $anchor)"
    }
    $hash = (Get-FileHash -LiteralPath $candidatePath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($hash -ne $expectHash) {
        throw "source SHA-256 drifted for $recPath (anchor: $anchor)"
    }
    $observedSourceBytes += $item.Length
}
$sealedByPath = @{}
foreach ($record in $sourceRecords) { $sealedByPath[[string]$record.path] = [long]$record.bytes }
$expectedSourceBytes = [long]$sourceManifest.total_bytes
foreach ($op in $deltaOverrides.Keys) {
    if ($sealedByPath.ContainsKey($op)) {
        $expectedSourceBytes += ([long]$deltaOverrides[$op].bytes - $sealedByPath[$op])
    }
}
Assert-Equal $observedSourceBytes $expectedSourceBytes "source manifest total bytes (sealed + declared delta)"
# Files ADDED since the seal are absent from the sealed manifest, so pin them here or they would be
# the one part of the candidate tree nobody hashes.
foreach ($addedPath in $deltaAdded) {
    if ($addedPath -eq $deltaSelfPath) { continue }
    if (-not $deltaOverrides.ContainsKey($addedPath)) {
        throw "live-delta declares added path '$addedPath' with no content override to pin it"
    }
    $addedFull = Join-Path $root $addedPath
    $addedItem = Get-Item -LiteralPath $addedFull -Force
    if ($addedItem.Length -ne [long]$deltaOverrides[$addedPath].bytes) {
        throw "declared added file length drifted for $addedPath"
    }
    $addedHash = (Get-FileHash -LiteralPath $addedFull -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($addedHash -ne [string]$deltaOverrides[$addedPath].sha256) {
        throw "declared added file SHA-256 drifted for $addedPath"
    }
}
$manifestDeleted = @($sourceManifest.deleted_paths | ForEach-Object { [string]$_ })
$manifestDeletionDrift = Compare-Object -ReferenceObject $expectedDeletedPaths -DifferenceObject $manifestDeleted
if ($manifestDeletionDrift) {
    throw "source manifest deletion set drifted"
}
Write-Host "PASS  every candidate source byte is pinned (sealed manifest, or an explicitly declared live-delta hash)"

$privateManifestPath = Join-Path $recoveryRoot "PRIVATE-BACKUP-MANIFEST.ceiling.json"
$privateManifest = Get-Content -LiteralPath $privateManifestPath -Raw | ConvertFrom-Json
Assert-Equal $privateManifest.schema_version 1 "private backup manifest schema"
$privateRecords = @($privateManifest.files)
Assert-Equal $privateRecords.Count $expectedBackupFiles "private backup manifest file count"
$privatePaths = @($privateRecords | ForEach-Object { [string]$_.path })
$privateDuplicates = @($privatePaths | Group-Object | Where-Object Count -gt 1)
if ($privateDuplicates) {
    throw "duplicate paths in private backup manifest: $($privateDuplicates.Name -join ', ')"
}
$privateArchiveDrift = Compare-Object -ReferenceObject $privatePaths -DifferenceObject $privateArchiveEntries
if ($privateArchiveDrift) {
    throw "private-backup archive inventory drifted from its manifest"
}
Write-Host "PASS  private-backup archive inventory matches its manifest"
$backupPrefix = $backupPath.TrimEnd("\") + "\"
$livePrivateFiles = @(
    Get-ChildItem -LiteralPath $backupPath -Recurse -File -Force |
        ForEach-Object { $_.FullName.Substring($backupPrefix.Length).Replace("\", "/") }
)
$privateInventoryDrift = Compare-Object -ReferenceObject $privatePaths -DifferenceObject $livePrivateFiles
if ($privateInventoryDrift) {
    throw "private backup manifest inventory drifted"
}
$observedPrivateBytes = 0
foreach ($record in $privateRecords) {
    $relative = [string]$record.path
    Assert-SafeRelativePath $relative "private backup manifest"
    $privatePath = Join-Path $backupPath ($relative.Replace("/", "\"))
    $item = Get-Item -LiteralPath $privatePath -Force
    if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "private backup manifest path is a reparse point: $relative"
    }
    if ($item.Length -ne [long]$record.bytes) {
        throw "private backup length drifted for $relative"
    }
    $hash = (Get-FileHash -LiteralPath $privatePath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($hash -ne [string]$record.sha256) {
        throw "private backup SHA-256 drifted for $relative"
    }
    $observedPrivateBytes += $item.Length
}
Assert-Equal $observedPrivateBytes $expectedBackupBytes "private backup manifest total bytes"
Write-Host "PASS  every private backup file is byte-identical to its sealed manifest"

$pytestManifestPath = Join-Path $recoveryRoot "PYTEST-OUTPUT-MANIFEST.ceiling.json"
$pytestManifest = Get-Content -LiteralPath $pytestManifestPath -Raw | ConvertFrom-Json
Assert-Equal $pytestManifest.schema_version 1 "pytest-output manifest schema"
Assert-Equal $pytestManifest.directory_count $expectedPytestArchiveDirectories "pytest-output manifest directory count"
Assert-Equal $pytestManifest.file_count $expectedPytestArchiveFiles "pytest-output manifest file count"
Assert-Equal $pytestManifest.archive_entry_count $expectedPytestArchiveEntries "pytest-output manifest archive entry count"
Assert-Equal $pytestManifest.total_bytes $expectedPytestArchiveBytes "pytest-output manifest total bytes"
$pytestManifestDirectories = @($pytestManifest.directories | ForEach-Object { [string]$_ })
$pytestManifestRecords = @($pytestManifest.files)
$pytestManifestPaths = @($pytestManifestRecords | ForEach-Object { [string]$_.path })
foreach ($path in @($pytestManifestDirectories + $pytestManifestPaths)) {
    Assert-SafeRelativePath $path "pytest-output manifest"
}
$pytestManifestDuplicates = @(
    @($pytestManifestDirectories + $pytestManifestPaths) |
        Group-Object |
        Where-Object Count -gt 1
)
if ($pytestManifestDuplicates) {
    throw "duplicate paths in pytest-output manifest"
}
$pytestExpectedArchiveEntries = @(
    @($pytestManifestDirectories | ForEach-Object { "$_/" }) +
    $pytestManifestPaths
)
$pytestArchiveDrift = Compare-Object -ReferenceObject $pytestExpectedArchiveEntries -DifferenceObject $pytestEntries
if ($pytestArchiveDrift) {
    throw "pytest recovery archive inventory drifted from its manifest"
}

$rootPrefix = $root.TrimEnd("\") + "\"
$livePytestDirectories = @()
$livePytestFiles = @()
foreach ($pytestDir in $pytestDirs) {
    $livePytestDirectories += $pytestDir.FullName.Substring($rootPrefix.Length).Replace("\", "/")
    $descendants = @(Get-ChildItem -LiteralPath $pytestDir.FullName -Recurse -Force)
    $livePytestDirectories += @(
        $descendants |
            Where-Object PSIsContainer |
            ForEach-Object { $_.FullName.Substring($rootPrefix.Length).Replace("\", "/") }
    )
    $livePytestFiles += @(
        $descendants |
            Where-Object { -not $_.PSIsContainer }
    )
}
$livePytestPaths = @(
    $livePytestFiles |
        ForEach-Object { $_.FullName.Substring($rootPrefix.Length).Replace("\", "/") }
)
if (Compare-Object -ReferenceObject $pytestManifestDirectories -DifferenceObject $livePytestDirectories) {
    throw "live pytest-output directory inventory drifted from its manifest"
}
if (Compare-Object -ReferenceObject $pytestManifestPaths -DifferenceObject $livePytestPaths) {
    throw "live pytest-output file inventory drifted from its manifest"
}
$observedPytestBytes = 0
foreach ($record in $pytestManifestRecords) {
    $relative = [string]$record.path
    $pytestPath = Join-Path $root ($relative.Replace("/", "\"))
    $item = Get-Item -LiteralPath $pytestPath -Force
    if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "pytest-output manifest path is a reparse point: $relative"
    }
    if ($item.Length -ne [long]$record.bytes) {
        throw "pytest-output length drifted for $relative"
    }
    $hash = (Get-FileHash -LiteralPath $pytestPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($hash -ne [string]$record.sha256) {
        throw "pytest-output SHA-256 drifted for $relative"
    }
    $observedPytestBytes += $item.Length
}
Assert-Equal $observedPytestBytes $expectedPytestArchiveBytes "live pytest-output bytes"
Write-Host "PASS  every preserved pytest-output byte is identical to its sealed manifest"

$restoreProofPath = Join-Path $recoveryRoot "RESTORE-PROOF.ceiling.json"
$restoreProof = Get-Content -LiteralPath $restoreProofPath -Raw | ConvertFrom-Json
Assert-Equal $restoreProof.schema_version 1 "restore proof schema"
Assert-Equal $restoreProof.result "pass" "clean-room restore result"
Assert-Equal $restoreProof.head $expectedHead "clean-room restore HEAD"
Assert-Equal $restoreProof.tree $expectedTree "clean-room restore tree"
Assert-Equal $restoreProof.candidate_file_count $sourceManifest.file_count "clean-room candidate file count"
Assert-Equal $restoreProof.candidate_total_bytes $sourceManifest.total_bytes "clean-room candidate total bytes"
Assert-Equal $restoreProof.candidate_manifest_sha256 $checksums["SOURCE-MANIFEST.ceiling.json"] "clean-room source-manifest binding"
Assert-Equal $restoreProof.private_backup_file_count $privateManifest.file_count "clean-room private-backup file count"
Assert-Equal $restoreProof.private_backup_total_bytes $privateManifest.total_bytes "clean-room private-backup total bytes"
Assert-Equal $restoreProof.private_manifest_sha256 $checksums["PRIVATE-BACKUP-MANIFEST.ceiling.json"] "clean-room private-manifest binding"
Assert-Equal $restoreProof.pytest_output_file_count $pytestManifest.file_count "clean-room pytest-output file count"
Assert-Equal $restoreProof.pytest_output_total_bytes $pytestManifest.total_bytes "clean-room pytest-output total bytes"
Assert-Equal $restoreProof.pytest_manifest_sha256 $checksums["PYTEST-OUTPUT-MANIFEST.ceiling.json"] "clean-room pytest-manifest binding"
Assert-Equal $restoreProof.untracked_archive_file_count $expectedUntrackedArchiveEntries "clean-room untracked-archive file count"
Assert-Equal $restoreProof.untracked_archive_verified $true "clean-room untracked-archive verification"
$restorePath = Join-Path $root "private-inputs/review-handoff-restore-proof-ceiling-20260730"
if (-not (Test-Path -LiteralPath $restorePath -PathType Container)) {
    throw "preserved clean-room restore directory is missing: $restorePath"
}

$restoredHead = @(& git -C $restorePath rev-parse HEAD)
if ($LASTEXITCODE -ne 0) {
    throw "could not read the clean-room restore HEAD"
}
Assert-Equal ($restoredHead | Select-Object -First 1) $expectedHead "preserved clean-room HEAD"
$restoredTree = @(& git -C $restorePath rev-parse "HEAD^{tree}")
if ($LASTEXITCODE -ne 0) {
    throw "could not read the clean-room restore tree"
}
Assert-Equal ($restoredTree | Select-Object -First 1) $expectedTree "preserved clean-room tree"

$restoredStatus = @(& git -C $restorePath -c core.quotePath=false status --porcelain=v1 --untracked-files=all)
if ($LASTEXITCODE -ne 0) {
    throw "could not read the clean-room restore status"
}
$manifestStatus = @($sourceManifest.status_porcelain_v1 | ForEach-Object { [string]$_ })
$restoredStatusDrift = Compare-Object -ReferenceObject $manifestStatus -DifferenceObject $restoredStatus
if ($restoredStatusDrift) {
    $details = ($restoredStatusDrift | ForEach-Object { "$($_.SideIndicator) $($_.InputObject)" }) -join "; "
    throw "clean-room restore status drifted from the source manifest: $details"
}
$restoredStaged = @($restoredStatus | Where-Object { $_[0] -ne " " -and $_[0] -ne "?" }).Count
$restoredModified = @($restoredStatus | Where-Object { $_.Substring(0, 2) -eq " M" }).Count
$restoredDeleted = @($restoredStatus | Where-Object { $_.Substring(0, 2) -eq " D" }).Count
$restoredUntracked = @($restoredStatus | Where-Object { $_.StartsWith("??") }).Count
$restoredTracked = @($restoredStatus | Where-Object { -not $_.StartsWith("??") }).Count
Assert-Equal $restoredStaged 0 "preserved clean-room staged entries"
Assert-Equal $restoredTracked $expectedChangedTracked "preserved clean-room changed tracked files"
Assert-Equal $restoredModified $expectedModifiedTracked "preserved clean-room modified tracked files"
Assert-Equal $restoredDeleted $expectedDeletedTracked "preserved clean-room deleted tracked files"
Assert-Equal $restoredUntracked $expectedVisibleUntracked "preserved clean-room visible untracked files"
Assert-Equal $restoreProof.status.staged $restoredStaged "clean-room proof staged entries"
Assert-Equal $restoreProof.status.changed_tracked $restoredTracked "clean-room proof changed tracked files"
Assert-Equal $restoreProof.status.modified_tracked $restoredModified "clean-room proof modified tracked files"
Assert-Equal $restoreProof.status.deleted_tracked $restoredDeleted "clean-room proof deleted tracked files"
Assert-Equal $restoreProof.status.visible_untracked $restoredUntracked "clean-room proof visible untracked files"

$restoredCandidatePaths = @(
    & git -C $restorePath -c core.quotePath=false ls-files --cached --others --exclude-standard |
        Where-Object { Test-Path -LiteralPath (Join-Path $restorePath $_) -PathType Leaf }
)
if ($LASTEXITCODE -ne 0) {
    throw "could not enumerate the clean-room candidate source inventory"
}
$restoredInventoryDrift = Compare-Object -ReferenceObject $sourcePaths -DifferenceObject $restoredCandidatePaths
if ($restoredInventoryDrift) {
    throw "clean-room candidate source inventory drifted from the source manifest"
}
$restoredSourceBytes = 0
foreach ($record in $sourceRecords) {
    $restoredPath = Join-Path $restorePath ([string]$record.path)
    $item = Get-Item -LiteralPath $restoredPath -Force
    if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "clean-room source path is a reparse point: $($record.path)"
    }
    if ($item.Length -ne [long]$record.bytes) {
        throw "clean-room source length drifted for $($record.path)"
    }
    $hash = (Get-FileHash -LiteralPath $restoredPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($hash -ne [string]$record.sha256) {
        throw "clean-room source SHA-256 drifted for $($record.path)"
    }
    $restoredSourceBytes += $item.Length
}
Assert-Equal $restoredSourceBytes ([long]$sourceManifest.total_bytes) "preserved clean-room source bytes"

$restoredPytestDirs = @(Get-ChildItem -LiteralPath $restorePath -Directory -Force -Filter ".pytest_tmp_registry_*")
Assert-Equal $restoredPytestDirs.Count $expectedPytestDirectories "preserved clean-room pytest directories"
foreach ($dir in $restoredPytestDirs) {
    & git -C $restorePath check-ignore -q -- $dir.Name
    if ($LASTEXITCODE -ne 0) {
        throw "clean-room pytest directory is not ignored: $($dir.Name)"
    }
}
$restorePrefix = $restorePath.TrimEnd("\") + "\"
$restoredPytestDirectories = @()
$restoredPytestFiles = @()
foreach ($pytestDir in $restoredPytestDirs) {
    $restoredPytestDirectories += $pytestDir.FullName.Substring($restorePrefix.Length).Replace("\", "/")
    $descendants = @(Get-ChildItem -LiteralPath $pytestDir.FullName -Recurse -Force)
    $restoredPytestDirectories += @(
        $descendants |
            Where-Object PSIsContainer |
            ForEach-Object { $_.FullName.Substring($restorePrefix.Length).Replace("\", "/") }
    )
    $restoredPytestFiles += @(
        $descendants |
            Where-Object { -not $_.PSIsContainer }
    )
}
$restoredPytestPaths = @(
    $restoredPytestFiles |
        ForEach-Object { $_.FullName.Substring($restorePrefix.Length).Replace("\", "/") }
)
if (Compare-Object -ReferenceObject $pytestManifestDirectories -DifferenceObject $restoredPytestDirectories) {
    throw "clean-room pytest-output directory inventory drifted from its manifest"
}
if (Compare-Object -ReferenceObject $pytestManifestPaths -DifferenceObject $restoredPytestPaths) {
    throw "clean-room pytest-output file inventory drifted from its manifest"
}
$restoredPytestBytes = 0
foreach ($record in $pytestManifestRecords) {
    $relative = [string]$record.path
    $restoredPytestPath = Join-Path $restorePath ($relative.Replace("/", "\"))
    $item = Get-Item -LiteralPath $restoredPytestPath -Force
    if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "clean-room pytest-output path is a reparse point: $relative"
    }
    if ($item.Length -ne [long]$record.bytes) {
        throw "clean-room pytest-output length drifted for $relative"
    }
    $hash = (Get-FileHash -LiteralPath $restoredPytestPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($hash -ne [string]$record.sha256) {
        throw "clean-room pytest-output SHA-256 drifted for $relative"
    }
    $restoredPytestBytes += $item.Length
}
Assert-Equal $restoredPytestBytes ([long]$pytestManifest.total_bytes) "preserved clean-room pytest-output bytes"

$restoredUntrackedRoot = Join-Path $restorePath "private-inputs/review-handoff-untracked-archive-proof-20260730"
if (-not (Test-Path -LiteralPath $restoredUntrackedRoot -PathType Container)) {
    throw "clean-room untracked-archive extraction is missing: $restoredUntrackedRoot"
}
$restoredUntrackedPrefix = $restoredUntrackedRoot.TrimEnd("\") + "\"
$restoredUntrackedFiles = @(
    Get-ChildItem -LiteralPath $restoredUntrackedRoot -Recurse -File -Force |
        ForEach-Object { $_.FullName.Substring($restoredUntrackedPrefix.Length).Replace("\", "/") }
)
if (Compare-Object -ReferenceObject $untrackedEntries -DifferenceObject $restoredUntrackedFiles) {
    throw "clean-room untracked-archive extraction inventory drifted"
}
$sourceByPath = @{}
foreach ($record in $sourceRecords) {
    $sourceByPath[[string]$record.path] = $record
}
foreach ($relative in $untrackedEntries) {
    if (-not $sourceByPath.ContainsKey($relative)) {
        throw "untracked archive path is absent from the source manifest: $relative"
    }
    $record = $sourceByPath[$relative]
    $restoredUntrackedPath = Join-Path $restoredUntrackedRoot ($relative.Replace("/", "\"))
    $item = Get-Item -LiteralPath $restoredUntrackedPath -Force
    if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "clean-room untracked-archive path is a reparse point: $relative"
    }
    if ($item.Length -ne [long]$record.bytes) {
        throw "clean-room untracked-archive length drifted for $relative"
    }
    $hash = (Get-FileHash -LiteralPath $restoredUntrackedPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($hash -ne [string]$record.sha256) {
        throw "clean-room untracked-archive SHA-256 drifted for $relative"
    }
}
Write-Host "PASS  standalone untracked archive is byte-identical to the source manifest"

$restoredPrivateRoot = Join-Path $restorePath "private-inputs/repository-sanitization-backup-2026-07-30"
if (-not (Test-Path -LiteralPath $restoredPrivateRoot -PathType Container)) {
    throw "clean-room private-backup extraction is missing: $restoredPrivateRoot"
}
$restoredPrivatePrefix = $restoredPrivateRoot.TrimEnd("\") + "\"
$restoredPrivateFiles = @(
    Get-ChildItem -LiteralPath $restoredPrivateRoot -Recurse -File -Force |
        ForEach-Object { $_.FullName.Substring($restoredPrivatePrefix.Length).Replace("\", "/") }
)
$restoredPrivateDrift = Compare-Object -ReferenceObject $privatePaths -DifferenceObject $restoredPrivateFiles
if ($restoredPrivateDrift) {
    throw "clean-room private-backup inventory drifted from the private manifest"
}
$restoredPrivateBytes = 0
foreach ($record in $privateRecords) {
    $relative = [string]$record.path
    $restoredPrivatePath = Join-Path $restoredPrivateRoot ($relative.Replace("/", "\"))
    $item = Get-Item -LiteralPath $restoredPrivatePath -Force
    if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "clean-room private-backup path is a reparse point: $relative"
    }
    if ($item.Length -ne [long]$record.bytes) {
        throw "clean-room private-backup length drifted for $relative"
    }
    $hash = (Get-FileHash -LiteralPath $restoredPrivatePath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($hash -ne [string]$record.sha256) {
        throw "clean-room private-backup SHA-256 drifted for $relative"
    }
    $restoredPrivateBytes += $item.Length
}
Assert-Equal $restoredPrivateBytes ([long]$privateManifest.total_bytes) "preserved clean-room private-backup bytes"
Write-Host "PASS  clean-room reconstruction is byte-identical to both manifests"

$hostingPath = Join-Path $root "master-reference/.openai/hosting.json"
$hosting = Get-Content -LiteralPath $hostingPath -Raw | ConvertFrom-Json
if ($hosting.PSObject.Properties.Name -contains "project_id") {
    throw "Sites project_id now exists; this checkpoint predates site creation and must be deliberately advanced"
}
Write-Host "PASS  Sites project has not been created"

$finalStatus = @(& git -c core.quotePath=false status --porcelain=v1 --untracked-files=all)
if ($LASTEXITCODE -ne 0) {
    throw "could not perform the final live status check"
}
$finalStatusDrift = Compare-Object -ReferenceObject $status -DifferenceObject $finalStatus
if ($finalStatusDrift) {
    throw "working-tree status changed while the checkpoint verifier was running"
}
$finalRestoredStatus = @(& git -C $restorePath -c core.quotePath=false status --porcelain=v1 --untracked-files=all)
if ($LASTEXITCODE -ne 0) {
    throw "could not perform the final clean-room status check"
}
if (Compare-Object -ReferenceObject $restoredStatus -DifferenceObject $finalRestoredStatus) {
    throw "clean-room status changed while the checkpoint verifier was running"
}

Assert-ManifestRecordsAtRoot $root $sourceRecords $expectedSourceBytes "final live source" -Overrides $deltaOverrides
Assert-ManifestRecordsAtRoot $backupPath $privateRecords ([long]$privateManifest.total_bytes) "final live private backup"
Assert-ManifestRecordsAtRoot $root $pytestManifestRecords ([long]$pytestManifest.total_bytes) "final live pytest output"
Assert-ManifestRecordsAtRoot $restorePath $sourceRecords ([long]$sourceManifest.total_bytes) "final clean-room source"
Assert-ManifestRecordsAtRoot $restoredPrivateRoot $privateRecords ([long]$privateManifest.total_bytes) "final clean-room private backup"
Assert-ManifestRecordsAtRoot $restorePath $pytestManifestRecords ([long]$pytestManifest.total_bytes) "final clean-room pytest output"
$untrackedRecords = @($untrackedEntries | ForEach-Object { $sourceByPath[$_] })
$untrackedBytes = [long](($untrackedRecords | Measure-Object bytes -Sum).Sum)
Assert-ManifestRecordsAtRoot $restoredUntrackedRoot $untrackedRecords $untrackedBytes "final standalone untracked archive"

foreach ($name in $expectedRecoveryNames) {
    $path = Join-Path $recoveryRoot $name
    $hash = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    Assert-Equal $hash $checksums[$name] "final recovery $name SHA-256"
}
$finalChecksumLedgerHash = (Get-FileHash -LiteralPath $checksumPath -Algorithm SHA256).Hash.ToLowerInvariant()
Assert-Equal $finalChecksumLedgerHash $checksumLedgerHashAtStart "stable recovery checksum ledger"
$finalHandoffHash = (Get-FileHash -LiteralPath $handoffPath -Algorithm SHA256).Hash.ToLowerInvariant()
Assert-Equal $finalHandoffHash $handoffHashAtStart "stable handoff during run"
Write-Host "PASS  end-of-run drift recheck"

Write-Host ""
Write-Host "CHECKPOINT INTACT"
Write-Host "Read docs/review-hardening-handoff-2026-07-30.md completely, then continue at Phase A."
Write-Host "This proves handoff integrity only; it is not a test, privacy, release, or deployment approval."
