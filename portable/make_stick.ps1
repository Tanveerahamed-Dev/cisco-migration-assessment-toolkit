<#
Lay out / update the Atlas stick (ADR-0004 P2/P3).

Copies the built one-folder bundle to <Dest>\Atlas. Re-running is the UPDATE flow: everything is
replaced wholesale EXCEPT the top-level data\ (the stick's only writable dir, where client
evidence lives) via robocopy /MIR with an ABSOLUTE /XD pin. A bare '/XD data' would also exclude
_internal\cisco_toolkit\data (the KB packs) from the copy and silently degrade the app.

  powershell -File portable\make_stick.ps1 -Dest E:\
  powershell -File portable\make_stick.ps1 -Dest D:\somewhere -Source C:\other\dist\Atlas

PowerShell 5.1-safe. ASCII ONLY in this file: PS 5.1 reads BOM-less files as ANSI, and a UTF-8
em-dash decodes into a cp1252 smart quote that TERMINATES STRINGS (found by test, not in theory).
#>
param(
  [Parameter(Mandatory = $true)][string]$Dest,
  [string]$Source = ""
)

if (-not $Source) { $Source = Join-Path $PSScriptRoot "dist\Atlas" }

if (-not (Test-Path (Join-Path $Source "Atlas.exe"))) {
  Write-Host "[fail] no bundle at $Source (Atlas.exe missing)."
  Write-Host "       Build it first:  python portable/build_atlas.py"
  exit 1
}
if (-not (Test-Path $Dest)) {
  Write-Host "[fail] destination $Dest does not exist (is the stick mounted?)"
  exit 1
}

$target = Join-Path $Dest "Atlas"
$updating = Test-Path $target
$dataDir = Join-Path $target "data"

# /R and /W are NOT optional here. Robocopy's DEFAULTS are /R:1000000 /W:30 - a million retries,
# 30s apart (~347 days). Paired with the quiet switches below that is a SILENT multi-hour hang with
# no output at all, which is what happened on 2026-07-21: Atlas.exe had auto-opened the browser
# FROM the stick, so Chrome (and its child processes) held DLLs under _internal open, robocopy hit
# ERROR 32 on one file and sat retrying for ~5 hours. Fail fast and say which file instead.
robocopy $Source $target /MIR /XD $dataDir /R:2 /W:5 /NFL /NDL /NJH /NJS /NP | Out-Null
$rc = $LASTEXITCODE
if ($rc -ge 8) {
  Write-Host "[fail] robocopy could not copy every file (exit $rc)."
  Write-Host "       Most likely a file on the stick is IN USE. Close Atlas AND the browser tab"
  Write-Host "       it opened (the browser inherits the stick as its working directory and pins"
  Write-Host "       files under _internal), then re-run this script."
  Write-Host "       To see exactly which file: robocopy `"$Source`" `"$target`" /MIR /XD `"$dataDir`" /R:1 /W:1 /NP"
  exit 1
}

if ($updating) {
  Write-Host "[ok] updated $target  (data\ preserved - client evidence untouched)"
} else {
  Write-Host "[ok] created $target"
}
Write-Host "Next, on the target machine:  $target\Atlas.exe --selftest   (expect SELFTEST: PASS)"
exit 0
