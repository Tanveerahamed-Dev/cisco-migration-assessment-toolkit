<#
Optional PowerShell 5.1 wrapper around the installed Atlas executable.
Copy this file anywhere; no repository checkout or host Python is used.

powershell -File portable\make_stick.ps1 -Dest E:\ -Package C:\release\Atlas-3.33.0rc7-windows-x64.zip -ExpectedSha256 <published-sha256>

First install: also pass -AtlasExe C:\extracted\Atlas\Atlas.exe.
Updates and rollback always use Dest\Atlas\Atlas.exe (the installed verifier).
#>
param(
  [Parameter(Mandatory = $true)][string]$Dest,
  [string]$Package = "",
  [string]$ExpectedSha256 = "",
  [string]$AtlasExe = "",
  [switch]$Rollback,
  [switch]$RestorePreUpdateDatabase
)
$ErrorActionPreference = "Stop"
$destRoot = [IO.Path]::GetFullPath($Dest)
$journal = Join-Path $destRoot "Atlas.update-state.json"
if (Test-Path -LiteralPath $journal -PathType Leaf) {
  $pointer = Get-Content -LiteralPath (Join-Path $destRoot "Atlas.maintenance.json") -Raw | ConvertFrom-Json
  if ($pointer.schema -ne "atlas.maintenance-recovery/1" -or
      $pointer.helper -cnotmatch '^Atlas\.maintenance-[0-9a-f]{32}/Atlas/Atlas\.exe$') {
    throw "unsupported maintenance recovery pointer; preserve every Atlas* path"
  }
  $helper = Join-Path $destRoot $pointer.helper
  $helperItem = Get-Item -LiteralPath $helper
  if ($helperItem.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "recovery executable is redirected" }
  $item = $helperItem.Directory
  while ($item.FullName -ne $destRoot) {
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "recovery path is redirected" }
    $item = $item.Parent
    if (-not $item) { throw "recovery path escaped its destination" }
  }
  if ((Get-FileHash -LiteralPath $helper -Algorithm SHA256).Hash.ToLowerInvariant() -cne $pointer.helper_exe_sha256) {
    throw "installed-version recovery helper identity changed"
  }
  & $helper --recover $destRoot
  exit $LASTEXITCODE
}
$installed = Join-Path ([IO.Path]::GetFullPath($Dest)) "Atlas\Atlas.exe"
if ($Rollback -and $Package) { throw "choose update or rollback" }
if ($RestorePreUpdateDatabase -and -not $Rollback) {
  throw "-RestorePreUpdateDatabase requires -Rollback"
}
if (Test-Path -LiteralPath $installed -PathType Leaf) {
  if ($AtlasExe) { throw "an update must use the installed Atlas.exe" }
  $result = Join-Path ([IO.Path]::GetFullPath($Dest)) ("Atlas.maintenance-result." + [guid]::NewGuid().ToString("N") + ".json")
  $arguments = @("--maintenance-result", $result)
  if ($Rollback) {
    $arguments += "--rollback"
    if ($RestorePreUpdateDatabase) { $arguments += "--restore-pre-update-database" }
  } else {
    $arguments += @("--update", $Package, "--expected-sha256", $ExpectedSha256)
  }
  & $installed @arguments
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
  $deadline = [DateTime]::UtcNow.AddMinutes(30)
  while (-not (Test-Path -LiteralPath $result -PathType Leaf)) {
    if ([DateTime]::UtcNow -ge $deadline) {
      throw "maintenance is not verified complete; preserve Atlas* paths and inspect $result"
    }
    Start-Sleep -Milliseconds 250
  }
  $receipt = Get-Content -LiteralPath $result -Raw | ConvertFrom-Json
  if ($receipt.schema -ne "atlas.maintenance-result/1") { throw "unsupported maintenance receipt" }
  Write-Output $receipt
  exit ([int]$receipt.exit_code)
}
if ($Rollback) { throw "no installed Atlas.exe for rollback" }
if (-not $AtlasExe) { throw "first install needs -AtlasExe pointing to the hash-checked extracted Atlas.exe" }
& $AtlasExe --install $Dest --package $Package --expected-sha256 $ExpectedSha256
exit $LASTEXITCODE
