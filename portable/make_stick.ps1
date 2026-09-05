<#
Install, update, or roll back Atlas with a journaled whole-directory transaction.

The active Atlas tree is never mirrored in place. Release packages are copied onto the target
volume, verified, extracted there, verified again, and moved into Atlas.incoming. Client data is
moved as one directory only after the candidate and a same-volume database copy pass preflight.

  powershell -File portable\make_stick.ps1 -Dest E:\ -Package C:\release\Atlas-3.33.0rc1-windows-x64.zip
  powershell -File portable\make_stick.ps1 -Dest E:\ -Rollback

PowerShell 5.1-safe and ASCII-only. Parameters beginning with Test are executable fault-injection
seams used by tests; release-package installs can never skip selftest.
#>
param(
  [Parameter(Mandatory = $true)][string]$Dest,
  [string]$Package = "",
  [string]$Source = "",
  [switch]$Rollback,
  [switch]$RestorePreUpdateDatabase,
  [switch]$SkipSelftest,
  [ValidateSet("", "staging", "staged", "prepared", "previous_retired",
    "data_moved", "active_moved", "activated", "data_attach_pending", "data_attached",
    "rollback_slot_prepared", "rollback_slot_receipted",
    "rollback_prepared", "rollback_data_moved", "rollback_database_restored",
    "rollback_active_moved", "rollback_activated", "rollback_data_attached")]
  [string]$TestFailAfter = "",
  [ValidateRange(0, 10000)][int]$TestHoldLockMilliseconds = 0,
  [ValidateRange(1, 600)][int]$TestProcessTimeoutSeconds = 300
)

$ErrorActionPreference = "Stop"
$script:LockHandle = $null
$script:ReservedPackage = $null
$script:ReservedExtract = $null
$script:ReservedPreflight = $null
$script:PackageMode = $false

function Full-Path([string]$Path) { return [IO.Path]::GetFullPath($Path) }

function Is-Reparse([IO.FileSystemInfo]$Item) {
  return [bool]($Item.Attributes -band [IO.FileAttributes]::ReparsePoint)
}

function Assert-PhysicalItem(
  [string]$Path,
  [switch]$AllowMissing,
  [switch]$Directory,
  [switch]$File
) {
  if (-not (Test-Path -LiteralPath $Path)) {
    if ($AllowMissing) { return $null }
    throw "required path is missing: $Path"
  }
  $item = Get-Item -LiteralPath $Path -Force
  if (Is-Reparse $item) { throw "reparse points are forbidden in the updater boundary: $Path" }
  if ($Directory -and -not $item.PSIsContainer) { throw "expected a directory: $Path" }
  if ($File -and $item.PSIsContainer) { throw "expected a file: $Path" }
  return $item
}

function Assert-PhysicalTree([string]$Path) {
  $root = Assert-PhysicalItem $Path -Directory
  $stack = New-Object System.Collections.Stack
  $stack.Push($root)
  while ($stack.Count -gt 0) {
    $directory = $stack.Pop()
    foreach ($child in @(Get-ChildItem -LiteralPath $directory.FullName -Force)) {
      if (Is-Reparse $child) {
        throw "reparse points are forbidden in updater-owned trees: $($child.FullName)"
      }
      if ($child.PSIsContainer) { $stack.Push($child) }
    }
  }
}

function File-Sha256([string]$Path) {
  $full = Full-Path $Path
  Assert-PhysicalItem $full -File | Out-Null
  $stream = [IO.File]::Open($full, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
  try {
    $sha = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($sha.ComputeHash($stream)) -replace '-', '').ToLowerInvariant() }
    finally { $sha.Dispose() }
  } finally { $stream.Dispose() }
}

function Copy-ExclusiveVerified([string]$SourcePath, [string]$DestinationPath) {
  $sourceFull = Full-Path $SourcePath
  $destinationFull = Full-Path $DestinationPath
  Assert-PhysicalItem $sourceFull -File | Out-Null
  if (Test-Path -LiteralPath $destinationFull) { throw "copy destination already exists: $destinationFull" }
  $sourceStream = $null
  $destinationStream = $null
  try {
    $sourceStream = [IO.File]::Open(
      $sourceFull, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::None
    )
    $destinationStream = [IO.FileStream]::new(
      $destinationFull, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write,
      [IO.FileShare]::None, 1048576, [IO.FileOptions]::WriteThrough
    )
    $sourceStream.CopyTo($destinationStream, 1048576)
    $destinationStream.Flush($true)
    $bytes = [int64]$sourceStream.Length
    $sourceStream.Position = 0
    $sha = [Security.Cryptography.SHA256]::Create()
    try { $sourceHash = ([BitConverter]::ToString($sha.ComputeHash($sourceStream)) -replace '-', '').ToLowerInvariant() }
    finally { $sha.Dispose() }
  } finally {
    if ($destinationStream) { $destinationStream.Dispose() }
    if ($sourceStream) { $sourceStream.Dispose() }
  }
  $destinationHash = File-Sha256 $destinationFull
  $destinationBytes = (Get-Item -LiteralPath $destinationFull -Force).Length
  if ($destinationHash -ne $sourceHash -or $destinationBytes -ne $bytes) {
    throw "exclusive copy verification failed"
  }
  return [pscustomobject]@{ sha256 = $sourceHash; bytes = $bytes }
}

function Move-DirectoryExact([string]$SourcePath, [string]$DestinationPath) {
  $sourceFull = Full-Path $SourcePath
  $destinationFull = Full-Path $DestinationPath
  Assert-PhysicalItem $sourceFull -Directory | Out-Null
  if (Test-Path -LiteralPath $destinationFull) { throw "directory move destination already exists: $destinationFull" }
  if ([IO.Path]::GetPathRoot($sourceFull) -ne [IO.Path]::GetPathRoot($destinationFull)) {
    throw "directory activation must remain on one volume"
  }
  [IO.Directory]::Move($sourceFull, $destinationFull)
}

function Write-JsonAtomic([string]$Path, [object]$Value) {
  $full = Full-Path $Path
  $temp = $full + "." + [guid]::NewGuid().ToString("N") + ".tmp"
  $json = ($Value | ConvertTo-Json -Depth 16 -Compress) + "`n"
  $bytes = [Text.UTF8Encoding]::new($false).GetBytes($json)
  $stream = $null
  try {
    $stream = [IO.FileStream]::new(
      $temp, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write,
      [IO.FileShare]::None, 4096, [IO.FileOptions]::WriteThrough
    )
    $stream.Write($bytes, 0, $bytes.Length)
    $stream.Flush($true)
    $stream.Dispose()
    $stream = $null
    Move-Item -LiteralPath $temp -Destination $full -Force
  } finally {
    if ($stream) { $stream.Dispose() }
    if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue }
  }
}

function Write-State([string]$Journal, [object]$State, [string]$Phase) {
  if ($State -is [Collections.IDictionary]) { $State["phase"] = $Phase }
  else { $State.phase = $Phase }
  Write-JsonAtomic $Journal $State
}

function Read-State([string]$Journal) {
  Assert-PhysicalItem $Journal -File | Out-Null
  try { $state = Get-Content -LiteralPath $Journal -Raw | ConvertFrom-Json }
  catch { throw "Update journal is unreadable; preserve all Atlas* paths and inspect manually" }
  if (
    $state.schema -ne "atlas.portable-transaction/2" -or
    $state.operation -notin @("update", "rollback") -or
    [string]$state.run_id -notmatch '^[0-9a-f]{32}$'
  ) { throw "Update journal schema or identity is unsupported" }
  $runId = [string]$state.run_id
  if ($state.operation -eq "update") {
    $phases = @(
      "staging", "staged", "prepared", "previous_retired", "data_moved",
      "active_moved", "activated", "data_attach_pending", "data_attached", "rollback_slot_prepared",
      "rollback_slot_receipted"
    )
    if (
      [string]$state.phase -notin $phases -or
      [string]$state.failed_name -ne "Atlas.failed-update-$runId" -or
      [string]$state.candidate_identity.atlas_exe_sha256 -notmatch '^[0-9a-f]{64}$' -or
      [string]$state.candidate_identity.app_tree_sha256 -notmatch '^[0-9a-f]{64}$'
    ) { throw "Update journal fields are outside the closed update contract" }
    if ([string]$state.rollback_slot_prepared_name -and
        [string]$state.rollback_slot_prepared_name -ne "Atlas.rollback-slot.$runId.json") {
      throw "Update journal names an unsafe rollback-slot receipt"
    }
  } else {
    $phases = @(
      "rollback_prepared", "rollback_data_moved", "rollback_database_restored",
      "rollback_active_moved", "rollback_activated", "rollback_data_attached", "rollback_reversing",
      "rollback_reversing_candidate_data_quarantined", "rollback_reversing_data_moved",
      "rollback_reversing_target_moved", "rollback_reversed"
    )
    if (
      [string]$state.phase -notin $phases -or
      [string]$state.failed_name -ne "Atlas.failed-rollback-$runId"
    ) { throw "Update journal fields are outside the closed rollback contract" }
    $restoreName = [string]$state.restore_candidate_name
    if ($restoreName -and $restoreName -ne ".atlas-rollback-selected-$runId.db") {
      throw "Rollback journal names an unsafe database candidate"
    }
  }
  return $state
}

function Remove-ExactTree([string]$Path, [string]$Parent, [switch]$AllowTopLevelData) {
  $full = Full-Path $Path
  $root = (Full-Path $Parent).TrimEnd('\') + '\'
  if (-not $full.StartsWith($root, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing recursive removal outside the intended destination"
  }
  if (-not (Test-Path -LiteralPath $full)) { return }
  Assert-PhysicalTree $full
  $data = Join-Path $full "data"
  if (-not $AllowTopLevelData -and (Test-Path -LiteralPath $data)) {
    throw "Refusing to remove an application tree that contains top-level data"
  }
  Remove-Item -LiteralPath $full -Recurse -Force
}

function Ensure-EmptyTopLevelData([string]$Root) {
  $data = Join-Path $Root "data"
  if (-not (Test-Path -LiteralPath $data)) { return }
  Assert-PhysicalItem $data -Directory | Out-Null
  if (@(Get-ChildItem -LiteralPath $data -Force).Count -ne 0) {
    throw "candidate data directory contains bytes that cannot be discarded"
  }
  Remove-Item -LiteralPath $data -Force
}

function Assert-AppRoot([string]$Root) {
  Assert-PhysicalItem $Root -Directory | Out-Null
  Assert-PhysicalItem (Join-Path $Root "Atlas.exe") -File | Out-Null
  Assert-PhysicalItem (Join-Path $Root "_internal") -Directory | Out-Null
}

function App-Hash([string]$Root) {
  Assert-AppRoot $Root
  return File-Sha256 (Join-Path $Root "Atlas.exe")
}

function App-TreeHash([string]$Root) {
  $rootFull = Full-Path $Root
  Assert-AppRoot $rootFull
  $rows = New-Object System.Collections.Generic.List[string]
  $stack = New-Object System.Collections.Stack
  $stack.Push((Get-Item -LiteralPath $rootFull -Force))
  while ($stack.Count -gt 0) {
    $directory = $stack.Pop()
    foreach ($child in @(Get-ChildItem -LiteralPath $directory.FullName -Force)) {
      if ($directory.FullName -eq $rootFull -and $child.Name -ieq "data") { continue }
      if (Is-Reparse $child) { throw "application tree contains a reparse point: $($child.FullName)" }
      if ($child.PSIsContainer) {
        $stack.Push($child)
      } else {
        $relative = $child.FullName.Substring($rootFull.Length).TrimStart('\').Replace('\', '/')
        $rows.Add($relative + "`0" + [string]$child.Length + "`0" + (File-Sha256 $child.FullName))
      }
    }
  }
  $orderedRows = [string[]]$rows.ToArray()
  [Array]::Sort($orderedRows, [StringComparer]::Ordinal)
  $text = ($orderedRows -join "`n") + "`n"
  $bytes = [Text.UTF8Encoding]::new($false).GetBytes($text)
  $sha = [Security.Cryptography.SHA256]::Create()
  try { return ([BitConverter]::ToString($sha.ComputeHash($bytes)) -replace '-', '').ToLowerInvariant() }
  finally { $sha.Dispose() }
}

function Data-TreeHash([string]$Root) {
  $rootFull = Full-Path $Root
  $rootItem = Assert-PhysicalItem $rootFull -Directory
  $rows = New-Object System.Collections.Generic.List[string]
  $stack = New-Object System.Collections.Stack
  $stack.Push($rootItem)
  while ($stack.Count -gt 0) {
    $directory = $stack.Pop()
    foreach ($path in @(Get-ChildItem -LiteralPath $directory.FullName -Force)) {
      if (Is-Reparse $path) { throw "client data tree contains a reparse point" }
      $relative = $path.FullName.Substring($rootFull.Length).TrimStart('\').Replace('\', '/')
      if ($path.PSIsContainer) {
        $rows.Add("D`0" + $relative)
        $stack.Push($path)
      } else {
        $rows.Add("F`0" + $relative + "`0" + [string]$path.Length + "`0" + (File-Sha256 $path.FullName))
      }
    }
  }
  $orderedRows = [string[]]$rows.ToArray()
  [Array]::Sort($orderedRows, [StringComparer]::Ordinal)
  $text = ($orderedRows -join "`n") + "`n"
  $bytes = [Text.UTF8Encoding]::new($false).GetBytes($text)
  $sha = [Security.Cryptography.SHA256]::Create()
  try { return ([BitConverter]::ToString($sha.ComputeHash($bytes)) -replace '-', '').ToLowerInvariant() }
  finally { $sha.Dispose() }
}

function Require-FreeSpace([string]$Root, [int64]$Required, [string]$Purpose) {
  $drive = [IO.DriveInfo]::new([IO.Path]::GetPathRoot((Full-Path $Root)))
  if ([int64]$drive.AvailableFreeSpace -lt $Required) {
    throw "insufficient free space for $Purpose (need at least $Required bytes free)"
  }
}

function Acquire-DestinationLock([string]$Root) {
  $path = Join-Path $Root ".Atlas.update.lock"
  if (Test-Path -LiteralPath $path) { Assert-PhysicalItem $path -File | Out-Null }
  try {
    $script:LockHandle = [IO.FileStream]::new(
      $path, [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite,
      [IO.FileShare]::None, 1, [IO.FileOptions]::WriteThrough
    )
  } catch {
    throw "another Atlas update or rollback already holds the destination lock"
  }
}

function Quote-NativeArgument([string]$Value) {
  if ($Value -eq "") { return '""' }
  if ($Value -notmatch '[\s"]') { return $Value }
  return '"' + $Value.Replace('"', '\"') + '"'
}

function Invoke-BoundedProcess(
  [string]$FilePath,
  [string[]]$Arguments,
  [string]$WorkingDirectory = ""
) {
  $argumentLine = (($Arguments | ForEach-Object { Quote-NativeArgument ([string]$_) }) -join " ")
  $info = New-Object Diagnostics.ProcessStartInfo
  $info.FileName = $FilePath
  $info.Arguments = $argumentLine
  $info.UseShellExecute = $false
  $info.RedirectStandardOutput = $true
  $info.RedirectStandardError = $true
  $info.CreateNoWindow = $true
  if ($WorkingDirectory) { $info.WorkingDirectory = $WorkingDirectory }
  $process = New-Object Diagnostics.Process
  $process.StartInfo = $info
  try {
    if (-not $process.Start()) { throw "process could not start: $FilePath" }
    $stdoutTask = $process.StandardOutput.ReadToEndAsync()
    $stderrTask = $process.StandardError.ReadToEndAsync()
    if (-not $process.WaitForExit($TestProcessTimeoutSeconds * 1000)) {
      try { $process.Kill() } catch { }
      try { $process.WaitForExit() } catch { }
      throw "process timed out after $TestProcessTimeoutSeconds seconds: $FilePath"
    }
    $process.WaitForExit()
    $stdout = $stdoutTask.Result
    $stderr = $stderrTask.Result
    $exitCode = $process.ExitCode
    return [pscustomobject]@{ exit_code = $exitCode; stdout = $stdout; stderr = $stderr }
  } finally {
    $process.Dispose()
  }
}

function Invoke-Selftest([string]$AtlasRoot) {
  if ($SkipSelftest) { return }
  $exe = Join-Path $AtlasRoot "Atlas.exe"
  $tempRoot = Join-Path ([IO.Path]::GetTempPath()) ("atlas-stick-selftest-" + [guid]::NewGuid().ToString("N"))
  $db = Join-Path $tempRoot "hub.db"
  try {
    $result = Invoke-BoundedProcess $exe @("--selftest", "--db", $db)
    if ($result.stdout) { Write-Host $result.stdout.TrimEnd() }
    if ($result.stderr) { Write-Host $result.stderr.TrimEnd() }
    if ($result.exit_code -ne 0) {
      $tail = ($result.stdout + "`n" + $result.stderr).Trim()
      throw "candidate Atlas selftest failed (exit $($result.exit_code)): $tail"
    }
  } finally {
    if (Test-Path -LiteralPath $tempRoot) {
      Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
  }
}

function Invoke-ReleaseVerifier([string[]]$VerifierArgs) {
  $repoRoot = Split-Path $PSScriptRoot -Parent
  $result = Invoke-BoundedProcess "py" (@("-3.12", "-B", "-m", "portable.verify_release") + $VerifierArgs) $repoRoot
  if ($result.exit_code -ne 0) {
    $tail = (($result.stdout + "`n" + $result.stderr).Trim().Split("`n") | Select-Object -Last 4) -join " | "
    throw "portable release verification failed: $tail"
  }
  $jsonLine = $result.stdout.Split("`n") | Where-Object { $_.TrimStart().StartsWith("{") } | Select-Object -Last 1
  if (-not $jsonLine) { throw "portable release verifier emitted no machine receipt" }
  try { return $jsonLine | ConvertFrom-Json }
  catch { throw "portable release verifier emitted malformed machine receipt" }
}

function Same-SourceIdentity([object]$Left, [object]$Right) {
  foreach ($key in @("repository", "commit", "tree", "version", "tracked_status")) {
    if ([string]$Left.$key -ne [string]$Right.$key) { return $false }
  }
  return $true
}

function Verify-InstalledCandidate([string]$Root, [object]$Expected) {
  if (-not $Expected -or [string]$Expected.kind -ne "package") { return }
  $receipt = Invoke-ReleaseVerifier @("--installed", $Root)
  if (
    [string]$receipt.schema -ne "atlas.portable-installed-verification/1" -or
    [string]$receipt.status -ne "SELF_CONSISTENCY_PASS" -or
    [string]$receipt.authentication -ne "none_self_authored_consistency_only" -or
    [string]$receipt.runtime_member_set_digest -ne [string]$Expected.member_set_digest -or
    -not (Same-SourceIdentity $receipt.source $Expected.source)
  ) { throw "installed candidate identity differs from the verified package" }
}

function Assert-CandidateIdentity([string]$Root, [object]$Expected) {
  Assert-AppRoot $Root
  if ((App-Hash $Root) -ne [string]$Expected.atlas_exe_sha256) {
    throw "candidate Atlas.exe identity changed"
  }
  if ((App-TreeHash $Root) -ne [string]$Expected.app_tree_sha256) {
    throw "candidate application member set changed"
  }
  Verify-InstalledCandidate $Root $Expected
}

function Expanded-ZipBytes([string]$Path) {
  Add-Type -AssemblyName System.IO.Compression.FileSystem
  $archive = [IO.Compression.ZipFile]::OpenRead((Full-Path $Path))
  try {
    [int64]$total = 0
    foreach ($entry in $archive.Entries) { $total += [int64]$entry.Length }
    return $total
  } finally { $archive.Dispose() }
}

function Assert-DatabaseQuiescent([string]$Database) {
  Assert-PhysicalItem $Database -File | Out-Null
  foreach ($suffix in @("-journal", "-wal", "-shm")) {
    $sidecar = $Database + $suffix
    if (Test-Path -LiteralPath $sidecar) {
      Assert-PhysicalItem $sidecar -File | Out-Null
      throw "active database has a live journal/WAL sidecar; close Atlas before continuing"
    }
  }
}

function Invoke-DatabasePreflight([string]$Exe, [string]$Database, [string]$Root) {
  if ($SkipSelftest) { return $null }
  Assert-DatabaseQuiescent $Database
  $preflight = $script:ReservedPreflight
  if (Test-Path -LiteralPath $preflight) { Remove-ExactTree $preflight $Root }
  New-Item -ItemType Directory -Path $preflight | Out-Null
  $copy = Join-Path $preflight "assesshub.db"
  try {
    $copied = Copy-ExclusiveVerified $Database $copy
    $nonce = [guid]::NewGuid().ToString("N")
    $requestPath = Join-Path $preflight "atlas-db-preflight.json"
    # Alphabetical key order is the canonical JSON order enforced by the frozen command.
    $request = [ordered]@{
      database_name = "assesshub.db"
      input_copy_bytes = [int64]$copied.bytes
      input_copy_sha256 = [string]$copied.sha256
      nonce = $nonce
      requested_action = "open_migrate_copy_and_report"
      schema = "atlas.database-preflight-request/1"
    }
    Write-JsonAtomic $requestPath $request
    $requestHash = File-Sha256 $requestPath
    $env:ATLAS_PORTABLE_DATABASE_PREFLIGHT = $nonce
    try {
      $result = Invoke-BoundedProcess $Exe @("--database-preflight", $copy)
    } finally { Remove-Item Env:\ATLAS_PORTABLE_DATABASE_PREFLIGHT -ErrorAction SilentlyContinue }
    if ($result.exit_code -ne 0) { throw "candidate cannot open and migrate a same-volume copy of the active database" }
    $jsonLine = $result.stdout.Split("`n") | Where-Object { $_.TrimStart().StartsWith("{") } | Select-Object -Last 1
    if (-not $jsonLine) { throw "database preflight emitted no machine receipt" }
    try { $receipt = $jsonLine | ConvertFrom-Json }
    catch { throw "database preflight emitted malformed machine receipt" }
    $migratedHash = File-Sha256 $copy
    $migratedBytes = [int64](Get-Item -LiteralPath $copy -Force).Length
    $wasModified = ($migratedHash -ne [string]$copied.sha256 -or $migratedBytes -ne [int64]$copied.bytes)
    if (
      [string]$receipt.schema -ne "atlas.database-preflight/1" -or
      $receipt.status -ne "pass" -or $receipt.quick_check -ne "ok" -or
      [string]$receipt.input_copy_binding.database_name -ne "assesshub.db" -or
      [string]$receipt.input_copy_binding.sha256 -ne [string]$copied.sha256 -or
      [int64]$receipt.input_copy_binding.bytes -ne [int64]$copied.bytes -or
      [string]$receipt.request_nonce -ne $nonce -or
      [string]$receipt.request_sha256 -ne $requestHash -or
      [string]$receipt.migrated_copy_sha256 -ne $migratedHash -or
      [int64]$receipt.migrated_copy_bytes -ne $migratedBytes -or
      [bool]$receipt.caller_supplied_database_modified -ne $wasModified -or
      [string]$receipt.authority_effect -ne "NONE"
    ) { throw "database preflight receipt did not bind the supplied copy and request" }
    return [pscustomobject]@{ sha256 = $copied.sha256; bytes = $copied.bytes; receipt = $receipt }
  } finally {
    if (Test-Path -LiteralPath $preflight) { Remove-ExactTree $preflight $Root }
  }
}

function New-PreUpdateBackup(
  [string]$Database,
  [string]$DataRoot,
  [string]$RunId,
  [string]$PreviousExeHash,
  [object]$Candidate,
  [string]$ExpectedDatabaseHash
) {
  $backupRoot = Join-Path $DataRoot "release-backups"
  if (Test-Path -LiteralPath $backupRoot) { Assert-PhysicalItem $backupRoot -Directory | Out-Null }
  else { New-Item -ItemType Directory -Path $backupRoot | Out-Null }
  $leaf = "pre-update-$RunId.db"
  $partial = Join-Path $backupRoot ("." + $leaf + ".partial")
  $final = Join-Path $backupRoot $leaf
  $receiptLeaf = "pre-update-$RunId.json"
  $receiptPath = Join-Path $backupRoot $receiptLeaf
  $copied = Copy-ExclusiveVerified $Database $partial
  if ([string]$copied.sha256 -ne $ExpectedDatabaseHash) {
    throw "active database changed between preflight and backup"
  }
  Move-Item -LiteralPath $partial -Destination $final
  if ((File-Sha256 $final) -ne [string]$copied.sha256) { throw "pre-update backup verification failed" }
  $receipt = [ordered]@{
    schema = "atlas.pre-update-database-backup/1"
    run_id = $RunId
    created_at = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    backup_name = $leaf
    bytes = [int64]$copied.bytes
    sha256 = [string]$copied.sha256
    source_database_sha256 = [string]$copied.sha256
    previous_exe_sha256 = $PreviousExeHash
    candidate_identity = $Candidate
    authentication = "none_local_consistency_only"
  }
  Write-JsonAtomic $receiptPath $receipt
  return [pscustomobject]@{
    receipt_name = $receiptLeaf
    receipt_sha256 = (File-Sha256 $receiptPath)
    backup_path = $final
    sha256 = [string]$copied.sha256
    bytes = [int64]$copied.bytes
  }
}

function Get-VerifiedPreUpdateBackup([string]$DataRoot, [object]$Slot) {
  $backupRoot = Join-Path $DataRoot "release-backups"
  Assert-PhysicalItem $backupRoot -Directory | Out-Null
  $receiptLeaf = [string]$Slot.database_backup_receipt
  if ($receiptLeaf -notmatch '^pre-update-[0-9a-f]{32}\.json$') {
    throw "no verified pre-update database backup is bound to Atlas.previous"
  }
  $receiptPath = Join-Path $backupRoot $receiptLeaf
  Assert-PhysicalItem $receiptPath -File | Out-Null
  if ((File-Sha256 $receiptPath) -ne [string]$Slot.database_backup_receipt_sha256) {
    throw "the rollback slot database receipt identity changed"
  }
  try { $receipt = Get-Content -LiteralPath $receiptPath -Raw | ConvertFrom-Json }
  catch { throw "pre-update database backup receipt is unreadable" }
  $leaf = [string]$receipt.backup_name
  if (
    $receipt.schema -ne "atlas.pre-update-database-backup/1" -or
    [string]$receipt.run_id -ne [string]$Slot.update_run_id -or
    [string]$receipt.previous_exe_sha256 -ne [string]$Slot.previous_exe_sha256 -or
    [string]$receipt.candidate_identity.app_tree_sha256 -ne [string]$Slot.active_tree_sha256 -or
    $leaf -notmatch '^pre-update-[0-9a-f]{32}\.db$' -or
    [IO.Path]::GetFileName($leaf) -ne $leaf
  ) { throw "pre-update database backup receipt binding is invalid" }
  $backup = Join-Path $backupRoot $leaf
  Assert-PhysicalItem $backup -File | Out-Null
  if (
    (File-Sha256 $backup) -ne [string]$receipt.sha256 -or
    [int64](Get-Item -LiteralPath $backup -Force).Length -ne [int64]$receipt.bytes -or
    [string]$receipt.source_database_sha256 -ne [string]$receipt.sha256
  ) { throw "pre-update database backup receipt does not match its bytes" }
  return [pscustomobject]@{
    receipt_name = $receiptLeaf
    backup_path = $backup
    sha256 = [string]$receipt.sha256
    bytes = [int64]$receipt.bytes
  }
}

function Prepare-RollbackSlotReceipt(
  [string]$Root,
  [object]$State,
  [string]$ActiveTreeHash,
  [string]$PreviousTreeHash
) {
  $leaf = "Atlas.rollback-slot." + [string]$State.run_id + ".json"
  $path = Join-Path $Root $leaf
  $receipt = [ordered]@{
    schema = "atlas.portable-rollback-slot/1"
    status = "prepared"
    update_run_id = [string]$State.run_id
    active_exe_sha256 = [string]$State.candidate_identity.atlas_exe_sha256
    active_tree_sha256 = $ActiveTreeHash
    previous_exe_sha256 = [string]$State.active_exe_sha256
    previous_tree_sha256 = $PreviousTreeHash
    database_backup_receipt = [string]$State.database_backup_receipt
    database_backup_receipt_sha256 = [string]$State.database_backup_receipt_sha256
    candidate_identity = $State.candidate_identity
    authentication = "none_local_consistency_only"
  }
  Write-JsonAtomic $path $receipt
  return [pscustomobject]@{ name = $leaf; sha256 = (File-Sha256 $path) }
}

function Complete-RollbackSlotReceipt([string]$Root, [object]$State) {
  $prepared = Join-Path $Root ([string]$State.rollback_slot_prepared_name)
  $final = Join-Path $Root "Atlas.rollback-slot.json"
  $expected = [string]$State.rollback_slot_prepared_sha256
  if (Test-Path -LiteralPath $prepared) {
    if ((File-Sha256 $prepared) -ne $expected) { throw "prepared rollback-slot receipt changed" }
    Move-Item -LiteralPath $prepared -Destination $final -Force
  }
  Assert-PhysicalItem $final -File | Out-Null
  if ((File-Sha256 $final) -ne $expected) { throw "active rollback-slot receipt changed" }
}

function Get-RollbackSlotReceipt([string]$Root, [string]$Target, [string]$Previous) {
  $path = Join-Path $Root "Atlas.rollback-slot.json"
  Assert-PhysicalItem $path -File | Out-Null
  try { $slot = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json }
  catch { throw "rollback-slot receipt is unreadable" }
  if (
    $slot.schema -ne "atlas.portable-rollback-slot/1" -or
    $slot.status -ne "prepared" -or
    [string]$slot.update_run_id -notmatch '^[0-9a-f]{32}$' -or
    [string]$slot.active_tree_sha256 -ne (App-TreeHash $Target) -or
    [string]$slot.previous_tree_sha256 -ne (App-TreeHash $Previous) -or
    [string]$slot.active_exe_sha256 -ne (App-Hash $Target) -or
    [string]$slot.previous_exe_sha256 -ne (App-Hash $Previous)
  ) { throw "rollback-slot receipt does not bind Atlas and Atlas.previous" }
  return $slot
}

function New-RollbackPreservedBackup(
  [string]$Database,
  [string]$DataRoot,
  [string]$RunId,
  [string]$ActiveExeHash,
  [string]$RollbackExeHash
) {
  $backupRoot = Join-Path $DataRoot "release-backups"
  if (Test-Path -LiteralPath $backupRoot) { Assert-PhysicalItem $backupRoot -Directory | Out-Null }
  else { New-Item -ItemType Directory -Path $backupRoot | Out-Null }
  $leaf = "rollback-preserved-$RunId.db"
  $partial = Join-Path $backupRoot ("." + $leaf + ".partial")
  $final = Join-Path $backupRoot $leaf
  $receiptLeaf = "rollback-preserved-$RunId.json"
  $copied = Copy-ExclusiveVerified $Database $partial
  Move-Item -LiteralPath $partial -Destination $final
  $receipt = [ordered]@{
    schema = "atlas.rollback-preserved-database/1"
    run_id = $RunId
    created_at = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    backup_name = $leaf
    bytes = [int64]$copied.bytes
    sha256 = [string]$copied.sha256
    active_exe_sha256 = $ActiveExeHash
    rollback_exe_sha256 = $RollbackExeHash
    authentication = "none_local_consistency_only"
  }
  $receiptPath = Join-Path $backupRoot $receiptLeaf
  Write-JsonAtomic $receiptPath $receipt
  return [pscustomobject]@{
    receipt_name = $receiptLeaf
    receipt_sha256 = (File-Sha256 $receiptPath)
    backup_path = $final
    sha256 = [string]$copied.sha256
    bytes = [int64]$copied.bytes
  }
}

function Restore-OriginalRollbackDatabase([string]$DataRoot, [object]$State) {
  $expected = [string]$State.original_database_sha256
  if (-not $expected) { return }
  $database = Join-Path $DataRoot "assesshub.db"
  if (Test-Path -LiteralPath $database) {
    if ((File-Sha256 $database) -eq $expected) { return }
  }
  if (-not [bool]$State.restore_pre_update_database) {
    throw "pre-rollback database identity cannot be restored"
  }
  $backupRoot = Join-Path $DataRoot "release-backups"
  $receiptLeaf = [string]$State.preserved_database_receipt
  if ($receiptLeaf -ne ("rollback-preserved-" + [string]$State.run_id + ".json")) {
    throw "rollback-preserved database receipt name is invalid"
  }
  $receiptPath = Join-Path $backupRoot $receiptLeaf
  Assert-PhysicalItem $receiptPath -File | Out-Null
  if ((File-Sha256 $receiptPath) -ne [string]$State.preserved_database_receipt_sha256) {
    throw "rollback-preserved database receipt identity changed"
  }
  try { $receipt = Get-Content -LiteralPath $receiptPath -Raw | ConvertFrom-Json }
  catch { throw "rollback-preserved database receipt is unreadable" }
  $leaf = [string]$receipt.backup_name
  if (
    $receipt.schema -ne "atlas.rollback-preserved-database/1" -or
    [string]$receipt.run_id -ne [string]$State.run_id -or
    $leaf -ne ("rollback-preserved-" + [string]$State.run_id + ".db") -or
    [string]$receipt.sha256 -ne $expected -or
    [string]$receipt.active_exe_sha256 -ne [string]$State.active_exe_sha256 -or
    [string]$receipt.rollback_exe_sha256 -ne [string]$State.rollback_exe_sha256
  ) { throw "rollback-preserved database receipt binding is invalid" }
  $backup = Join-Path $backupRoot $leaf
  Assert-PhysicalItem $backup -File | Out-Null
  if (
    (File-Sha256 $backup) -ne $expected -or
    [int64](Get-Item -LiteralPath $backup -Force).Length -ne [int64]$receipt.bytes
  ) { throw "rollback-preserved database bytes do not match their receipt" }
  $candidate = Join-Path $DataRoot (".atlas-original-" + [string]$State.run_id + ".db")
  if (Test-Path -LiteralPath $candidate) { Remove-Item -LiteralPath $candidate -Force }
  $copied = Copy-ExclusiveVerified $backup $candidate
  if ([string]$copied.sha256 -ne $expected) { throw "rollback-preserved database copy changed" }
  Move-Item -LiteralPath $candidate -Destination $database -Force
  if ((File-Sha256 $database) -ne $expected) { throw "pre-rollback database restoration failed" }
}

function Restore-PreRollbackActive(
  [string]$Root,
  [string]$Target,
  [string]$Handoff,
  [string]$Previous,
  [string]$Journal,
  [object]$State
) {
  $failed = Join-Path $Root ([string]$State.failed_name)
  $activeHash = [string]$State.active_tree_sha256
  $rollbackHash = [string]$State.rollback_tree_sha256
  $targetHash = if (Test-Path -LiteralPath $Target) { App-TreeHash $Target } else { $null }
  $previousHash = if (Test-Path -LiteralPath $Previous) { App-TreeHash $Previous } else { $null }
  $failedHash = if (Test-Path -LiteralPath $failed) { App-TreeHash $failed } else { $null }

  if ($targetHash -eq $rollbackHash) {
    if ($failedHash -ne $activeHash) { throw "pre-rollback active tree is unavailable for reversal" }
    $targetData = Join-Path $Target "data"
    $failedData = Join-Path $failed "data"
    if (Test-Path -LiteralPath $targetData) {
      if (Test-Path -LiteralPath $Handoff) {
        $candidateData = Join-Path $Root ("Atlas.failed-rollback-data-" + [string]$State.run_id)
        if (-not (Test-Path -LiteralPath $candidateData)) {
          Move-DirectoryExact $targetData $candidateData
          Write-State $Journal $State "rollback_reversing_candidate_data_quarantined"
        }
        Restore-OriginalRollbackDatabase $Handoff $State
      } else {
        Restore-OriginalRollbackDatabase $targetData $State
        if (Test-Path -LiteralPath $failedData) {
          throw "client data exists in more than one rollback location"
        }
        Move-DirectoryExact $targetData $Handoff
        Write-State $Journal $State "rollback_reversing_data_moved"
      }
    } elseif (Test-Path -LiteralPath $Handoff) {
      Restore-OriginalRollbackDatabase $Handoff $State
    } elseif (Test-Path -LiteralPath $failedData) {
      Restore-OriginalRollbackDatabase $failedData $State
    } else {
      throw "client data is unavailable for rollback reversal"
    }
    if (-not (Test-Path -LiteralPath $Previous)) {
      Move-DirectoryExact $Target $Previous
      Write-State $Journal $State "rollback_reversing_target_moved"
    }
  }

  if (-not (Test-Path -LiteralPath $Target)) {
    if ((App-TreeHash $failed) -ne $activeHash) { throw "pre-rollback active tree identity changed" }
    Move-DirectoryExact $failed $Target
    Write-State $Journal $State "rollback_reversed"
  }
  if ((App-TreeHash $Target) -ne $activeHash) { throw "pre-rollback active tree was not restored" }
  if ((App-TreeHash $Previous) -ne $rollbackHash) { throw "rollback candidate was not restored to Atlas.previous" }
  $data = Join-Path $Target "data"
  if (Test-Path -LiteralPath $Handoff) {
    if (Test-Path -LiteralPath $data) { throw "client data exists in two reversal locations" }
    Move-DirectoryExact $Handoff $data
  }
  Assert-PhysicalItem $data -Directory | Out-Null
  Restore-OriginalRollbackDatabase $data $State
  Remove-Item -LiteralPath $Journal -Force
  Write-Host "[ok] rollback candidate failed; restored the pre-rollback active tree and database"
}

function Restore-PriorPrevious([object]$State, [string]$Previous, [string]$Retired) {
  if ([bool]$State.prior_previous_present) {
    if (Test-Path -LiteralPath $Retired) {
      if (Test-Path -LiteralPath $Previous) { throw "both prior rollback slots exist; refusing ambiguity" }
      if ((App-TreeHash $Retired) -ne [string]$State.prior_previous_tree_sha256) {
        throw "retired rollback slot identity changed"
      }
      Move-DirectoryExact $Retired $Previous
    } elseif (-not (Test-Path -LiteralPath $Previous)) {
      throw "the prior rollback slot is missing"
    } elseif ((App-TreeHash $Previous) -ne [string]$State.prior_previous_tree_sha256) {
      throw "prior rollback slot identity changed"
    }
  } elseif (Test-Path -LiteralPath $Retired) {
    throw "unexpected retired rollback slot exists"
  }
}

function Move-ToFailed([string]$Path, [string]$Failed) {
  if (-not (Test-Path -LiteralPath $Path)) { return }
  if (Test-Path -LiteralPath $Failed) { throw "recovery target already exists: $Failed" }
  Move-DirectoryExact $Path $Failed
}

function Remove-OrQuarantineIncoming([string]$Incoming, [string]$Failed, [string]$Root) {
  if (-not (Test-Path -LiteralPath $Incoming)) { return }
  $candidateData = Join-Path $Incoming "data"
  if (Test-Path -LiteralPath $candidateData) {
    Assert-PhysicalItem $candidateData -Directory | Out-Null
    if (@(Get-ChildItem -LiteralPath $candidateData -Force).Count -ne 0) {
      Move-ToFailed $Incoming $Failed
      return
    }
    Remove-Item -LiteralPath $candidateData -Force
  }
  Remove-ExactTree $Incoming $Root
}

function Recover-Update(
  [string]$Root,
  [string]$Target,
  [string]$Incoming,
  [string]$Handoff,
  [string]$Previous,
  [string]$Retired,
  [string]$Journal,
  [object]$State,
  [switch]$ForceRollback
) {
  $failed = Join-Path $Root ([string]$State.failed_name)
  foreach ($slot in @($Target, $Incoming, $Handoff, $Previous, $Retired, $failed)) {
    if (Test-Path -LiteralPath $slot) { Assert-PhysicalItem $slot -Directory | Out-Null }
  }
  $candidate = $State.candidate_identity
  if ([string]$State.phase -in @("rollback_slot_prepared", "rollback_slot_receipted")) {
    if (-not [bool]$State.had_active) { throw "first install cannot publish a rollback-slot receipt" }
    Assert-CandidateIdentity $Target $candidate
    if ((App-TreeHash $Previous) -ne [string]$State.active_tree_sha256) {
      throw "validated update lost its exact prior active tree"
    }
    Complete-RollbackSlotReceipt $Root $State
    $committedData = Join-Path $Target "data"
    if ([string]$State.data_tree_sha256 -and
        (Data-TreeHash $committedData) -ne [string]$State.data_tree_sha256) {
      throw "validated update data identity changed before commit recovery"
    }
    if (Test-Path -LiteralPath $Retired) { Remove-ExactTree $Retired $Root }
    Remove-Item -LiteralPath $Journal -Force
    Write-Host "[ok] completed the validated update rollback-slot receipt"
    return
  }
  if (-not [bool]$State.had_active) {
    if ((Test-Path -LiteralPath $Previous) -or (Test-Path -LiteralPath $Retired)) {
      throw "first-install journal conflicts with an existing rollback slot"
    }
    if (Test-Path -LiteralPath $Target) {
      if ($ForceRollback) {
        Move-ToFailed $Target $failed
      } else {
        try {
          Assert-CandidateIdentity $Target $candidate
          $firstData = Join-Path $Target "data"
          if (Test-Path -LiteralPath $firstData) {
            Ensure-EmptyTopLevelData $Target
          }
          Invoke-Selftest $Target
          Assert-CandidateIdentity $Target $candidate
          if (Test-Path -LiteralPath $firstData) {
            Ensure-EmptyTopLevelData $Target
          }
          New-Item -ItemType Directory -Path $firstData | Out-Null
        } catch {
          Move-ToFailed $Target $failed
          Remove-Item -LiteralPath $Journal -Force
          throw "interrupted first-install candidate failed verification and was quarantined"
        }
      }
    } elseif (Test-Path -LiteralPath $Incoming) {
      Remove-OrQuarantineIncoming $Incoming $failed $Root
    }
    Remove-Item -LiteralPath $Journal -Force
    Write-Host "[ok] recovered an interrupted first install"
    return
  }

  $oldHash = [string]$State.active_tree_sha256
  $targetHash = if (Test-Path -LiteralPath $Target) { App-TreeHash $Target } else { $null }
  $previousHash = if (Test-Path -LiteralPath $Previous) { App-TreeHash $Previous } else { $null }
  $targetData = Join-Path $Target "data"
  $incomingData = Join-Path $Incoming "data"
  $previousData = Join-Path $Previous "data"

  $preferPriorActive = (
    $previousHash -eq $oldHash -and
    ($ForceRollback -or -not (Test-Path -LiteralPath $Incoming))
  )
  if ($targetHash -eq $oldHash -and -not $preferPriorActive) {
    if (-not (Test-Path -LiteralPath $targetData)) {
      if (Test-Path -LiteralPath $Handoff) {
        Move-DirectoryExact $Handoff $targetData
      } elseif (Test-Path -LiteralPath $incomingData) {
        Move-DirectoryExact $incomingData $targetData
      } else { throw "recovery cannot find the client data directory" }
    }
    if (Test-Path -LiteralPath $Incoming) {
      Remove-OrQuarantineIncoming $Incoming $failed $Root
    }
    if ([string]$State.data_tree_sha256 -and
        (Data-TreeHash $targetData) -ne [string]$State.data_tree_sha256) {
      throw "client data identity changed during update recovery"
    }
    Restore-PriorPrevious $State $Previous $Retired
    Remove-Item -LiteralPath $Journal -Force
    Write-Host "[ok] recovered interrupted update to the prior active tree"
    return
  }

  if ($previousHash -eq $oldHash) {
    if (-not (Test-Path -LiteralPath $previousData)) {
      if (Test-Path -LiteralPath $Handoff) {
        if (Test-Path -LiteralPath $targetData) {
          Move-DirectoryExact $targetData (Join-Path $Root ("Atlas.failed-update-data-" + [string]$State.run_id))
        }
        Move-DirectoryExact $Handoff $previousData
      } elseif (Test-Path -LiteralPath $targetData) {
        Move-DirectoryExact $targetData $previousData
      } elseif (Test-Path -LiteralPath $incomingData) {
        Move-DirectoryExact $incomingData $previousData
      } else { throw "recovery cannot find the client data directory" }
    }
    if (Test-Path -LiteralPath $Target) { Move-ToFailed $Target $failed }
    if (-not (Test-Path -LiteralPath $Target)) { Move-DirectoryExact $Previous $Target }
    if (Test-Path -LiteralPath $Incoming) {
      Remove-OrQuarantineIncoming $Incoming $failed $Root
    }
    if ([string]$State.data_tree_sha256 -and
        (Data-TreeHash (Join-Path $Target "data")) -ne [string]$State.data_tree_sha256) {
      throw "client data identity changed during update rollback recovery"
    }
    Restore-PriorPrevious $State $Previous $Retired
    Remove-Item -LiteralPath $Journal -Force
    Write-Host "[ok] recovered interrupted update to the prior active tree"
    return
  }

  if ($targetHash -eq [string]$candidate.app_tree_sha256 -and -not (Test-Path -LiteralPath $Previous)) {
    throw "candidate is active but the prior active tree is missing; preserve all slots"
  }
  throw "interrupted update topology or application identity is inconsistent; preserve all slots"
}

function Ensure-SelectedRollbackDatabase([string]$DataRoot, [object]$State) {
  $expected = [string]$State.selected_database_sha256
  if (-not $expected) { return }
  $database = Join-Path $DataRoot "assesshub.db"
  if (Test-Path -LiteralPath $database) {
    $current = File-Sha256 $database
    if ($current -eq $expected) { return }
  }
  if (-not [bool]$State.restore_pre_update_database) {
    throw "rollback database changed after compatibility preflight"
  }
  $candidate = Join-Path $DataRoot ([string]$State.restore_candidate_name)
  Assert-PhysicalItem $candidate -File | Out-Null
  if ((File-Sha256 $candidate) -ne $expected) { throw "rollback database candidate identity changed" }
  Move-Item -LiteralPath $candidate -Destination $database -Force
  if ((File-Sha256 $database) -ne $expected) { throw "rollback database activation failed" }
}

function Recover-Rollback(
  [string]$Root,
  [string]$Target,
  [string]$Handoff,
  [string]$Previous,
  [string]$Journal,
  [object]$State
) {
  if ([string]$State.phase -like "rollback_reversing*" -or [string]$State.phase -eq "rollback_reversed") {
    Restore-PreRollbackActive $Root $Target $Handoff $Previous $Journal $State
    return "rollback_reversed"
  }
  $failed = Join-Path $Root ([string]$State.failed_name)
  foreach ($slot in @($Target, $Handoff, $Previous, $failed)) {
    if (Test-Path -LiteralPath $slot) { Assert-PhysicalItem $slot -Directory | Out-Null }
  }
  $activeHash = [string]$State.active_tree_sha256
  $rollbackHash = [string]$State.rollback_tree_sha256
  $targetHash = if (Test-Path -LiteralPath $Target) { App-TreeHash $Target } else { $null }
  $previousHash = if (Test-Path -LiteralPath $Previous) { App-TreeHash $Previous } else { $null }
  $targetData = Join-Path $Target "data"
  $previousData = Join-Path $Previous "data"

  if (
    $targetHash -eq $rollbackHash -and
    (Test-Path -LiteralPath $targetData) -and
    -not (Test-Path -LiteralPath $Handoff) -and
    -not (Test-Path -LiteralPath $Previous) -and
    (Test-Path -LiteralPath $failed) -and
    (App-TreeHash $failed) -eq $activeHash
  ) {
    if ([string]$State.selected_data_tree_sha256 -and
        (Data-TreeHash $targetData) -ne [string]$State.selected_data_tree_sha256) {
      throw "attached rollback data identity changed before recovery commit"
    }
    Remove-Item -LiteralPath $Journal -Force
    Write-Host "[ok] recovered completed rollback after verified data attachment"
    return "rollback_completed"
  }

  if ($targetHash -eq $activeHash -and $previousHash -eq $rollbackHash -and
      (Test-Path -LiteralPath $targetData) -and -not (Test-Path -LiteralPath $previousData)) {
    $candidate = Join-Path $targetData ([string]$State.restore_candidate_name)
    if ([string]$State.restore_candidate_name -and (Test-Path -LiteralPath $candidate)) {
      Remove-Item -LiteralPath $candidate -Force
    }
    Remove-Item -LiteralPath $Journal -Force
    Write-Host "[ok] recovered interrupted rollback before activation; active tree unchanged"
    return "rollback_aborted"
  }

  if ($previousHash -eq $rollbackHash -and (Test-Path -LiteralPath $Handoff)) {
    Ensure-SelectedRollbackDatabase $Handoff $State
    if (Test-Path -LiteralPath $Target) {
      if ((App-TreeHash $Target) -ne $activeHash) { throw "rollback active slot identity changed" }
      Move-ToFailed $Target $failed
    }
    if (-not (Test-Path -LiteralPath $Target)) { Move-DirectoryExact $Previous $Target }
  } elseif ($targetHash -ne $rollbackHash) {
    throw "interrupted rollback topology or data location is inconsistent; preserve all slots"
  }

  if ((App-TreeHash $Target) -ne $rollbackHash) { throw "rollback target identity changed" }
  $verificationData = if (Test-Path -LiteralPath $Handoff) { $Handoff } else { $targetData }
  Assert-PhysicalItem $verificationData -Directory | Out-Null
  Ensure-SelectedRollbackDatabase $verificationData $State
  if (-not [string]$State.selected_data_tree_sha256) {
    $State.selected_data_tree_sha256 = Data-TreeHash $verificationData
    Write-State $Journal $State "rollback_database_restored"
  }
  try {
    Invoke-Selftest $Target
    $database = Join-Path $verificationData "assesshub.db"
    if (Test-Path -LiteralPath $database) {
      Invoke-DatabasePreflight (Join-Path $Target "Atlas.exe") $database $Root | Out-Null
    }
    if ((App-TreeHash $Target) -ne $rollbackHash) {
      throw "rollback candidate changed during final verification"
    }
    if (Test-Path -LiteralPath $targetData) {
      throw "rollback candidate created data before verified recovery attachment"
    }
  } catch {
    Write-State $Journal $State "rollback_reversing"
    Restore-PreRollbackActive $Root $Target $Handoff $Previous $Journal $State
    return "rollback_reversed"
  }
  if (Test-Path -LiteralPath $Handoff) {
    if (Test-Path -LiteralPath $targetData) { throw "client data exists in two rollback locations" }
    Move-DirectoryExact $Handoff $targetData
  }
  if ([string]$State.selected_data_tree_sha256 -and
      (Data-TreeHash $targetData) -ne [string]$State.selected_data_tree_sha256) {
    throw "client data tree changed during rollback attachment"
  }
  Remove-Item -LiteralPath $Journal -Force
  Write-Host "[ok] recovered and completed interrupted Atlas rollback"
  return "rollback_completed"
}

function Recover-Interrupted(
  [string]$Root,
  [string]$Target,
  [string]$Incoming,
  [string]$Handoff,
  [string]$Previous,
  [string]$Retired,
  [string]$Journal
) {
  if (-not (Test-Path -LiteralPath $Journal)) { return "" }
  $state = Read-State $Journal
  if ($state.operation -eq "update") {
    Recover-Update $Root $Target $Incoming $Handoff $Previous $Retired $Journal $state
    return "update_recovered"
  } else {
    return (Recover-Rollback $Root $Target $Handoff $Previous $Journal $state)
  }
}

try {
  $destPath = Full-Path $Dest
  Assert-PhysicalItem $destPath -Directory | Out-Null
  Acquire-DestinationLock $destPath
  if ($TestHoldLockMilliseconds -gt 0) { Start-Sleep -Milliseconds $TestHoldLockMilliseconds }

  $target = Join-Path $destPath "Atlas"
  $incoming = Join-Path $destPath "Atlas.incoming"
  $handoff = Join-Path $destPath "Atlas.data-handoff"
  $previous = Join-Path $destPath "Atlas.previous"
  $retired = Join-Path $destPath "Atlas.retired"
  $journal = Join-Path $destPath "Atlas.update-state.json"
  $script:ReservedPackage = Join-Path $destPath ".Atlas.update-package.zip"
  $script:ReservedExtract = Join-Path $destPath ".Atlas.update-extract"
  $script:ReservedPreflight = Join-Path $destPath ".Atlas.database-preflight"

  $recoveryOutcome = Recover-Interrupted $destPath $target $incoming $handoff $previous $retired $journal
  if ($Rollback -and $recoveryOutcome -eq "rollback_completed") {
    Write-Host "[ok] requested rollback was completed by recovery"
    exit 0
  }
  if ($recoveryOutcome -eq "rollback_reversed") {
    throw "the interrupted rollback candidate failed verification; the pre-rollback active tree was restored"
  }
  if ($RestorePreUpdateDatabase -and -not $Rollback) {
    throw "-RestorePreUpdateDatabase requires -Rollback"
  }
  if (Test-Path -LiteralPath $handoff) {
    Assert-PhysicalItem $handoff -Directory | Out-Null
    throw "unowned Atlas.data-handoff exists without a recoverable transaction; preserve it and inspect"
  }

  if (Test-Path -LiteralPath $script:ReservedPackage) {
    Assert-PhysicalItem $script:ReservedPackage -File | Out-Null
    Remove-Item -LiteralPath $script:ReservedPackage -Force
  }
  if (Test-Path -LiteralPath $script:ReservedExtract) {
    Remove-ExactTree $script:ReservedExtract $destPath
  }
  if (Test-Path -LiteralPath $script:ReservedPreflight) {
    Remove-ExactTree $script:ReservedPreflight $destPath
  }
  if (Test-Path -LiteralPath $retired) {
    Remove-ExactTree $retired $destPath
  }

  if ($Rollback) {
    if ($Package -or $Source) { throw "-Rollback cannot be combined with -Package or -Source" }
    if (-not (Test-Path -LiteralPath $target) -or -not (Test-Path -LiteralPath $previous)) {
      throw "rollback needs both Atlas and Atlas.previous"
    }
    Assert-AppRoot $target
    Assert-AppRoot $previous
    if (Test-Path -LiteralPath (Join-Path $previous "data")) {
      throw "previous slot unexpectedly contains data"
    }
    $rollbackSlot = Get-RollbackSlotReceipt $destPath $target $previous
    $runId = [guid]::NewGuid().ToString("N")
    $activeHash = App-Hash $target
    $rollbackHash = App-Hash $previous
    $activeTreeHash = App-TreeHash $target
    $rollbackTreeHash = App-TreeHash $previous
    $data = Join-Path $target "data"
    Assert-PhysicalItem $data -Directory | Out-Null
    $database = Join-Path $data "assesshub.db"
    $selectedHash = ""
    $restoreCandidateName = ""
    $restoreReceiptName = ""
    $preservedReceiptName = ""
    $preservedReceiptSha256 = ""
    $originalHash = ""
    $preRollbackDataHash = Data-TreeHash $data
    Invoke-Selftest $previous
    $rollbackProbeData = Join-Path $previous "data"
    if (Test-Path -LiteralPath $rollbackProbeData) {
      $probeFailure = Join-Path $destPath ("Atlas.failed-rollback-preflight-data-" + $runId)
      Move-DirectoryExact $rollbackProbeData $probeFailure
      throw "rollback candidate created data during preflight selftest"
    }
    if ((App-TreeHash $previous) -ne $rollbackTreeHash) {
      throw "rollback candidate changed during preflight selftest"
    }
    if ((Data-TreeHash $data) -ne $preRollbackDataHash) {
      throw "rollback candidate selftest changed active client data"
    }

    if (Test-Path -LiteralPath $database) {
      Assert-DatabaseQuiescent $database
      if ($RestorePreUpdateDatabase) {
        $backup = Get-VerifiedPreUpdateBackup $data $rollbackSlot
        Require-FreeSpace $destPath (
          [int64](Get-Item -LiteralPath $database -Force).Length + [int64]$backup.bytes + 64MB
        ) "rollback database preservation and restore copies"
        Invoke-DatabasePreflight (Join-Path $previous "Atlas.exe") $backup.backup_path $destPath | Out-Null
        if (Test-Path -LiteralPath $rollbackProbeData) {
          Move-DirectoryExact $rollbackProbeData $probeFailure
          throw "rollback candidate created data during database preflight"
        }
        if ((App-TreeHash $previous) -ne $rollbackTreeHash) {
          throw "rollback candidate changed during database preflight"
        }
        if ((Data-TreeHash $data) -ne $preRollbackDataHash) {
          throw "rollback database preflight changed active client data"
        }
        $preserved = New-RollbackPreservedBackup $database $data $runId $activeHash $rollbackHash
        $preservedReceiptName = $preserved.receipt_name
        $preservedReceiptSha256 = $preserved.receipt_sha256
        $originalHash = $preserved.sha256
        $restoreCandidateName = ".atlas-rollback-selected-$runId.db"
        $candidatePath = Join-Path $data $restoreCandidateName
        $selected = Copy-ExclusiveVerified $backup.backup_path $candidatePath
        if ([string]$selected.sha256 -ne [string]$backup.sha256) {
          throw "selected rollback database differs from its verified backup"
        }
        $selectedHash = [string]$backup.sha256
        $restoreReceiptName = [string]$backup.receipt_name
      } else {
        Require-FreeSpace $destPath (
          [int64](Get-Item -LiteralPath $database -Force).Length + 64MB
        ) "rollback database compatibility copy"
        $preflight = Invoke-DatabasePreflight (Join-Path $previous "Atlas.exe") $database $destPath
        if (Test-Path -LiteralPath $rollbackProbeData) {
          Move-DirectoryExact $rollbackProbeData $probeFailure
          throw "rollback candidate created data during database preflight"
        }
        if ((App-TreeHash $previous) -ne $rollbackTreeHash) {
          throw "rollback candidate changed during database preflight"
        }
        if ((Data-TreeHash $data) -ne $preRollbackDataHash) {
          throw "rollback database preflight changed active client data"
        }
        $selectedHash = [string]$preflight.sha256
        $originalHash = [string]$preflight.sha256
      }
    } elseif ($RestorePreUpdateDatabase) {
      throw "cannot restore a pre-update database because no active database exists"
    }

    $failedName = "Atlas.failed-rollback-$runId"
    $state = [ordered]@{
      schema = "atlas.portable-transaction/2"
      operation = "rollback"
      phase = "rollback_prepared"
      run_id = $runId
      active_exe_sha256 = $activeHash
      rollback_exe_sha256 = $rollbackHash
      active_tree_sha256 = $activeTreeHash
      rollback_tree_sha256 = $rollbackTreeHash
      failed_name = $failedName
      restore_pre_update_database = [bool]$RestorePreUpdateDatabase
      restore_candidate_name = $restoreCandidateName
      restore_backup_receipt = $restoreReceiptName
      preserved_database_receipt = $preservedReceiptName
      preserved_database_receipt_sha256 = $preservedReceiptSha256
      original_database_sha256 = $originalHash
      selected_database_sha256 = $selectedHash
      selected_data_tree_sha256 = ""
    }
    Write-State $journal $state "rollback_prepared"
    if ($TestFailAfter -eq "rollback_prepared") { exit 70 }

    Move-DirectoryExact $data $handoff
    Write-State $journal $state "rollback_data_moved"
    if ($TestFailAfter -eq "rollback_data_moved") { exit 70 }

    if ($selectedHash) {
      Ensure-SelectedRollbackDatabase $handoff $state
    }
    $state["selected_data_tree_sha256"] = Data-TreeHash $handoff
    Write-State $journal $state "rollback_database_restored"
    if ($TestFailAfter -eq "rollback_database_restored") { exit 70 }

    $failed = Join-Path $destPath $failedName
    Move-DirectoryExact $target $failed
    Write-State $journal $state "rollback_active_moved"
    if ($TestFailAfter -eq "rollback_active_moved") { exit 70 }
    Move-DirectoryExact $previous $target
    Write-State $journal $state "rollback_activated"
    if ($TestFailAfter -eq "rollback_activated") { exit 70 }

    try {
      Invoke-Selftest $target
      if (Test-Path -LiteralPath (Join-Path $handoff "assesshub.db")) {
        Invoke-DatabasePreflight (Join-Path $target "Atlas.exe") (Join-Path $handoff "assesshub.db") $destPath | Out-Null
      }
      if ((App-TreeHash $target) -ne $rollbackTreeHash) {
        throw "rollback candidate changed during final verification"
      }
      if (Test-Path -LiteralPath (Join-Path $target "data")) {
        throw "rollback candidate created data before verified attachment"
      }
    } catch {
      Write-State $journal $state "rollback_reversing"
      Restore-PreRollbackActive $destPath $target $handoff $previous $journal $state
      throw "rollback candidate failed verification; restored the pre-rollback active tree"
    }
    if ((Data-TreeHash $handoff) -ne [string]$state.selected_data_tree_sha256) {
      Restore-PreRollbackActive $destPath $target $handoff $previous $journal $state
      throw "rollback verification changed client data; restored the pre-rollback active tree"
    }
    Move-DirectoryExact $handoff (Join-Path $target "data")
    Write-State $journal $state "rollback_data_attached"
    if ($TestFailAfter -eq "rollback_data_attached") { exit 70 }
    Remove-Item -LiteralPath $journal -Force
    Write-Host "[ok] rolled back to Atlas.previous; newer application tree retained at $failed"
    exit 0
  }

  if ($Package -and $Source) { throw "choose either -Package or -Source, not both" }
  if (Test-Path -LiteralPath $incoming) {
    throw "stale Atlas.incoming exists without a journal; preserve it and inspect before retrying"
  }

  $runId = [guid]::NewGuid().ToString("N")
  $sourcePath = ""
  $candidateIdentity = $null
  [int64]$sourceBytes = 0
  [int64]$databaseBytes = 0
  $activeDb = Join-Path $target "data\assesshub.db"
  if (Test-Path -LiteralPath $activeDb) { $databaseBytes = [int64](Get-Item -LiteralPath $activeDb -Force).Length }

  if ($Package) {
    if ($SkipSelftest) { throw "-SkipSelftest is forbidden for a release package" }
    $script:PackageMode = $true
    $packagePath = Full-Path $Package
    $packageItem = Assert-PhysicalItem $packagePath -File
    Require-FreeSpace $destPath ([int64]$packageItem.Length + 64MB) "the verified package copy"
    $packageCopy = Copy-ExclusiveVerified $packagePath $script:ReservedPackage
    $zipReceipt = Invoke-ReleaseVerifier @(
      "--zip", $script:ReservedPackage, "--expected-sha256", [string]$packageCopy.sha256
    )
    if (
      [string]$zipReceipt.schema -ne "atlas.portable-verification/1" -or
      [string]$zipReceipt.status -ne "SELF_CONSISTENCY_PASS" -or
      [string]$zipReceipt.authentication -ne "none_self_authored_consistency_only" -or
      [string]$zipReceipt.zip_sha256 -ne [string]$packageCopy.sha256 -or
      $zipReceipt.zip_digest_expectation_matched -ne $true
    ) { throw "verified package receipt did not bind the same-volume package copy" }
    if ((File-Sha256 $script:ReservedPackage) -ne [string]$packageCopy.sha256) {
      throw "same-volume package copy changed after verification"
    }
    $expandedBytes = Expanded-ZipBytes $script:ReservedPackage
    Require-FreeSpace $destPath ($expandedBytes + (2 * $databaseBytes) + 64MB) "package extraction and database safety copies"
    New-Item -ItemType Directory -Path $script:ReservedExtract | Out-Null
    Expand-Archive -LiteralPath $script:ReservedPackage -DestinationPath $script:ReservedExtract
    if ((File-Sha256 $script:ReservedPackage) -ne [string]$packageCopy.sha256) {
      throw "same-volume package copy changed during extraction"
    }
    $sourcePath = Join-Path $script:ReservedExtract "Atlas"
    $installedReceipt = Invoke-ReleaseVerifier @("--installed", $sourcePath)
    if (
      [string]$installedReceipt.runtime_member_set_digest -ne [string]$zipReceipt.member_set_digest -or
      -not (Same-SourceIdentity $installedReceipt.source $zipReceipt.source)
    ) { throw "extracted candidate identity differs from the verified package" }
    $candidateIdentity = [ordered]@{
      kind = "package"
      package_sha256 = [string]$packageCopy.sha256
      member_set_digest = [string]$zipReceipt.member_set_digest
      source = $zipReceipt.source
      atlas_exe_sha256 = (File-Sha256 (Join-Path $sourcePath "Atlas.exe"))
      app_tree_sha256 = (App-TreeHash $sourcePath)
    }
    $sourceBytes = [int64](Get-ChildItem -LiteralPath $sourcePath -File -Recurse | Measure-Object Length -Sum).Sum
  } else {
    if (-not $Source) { $Source = Join-Path $PSScriptRoot "dist\Atlas" }
    $sourcePath = Full-Path $Source
    if (-not (Test-Path -LiteralPath $sourcePath)) {
      throw "no built bundle exists at $sourcePath; build it first"
    }
    Assert-PhysicalTree $sourcePath
    Assert-AppRoot $sourcePath
    $sourceBytes = [int64](Get-ChildItem -LiteralPath $sourcePath -File -Recurse | Measure-Object Length -Sum).Sum
    Require-FreeSpace $destPath ($sourceBytes + (2 * $databaseBytes) + 64MB) "candidate staging and database safety copies"
    $candidateIdentity = [ordered]@{
      kind = "source"
      package_sha256 = $null
      member_set_digest = $null
      source = $null
      atlas_exe_sha256 = (File-Sha256 (Join-Path $sourcePath "Atlas.exe"))
      app_tree_sha256 = (App-TreeHash $sourcePath)
    }
  }

  $hadActive = Test-Path -LiteralPath $target
  $activeHash = if ($hadActive) { App-Hash $target } else { "" }
  $activeTreeHash = if ($hadActive) { App-TreeHash $target } else { "" }
  $priorPrevious = Test-Path -LiteralPath $previous
  $priorPreviousHash = ""
  $priorPreviousTreeHash = ""
  if ($priorPrevious) {
    Assert-AppRoot $previous
    if (Test-Path -LiteralPath (Join-Path $previous "data")) {
      throw "Atlas.previous unexpectedly contains data; refusing to rotate it"
    }
    $priorPreviousHash = App-Hash $previous
    $priorPreviousTreeHash = App-TreeHash $previous
  }
  $state = [ordered]@{
    schema = "atlas.portable-transaction/2"
    operation = "update"
    phase = "staging"
    run_id = $runId
    had_active = [bool]$hadActive
    active_exe_sha256 = $activeHash
    active_tree_sha256 = $activeTreeHash
    prior_previous_present = [bool]$priorPrevious
    prior_previous_exe_sha256 = $priorPreviousHash
    prior_previous_tree_sha256 = $priorPreviousTreeHash
    candidate_identity = $candidateIdentity
    failed_name = "Atlas.failed-update-$runId"
    database_backup_receipt = ""
    database_backup_receipt_sha256 = ""
    active_database_sha256 = ""
    data_tree_sha256 = ""
  }
  Write-State $journal $state "staging"
  if ($TestFailAfter -eq "staging") { exit 70 }

  if ($script:PackageMode) {
    Move-DirectoryExact $sourcePath $incoming
    Verify-InstalledCandidate $incoming $candidateIdentity
  } else {
    $sourceData = Join-Path $sourcePath "data"
    robocopy $sourcePath $incoming /MIR /XD $sourceData /R:2 /W:5 /NFL /NDL /NJH /NJS /NP | Out-Null
    $rc = $LASTEXITCODE
    if ($rc -ge 8) { throw "staging copy failed (robocopy exit $rc); the active tree is untouched" }
  }
  Assert-CandidateIdentity $incoming $candidateIdentity
  Write-State $journal $state "staged"
  if ($TestFailAfter -eq "staged") { exit 70 }
  $preCandidateDataHash = ""
  if ($hadActive) {
    $activeDataRoot = Join-Path $target "data"
    if (-not (Test-Path -LiteralPath $activeDataRoot)) {
      New-Item -ItemType Directory -Path $activeDataRoot | Out-Null
    }
    $preCandidateDataHash = Data-TreeHash $activeDataRoot
  }
  Invoke-Selftest $incoming
  Assert-CandidateIdentity $incoming $candidateIdentity
  if ($hadActive -and (Data-TreeHash (Join-Path $target "data")) -ne $preCandidateDataHash) {
    throw "candidate selftest changed client data before handoff"
  }

  if ($hadActive -and -not $SkipSelftest -and (Test-Path -LiteralPath $activeDb)) {
    $preflight = Invoke-DatabasePreflight (Join-Path $incoming "Atlas.exe") $activeDb $destPath
    Assert-CandidateIdentity $incoming $candidateIdentity
    if ((Data-TreeHash (Join-Path $target "data")) -ne $preCandidateDataHash) {
      throw "candidate database preflight changed the active client data tree"
    }
    $backup = New-PreUpdateBackup $activeDb (Split-Path $activeDb -Parent) $runId $activeHash $candidateIdentity $preflight.sha256
    $state["database_backup_receipt"] = $backup.receipt_name
    $state["database_backup_receipt_sha256"] = $backup.receipt_sha256
    $state["active_database_sha256"] = $backup.sha256
  }
  Write-State $journal $state "prepared"
  if ($TestFailAfter -eq "prepared") { exit 70 }

  if ($priorPrevious) {
    if (Test-Path -LiteralPath $retired) { throw "reserved Atlas.retired slot already exists" }
    Move-DirectoryExact $previous $retired
    Write-State $journal $state "previous_retired"
    if ($TestFailAfter -eq "previous_retired") { exit 70 }
  }

  $incomingData = Join-Path $incoming "data"
  if ($hadActive) {
    $data = Join-Path $target "data"
    if (-not (Test-Path -LiteralPath $data)) { New-Item -ItemType Directory -Path $data | Out-Null }
    Assert-PhysicalItem $data -Directory | Out-Null
    if ([string]$state.active_database_sha256) {
      Assert-DatabaseQuiescent $activeDb
      if ((File-Sha256 $activeDb) -ne [string]$state.active_database_sha256) {
        throw "active database changed after its verified backup was frozen"
      }
    }
    if (Test-Path -LiteralPath $incomingData) { throw "candidate unexpectedly contains top-level data" }
    $state["data_tree_sha256"] = Data-TreeHash $data
    Write-State $journal $state "prepared"
    Move-DirectoryExact $data $handoff
    if ((Data-TreeHash $handoff) -ne [string]$state.data_tree_sha256) {
      throw "client data tree changed during handoff"
    }
  } elseif (Test-Path -LiteralPath $incomingData) {
    throw "candidate unexpectedly contains top-level data"
  }
  Write-State $journal $state "data_moved"
  if ($TestFailAfter -eq "data_moved") { exit 70 }

  if ($hadActive) { Move-DirectoryExact $target $previous }
  Write-State $journal $state "active_moved"
  if ($TestFailAfter -eq "active_moved") { exit 70 }
  Move-DirectoryExact $incoming $target
  Write-State $journal $state "activated"
  if ($TestFailAfter -eq "activated") { exit 70 }

  try {
    Assert-CandidateIdentity $target $candidateIdentity
    Invoke-Selftest $target
    $database = Join-Path $handoff "assesshub.db"
    if (Test-Path -LiteralPath $database) {
      Invoke-DatabasePreflight (Join-Path $target "Atlas.exe") $database $destPath | Out-Null
    }
    Assert-CandidateIdentity $target $candidateIdentity
    if (Test-Path -LiteralPath (Join-Path $target "data")) {
      throw "candidate created data before verified attachment"
    }
    if ($hadActive -and (Data-TreeHash $handoff) -ne [string]$state.data_tree_sha256) {
      throw "candidate verification changed the detached client data tree"
    }
  } catch {
    $verificationError = $_.Exception.Message
    $stateNow = Read-State $journal
    Recover-Update $destPath $target $incoming $handoff $previous $retired $journal $stateNow -ForceRollback
    if ($hadActive) {
      throw "activated candidate failed verification ($verificationError); restored the prior active tree"
    }
    throw "first-install candidate failed verification ($verificationError); quarantined it and left no active Atlas tree"
  }
  Write-State $journal $state "data_attach_pending"
  if ($TestFailAfter -eq "data_attach_pending") { exit 70 }
  $targetData = Join-Path $target "data"
  if ($hadActive) {
    if (Test-Path -LiteralPath $targetData) { throw "candidate created data before verified attachment" }
    Move-DirectoryExact $handoff $targetData
    if ((Data-TreeHash $targetData) -ne [string]$state.data_tree_sha256) {
      throw "client data tree changed during verified attachment"
    }
  } else {
    New-Item -ItemType Directory -Path $targetData | Out-Null
  }
  Write-State $journal $state "data_attached"
  if ($TestFailAfter -eq "data_attached") { exit 70 }
  if ($hadActive) {
    $slot = Prepare-RollbackSlotReceipt $destPath $state (App-TreeHash $target) (App-TreeHash $previous)
    $state["rollback_slot_prepared_name"] = $slot.name
    $state["rollback_slot_prepared_sha256"] = $slot.sha256
    Write-State $journal $state "rollback_slot_prepared"
    if ($TestFailAfter -eq "rollback_slot_prepared") { exit 70 }
    Complete-RollbackSlotReceipt $destPath $state
    Write-State $journal $state "rollback_slot_receipted"
    if ($TestFailAfter -eq "rollback_slot_receipted") { exit 70 }
  }
  Remove-Item -LiteralPath $journal -Force
  if (Test-Path -LiteralPath $retired) { Remove-ExactTree $retired $destPath }
  $rollbackNote = if (Test-Path -LiteralPath $previous) { "prior app retained at Atlas.previous" } else { "first installation; no previous app exists" }
  Write-Host "[ok] activated $target; data\ preserved; $rollbackNote"
  exit 0
} catch {
  $message = $_.Exception.Message
  Write-Host "[fail] $message"
  if ($message -match "used by another|being used|access.*denied|destination lock") {
    Write-Host "       A file is IN USE. Close Atlas and the browser window it opened, then retry; any journal recovers first."
  }
  exit 1
} finally {
  foreach ($path in @($script:ReservedPackage)) {
    if ($path -and (Test-Path -LiteralPath $path)) {
      Remove-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
    }
  }
  foreach ($path in @($script:ReservedExtract, $script:ReservedPreflight)) {
    if ($path -and (Test-Path -LiteralPath $path)) {
      try { Remove-ExactTree $path (Split-Path $path -Parent) } catch { }
    }
  }
  if ($script:LockHandle) { $script:LockHandle.Dispose() }
}
