<#
Optional PowerShell 5.1 wrapper; no repository or host Python is used.
powershell -File portable\make_stick.ps1 -Dest C:\AtlasField -Package C:\release\Atlas-3.33.0rc7-windows-x64.zip -ExpectedSha256 <published-sha256>
First install: -Dest C:\AtlasField -AtlasExe C:\extracted\Atlas\Atlas.exe -Package ZIP -ExpectedSha256 SHA
Update: -Dest C:\AtlasField -Package ZIP -ExpectedSha256 SHA
Rollback: -Dest C:\AtlasField -Rollback [-RestorePreUpdateDatabase]
Explicit journal recovery: -Dest C:\AtlasField -Recover
#>
param(
  [Parameter(Mandatory = $true)][string]$Dest,
  [string]$Package = "",
  [string]$ExpectedSha256 = "",
  [string]$AtlasExe = "",
  [switch]$Rollback,
  [switch]$RestorePreUpdateDatabase,
  [switch]$Recover
)
$ErrorActionPreference = "Stop"
$destRoot = [IO.Path]::GetFullPath($Dest)
if ($destRoot.Length -gt [IO.Path]::GetPathRoot($destRoot).Length) { $destRoot = $destRoot.TrimEnd('\', '/') }
if ($Recover -and ($Package -or $ExpectedSha256 -or $AtlasExe -or $Rollback -or $RestorePreUpdateDatabase)) {
  throw "-Recover cannot ignore requested install, update or rollback options"
}
if ($Rollback -and ($Package -or $ExpectedSha256 -or $AtlasExe)) { throw "rollback cannot take package, digest or bootstrap options" }
if ($RestorePreUpdateDatabase -and -not $Rollback) { throw "-RestorePreUpdateDatabase requires -Rollback" }
$journal = Join-Path $destRoot "Atlas.update-state.json"
if ((Test-Path -LiteralPath $journal) -and -not $Recover) {
  throw "journaled maintenance is incomplete; explicitly use -Recover and preserve every Atlas* path"
}
$installed = Join-Path $destRoot "Atlas\Atlas.exe"
if ($Recover) {
  if (-not (Test-Path -LiteralPath $journal -PathType Leaf)) { throw "no journaled maintenance request to recover" }
  if (Test-Path -LiteralPath $installed -PathType Leaf) { & $installed --recover $destRoot; exit $LASTEXITCODE }
  $pointerPath = Join-Path $destRoot "Atlas.maintenance.json"
  if ((Get-Item -LiteralPath $pointerPath).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "recovery pointer is redirected" }
  $pointer = Get-Content -LiteralPath $pointerPath -Raw | ConvertFrom-Json
  if ($pointer.schema -ne "atlas.maintenance-recovery/1" -or
      $pointer.helper -cnotmatch '^Atlas\.maintenance-[0-9a-f]{32}/Atlas/Atlas\.exe$') { throw "unsupported recovery pointer" }
  $helper = [IO.Path]::GetFullPath((Join-Path $destRoot $pointer.helper))
  $item = Get-Item -LiteralPath $helper
  while ($item) {
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "recovery path is redirected" }
    if ($item.FullName -eq $destRoot) { break }
    $item = if ($item.PSIsContainer) { $item.Parent } else { $item.Directory }
  }
  if (-not $item) { throw "recovery path escaped its destination" }
  if ((Get-FileHash -LiteralPath $helper -Algorithm SHA256).Hash.ToLowerInvariant() -cne $pointer.helper_exe_sha256) {
    throw "recorded installed-version recovery helper identity changed"
  }
  & $helper --recover $destRoot
  exit $LASTEXITCODE
}
if (Test-Path -LiteralPath $installed -PathType Leaf) {
  if ($AtlasExe) { throw "an update must use the installed Atlas.exe" }
  $nonce = [guid]::NewGuid().ToString("N")
  $result = Join-Path $destRoot ("Atlas.maintenance-result." + $nonce + ".json")
  $arguments = @("--maintenance-result", $result)
  if ($Rollback) {
    $arguments += "--rollback"
    if ($RestorePreUpdateDatabase) { $arguments += "--restore-pre-update-database" }
  } else { $arguments += @("--update", $Package, "--expected-sha256", $ExpectedSha256) }
  & $installed @arguments
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
  $deadline = [DateTime]::UtcNow.AddMinutes(30)
  while (-not (Test-Path -LiteralPath $result -PathType Leaf)) {
    if ([DateTime]::UtcNow -ge $deadline) { throw "maintenance is not verified complete; inspect $result and preserve Atlas* paths" }
    Start-Sleep -Milliseconds 250
  }
  $receipt = Get-Content -LiteralPath $result -Raw | ConvertFrom-Json
  if ($receipt.schema -ne "atlas.maintenance-result/1" -or $receipt.nonce -cne $nonce -or
      $receipt.verifier_origin -ne "installed_atlas" -or
      -not ($receipt.exit_code -is [int] -or $receipt.exit_code -is [long]) -or
      $receipt.status -ne $(if ($receipt.exit_code -eq 0) { "complete" } else { "refused" })) { throw "unsupported or inconsistent maintenance receipt" }
  if ($receipt.exit_code -ne 0) { Write-Error ("Atlas maintenance refused: " + $receipt.error + "; result: " + $result) -ErrorAction Continue }
  Write-Output $receipt
  exit ([int]$receipt.exit_code)
}
if ($Rollback) { throw "no installed Atlas.exe for rollback" }
if (-not $AtlasExe) { throw "first install needs -AtlasExe pointing to the hash-checked extracted Atlas.exe" }
& $AtlasExe --install $destRoot --package $Package --expected-sha256 $ExpectedSha256
exit $LASTEXITCODE
