<# Verify every Atlas PE with Windows Authenticode policy and emit a bounded receipt. #>
param(
  [Parameter(Mandatory = $true)][string]$Bundle,
  [string]$Manifest = "",
  [string]$ExpectedThumbprint = "",
  [string]$OutReceipt = ""
)

$ErrorActionPreference = "Stop"
$VerifyOs = '2:10.0.0'
$bundlePath = [IO.Path]::GetFullPath($Bundle)
if (-not (Test-Path -LiteralPath $bundlePath -PathType Container)) { throw "Bundle is not a directory" }
$bundlePrefix = $bundlePath.TrimEnd('\') + '\'

function File-Sha256([string]$Path) {
  $stream = [IO.File]::OpenRead([IO.Path]::GetFullPath($Path))
  try {
    $sha = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($sha.ComputeHash($stream)) -replace '-', '').ToLowerInvariant() }
    finally { $sha.Dispose() }
  } finally { $stream.Dispose() }
}

$manifestPath = if ($Manifest) { [IO.Path]::GetFullPath($Manifest) } else {
  Join-Path $bundlePath 'release-metadata\portable-member-manifest.json'
}
if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
  throw "Portable member manifest is required for the exact PE denominator"
}
$manifestHash = File-Sha256 $manifestPath
try { $manifestObject = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json } catch {
  throw "Portable member manifest is unreadable"
}
if ($manifestObject.schema -ne 'atlas.portable-member-manifest/1') {
  throw "Portable member manifest schema is unsupported"
}
$expected = ($ExpectedThumbprint -replace '[^0-9A-Fa-f]', '').ToLowerInvariant()
if ($expected -and $expected.Length -ne 40) { throw "Expected thumbprint must be 40 hexadecimal characters" }

$seen = @{}
$files = @(
  foreach ($row in @($manifestObject.members)) {
    if ($row.executable -ne $true) { continue }
    $relative = [string]$row.path
    $claimedHash = [string]$row.sha256
    if (-not $relative -or $relative.Contains('\') -or $relative.Contains(':') -or $claimedHash -notmatch '^[0-9a-f]{64}$') {
      throw "Portable manifest contains an unsafe PE row"
    }
    $key = $relative.ToLowerInvariant()
    if ($seen.ContainsKey($key)) { throw "Portable manifest PE paths collide under Windows casing" }
    $seen[$key] = $true
    $full = [IO.Path]::GetFullPath((Join-Path $bundlePath ($relative.Replace('/', '\'))))
    if (-not $full.StartsWith($bundlePrefix, [StringComparison]::OrdinalIgnoreCase)) {
      throw "Portable manifest PE path escapes the bundle"
    }
    if (-not (Test-Path -LiteralPath $full -PathType Leaf)) {
      throw "Portable manifest PE member is missing: $relative"
    }
    $observedHash = File-Sha256 $full
    if ($observedHash -ne $claimedHash) {
      throw "Portable manifest PE hash differs before Authenticode verification: $relative"
    }
    [pscustomobject]@{ FullName = $full; Relative = $relative; Sha256 = $claimedHash }
  }
)
if (-not $files) { throw "Bundle contains no PE members" }

function Resolve-SignTool {
  $choices = @(
    Get-ChildItem 'C:\Program Files (x86)\Windows Kits\10\bin' -Directory -ErrorAction SilentlyContinue |
      ForEach-Object {
        try { $version = [version]$_.Name } catch { $version = $null }
        $path = Join-Path $_.FullName 'x64\signtool.exe'
        if ($version -and (Test-Path -LiteralPath $path -PathType Leaf)) {
          [pscustomobject]@{ Version = $version; Path = $path }
        }
      } | Sort-Object Version -Descending
  )
  foreach ($choice in $choices) {
    $signature = Get-AuthenticodeSignature -LiteralPath $choice.Path
    if ($signature.Status -eq 'Valid' -and $signature.SignerCertificate.Subject -match '(^|,\s*)O=Microsoft Corporation(,|$)') {
      return $choice.Path
    }
  }
  throw "No Microsoft-signed Windows SDK x64 signtool.exe is available"
}
$signtool = Resolve-SignTool

$members = @()
$failed = $false
foreach ($file in $files) {
  & $signtool verify /pa /all /tw /o $VerifyOs /v $file.FullName | Out-Null
  $signtoolValid = $LASTEXITCODE -eq 0
  $signature = Get-AuthenticodeSignature -LiteralPath $file.FullName
  $thumb = if ($signature.SignerCertificate) { $signature.SignerCertificate.Thumbprint.ToLowerInvariant() } else { $null }
  $valid = $signtoolValid -and $signature.Status -eq 'Valid' -and $signature.TimeStamperCertificate -and (-not $expected -or $thumb -eq $expected)
  if (-not $valid) { $failed = $true }
  $afterHash = File-Sha256 $file.FullName
  if ($afterHash -ne $file.Sha256) {
    throw "PE member changed during Authenticode verification: $($file.Relative)"
  }
  $members += [ordered]@{
    path = $file.Relative
    sha256 = $afterHash
    status = [string]$signature.Status
    signtool_policy_valid = [bool]$signtoolValid
    publisher_subject = if ($signature.SignerCertificate) { $signature.SignerCertificate.Subject } else { $null }
    publisher_thumbprint = $thumb
    publisher_public_key_oid = if ($signature.SignerCertificate) { $signature.SignerCertificate.PublicKey.Oid.Value } else { $null }
    timestamp_present = [bool]$signature.TimeStamperCertificate
    timestamp_verified = [bool]($signtoolValid -and $signature.TimeStamperCertificate)
    timestamp_subject = if ($signature.TimeStamperCertificate) { $signature.TimeStamperCertificate.Subject } else { $null }
    expected_publisher = if ($expected) { $thumb -eq $expected } else { $null }
  }
}
$publisherThumbprints = @($members | Where-Object { $_.publisher_thumbprint } |
  ForEach-Object { $_.publisher_thumbprint } | Sort-Object -Unique)
if ((File-Sha256 $manifestPath) -ne $manifestHash) {
  throw "Portable member manifest changed during Authenticode verification"
}
$receipt = [ordered]@{
  schema = 'atlas.portable-authenticode-verification/1'
  status = if ($failed) { 'fail' } else { 'pass' }
  subject = [ordered]@{
    source = $manifestObject.source
    manifest_sha256 = $manifestHash
    member_set_digest = $manifestObject.summary.member_set_digest
    executable_member_count = $files.Count
  }
  policy = [ordered]@{
    authenticode = 'Default Authentication Verification Policy (/pa)'
    all_signatures = $true
    timestamp_required = $true
    target_os = $VerifyOs
    signing_lane_certificate_store = 'CurrentUser\My'
    promotion_effect = 'NONE'
  }
  expected_thumbprint = if ($expected) { $expected } else { $null }
  publisher_thumbprints = $publisherThumbprints
  signtool = [ordered]@{
    name = [IO.Path]::GetFileName($signtool)
    sha256 = File-Sha256 $signtool
    file_version = (Get-Item -LiteralPath $signtool).VersionInfo.FileVersion
  }
  members = $members
}
if ($OutReceipt) {
  $outPath = [IO.Path]::GetFullPath($OutReceipt)
  if ($outPath.StartsWith($bundlePrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Authenticode receipt must be written outside the verified bundle"
  }
  $json = $receipt | ConvertTo-Json -Depth 8
  [IO.File]::WriteAllText($outPath, $json + "`n", [Text.UTF8Encoding]::new($false))
}
if ($failed) { Write-Error "Authenticode verification failed"; exit 1 }
Write-Host "[ok] Authenticode verified $($files.Count) PE member(s)"
exit 0
