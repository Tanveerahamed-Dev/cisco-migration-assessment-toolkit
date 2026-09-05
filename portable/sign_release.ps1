<# Sign every unsigned Atlas PE with one explicit certificate, then verify and receipt it.

No certificate is discovered by subject name, no PFX/password is accepted, and no key material is
stored in source. The explicit certificate must be in CurrentUser\My; machine-store key use is
outside this non-elevated lane. Use -ProductionCertificate only after the external identity/custody
decision.
#>
param(
  [Parameter(Mandatory = $true)][string]$Bundle,
  [Parameter(Mandatory = $true)][string]$SignedBundle,
  [Parameter(Mandatory = $true)][string]$Manifest,
  [Parameter(Mandatory = $true)][string]$Thumbprint,
  [Parameter(Mandatory = $true)][ValidatePattern('^https://')][string]$TimestampUrl,
  [Parameter(Mandatory = $true)][string]$OutReceipt,
  [switch]$ProductionCertificate
)

$ErrorActionPreference = "Stop"
$VerifyOs = '2:10.0.0'
$timestampUri = [Uri]$TimestampUrl
if ($timestampUri.Scheme -ne 'https' -or $timestampUri.UserInfo -or $timestampUri.Query -or $timestampUri.Fragment) {
  throw "Timestamp URL must be credential-free HTTPS without query or fragment"
}
$unsignedPath = [IO.Path]::GetFullPath($Bundle)
if (-not (Test-Path -LiteralPath $unsignedPath -PathType Container)) { throw "Unsigned bundle is not a directory" }
$bundlePath = [IO.Path]::GetFullPath($SignedBundle)
$repositoryPath = [IO.Path]::GetFullPath((Split-Path $PSScriptRoot -Parent)).TrimEnd('\') + '\'
if ($bundlePath.StartsWith($repositoryPath, [StringComparison]::OrdinalIgnoreCase)) {
  throw "Signed staging bundle must be outside the clean source repository"
}
if ($bundlePath -eq $unsignedPath -or $bundlePath.StartsWith($unsignedPath.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase) -or $unsignedPath.StartsWith($bundlePath.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) {
  throw "Signed staging bundle must be a fresh path disjoint from the unsigned bundle"
}
if (Test-Path -LiteralPath $bundlePath) { throw "Signed staging bundle must not already exist" }
$bundleParent = Split-Path $bundlePath -Parent
if (-not (Test-Path -LiteralPath $bundleParent -PathType Container)) { throw "Signed staging parent does not exist" }
robocopy $unsignedPath $bundlePath /E /COPY:DAT /DCOPY:T /R:2 /W:2 /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { throw "Unsigned-to-signed staging copy failed (robocopy exit $LASTEXITCODE)" }
$bundlePrefix = $bundlePath.TrimEnd('\') + '\'
$outPath = [IO.Path]::GetFullPath($OutReceipt)
if ($outPath.StartsWith($bundlePrefix, [StringComparison]::OrdinalIgnoreCase) -or $outPath.StartsWith($unsignedPath.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) {
  throw "Signing receipt must be written outside the unsigned and signed bundles"
}
if (Test-Path -LiteralPath $outPath) { throw "Signing receipt output must be a fresh path" }
$thumb = ($Thumbprint -replace '[^0-9A-Fa-f]', '').ToUpperInvariant()
if ($thumb.Length -ne 40) { throw "Certificate thumbprint must be exactly 40 hexadecimal characters" }
$certs = @(
  Get-ChildItem Cert:\CurrentUser\My -ErrorAction SilentlyContinue |
    Where-Object { $_.Thumbprint -eq $thumb }
)
if ($certs.Count -ne 1) { throw "Expected exactly one certificate with the explicit thumbprint" }
$cert = $certs[0]
if (-not $cert.HasPrivateKey) { throw "Selected signing certificate has no accessible private key" }
if ($cert.PublicKey.Oid.Value -ne '1.2.840.113549.1.1.1') { throw "Smart App Control requires an RSA signing certificate" }
$codeSigning = @($cert.EnhancedKeyUsageList | Where-Object { $_.ObjectId.Value -eq '1.3.6.1.5.5.7.3.3' })
if ($codeSigning.Count -ne 1) { throw "Selected certificate is not valid for code signing" }

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

$manifestPath = [IO.Path]::GetFullPath($Manifest)
if ($manifestPath -eq $outPath) { throw "Signing receipt cannot overwrite the pre-sign manifest" }
if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
  throw "A pre-sign portable member manifest is required"
}
$preSignManifestHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $manifestPath).Hash.ToLowerInvariant()
try { $manifestObject = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json } catch {
  throw "Pre-sign portable member manifest is unreadable"
}
if ($manifestObject.schema -ne 'atlas.portable-member-manifest/1') {
  throw "Pre-sign portable member manifest schema is unsupported"
}
$seen = @{}
$files = @(
  foreach ($row in @($manifestObject.members)) {
    if ($row.executable -ne $true) { continue }
    $relative = [string]$row.path
    $claimedHash = [string]$row.sha256
    if (-not $relative -or $relative.Contains('\') -or $relative.Contains(':') -or $claimedHash -notmatch '^[0-9a-f]{64}$') {
      throw "Pre-sign manifest contains an unsafe PE row"
    }
    $key = $relative.ToLowerInvariant()
    if ($seen.ContainsKey($key)) { throw "Pre-sign manifest PE paths collide under Windows casing" }
    $seen[$key] = $true
    $full = [IO.Path]::GetFullPath((Join-Path $bundlePath ($relative.Replace('/', '\'))))
    if (-not $full.StartsWith($bundlePrefix, [StringComparison]::OrdinalIgnoreCase)) {
      throw "Pre-sign manifest PE path escapes the bundle"
    }
    $cursor = $bundlePath
    foreach ($part in $relative.Split('/')) {
      $cursor = Join-Path $cursor $part
      $entry = Get-Item -LiteralPath $cursor -Force
      if (($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Pre-sign manifest path crosses a reparse point: $relative"
      }
    }
    if (-not (Test-Path -LiteralPath $full -PathType Leaf)) {
      throw "Pre-sign manifest PE member is missing: $relative"
    }
    $observedHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $full).Hash.ToLowerInvariant()
    if ($observedHash -ne $claimedHash) { throw "Pre-sign manifest PE hash differs: $relative" }
    [pscustomobject]@{ FullName = $full; Relative = $relative }
  }
)
if (-not $files) { throw "Bundle contains no PE members" }

$signedBySelected = @{}
foreach ($file in $files) {
  $prior = Get-AuthenticodeSignature -LiteralPath $file.FullName
  if ($prior.Status -eq 'Valid') { continue }
  if ($prior.Status -ne 'NotSigned') { throw "Refusing to overwrite invalid signature state on $($file.Relative): $($prior.Status)" }
  & $signtool sign /sha1 $thumb /fd SHA256 /tr $TimestampUrl /td SHA256 /v $file.FullName
  if ($LASTEXITCODE -ne 0) { throw "SignTool failed for $($file.Relative)" }
  $signedBySelected[$file.FullName] = $true
}
if ($signedBySelected.Count -eq 0) {
  throw "The selected certificate signed no member; refusing to claim a signing-certificate posture"
}
$atlasEntry = [IO.Path]::GetFullPath((Join-Path $bundlePath 'Atlas.exe'))
if (-not $signedBySelected.ContainsKey($atlasEntry)) {
  throw "Atlas.exe was not newly signed by the explicitly selected certificate"
}

$members = @()
foreach ($file in $files) {
  & $signtool verify /pa /all /tw /o $VerifyOs /v $file.FullName | Out-Null
  if ($LASTEXITCODE -ne 0) { throw "SignTool verification failed for $($file.Relative)" }
  $signature = Get-AuthenticodeSignature -LiteralPath $file.FullName
  if ($signature.Status -ne 'Valid' -or -not $signature.TimeStamperCertificate) {
    throw "Authenticode or timestamp verification failed for $($file.Relative)"
  }
  $actualThumb = $signature.SignerCertificate.Thumbprint.ToUpperInvariant()
  if ($signedBySelected.ContainsKey($file.FullName) -and $actualThumb -ne $thumb) {
    throw "SignTool did not apply the explicitly selected certificate to $($file.Relative)"
  }
  $members += [ordered]@{
    path = $file.Relative
    sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $file.FullName).Hash.ToLowerInvariant()
    signature = 'valid'
    publisher_subject = $signature.SignerCertificate.Subject
    publisher_thumbprint = $signature.SignerCertificate.Thumbprint.ToLowerInvariant()
    timestamp_subject = $signature.TimeStamperCertificate.Subject
    signature_origin = if ($signedBySelected.ContainsKey($file.FullName)) { 'selected_current_user_certificate' } else { 'preexisting_valid_signature' }
  }
}

$receipt = [ordered]@{
  schema = 'atlas.portable-signing/1'
  status = if ($ProductionCertificate) { 'AUTHENTICODE_TIMESTAMPED_VERIFIED_NOT_PROMOTED' } else { 'TEST_SIGNATURE_NOT_TRUSTED' }
  production_certificate_present = [bool]$ProductionCertificate
  timestamp_verified = $true
  timestamp = [ordered]@{
    scope = 'selected_current_user_certificate_members_only'
    protocol = 'RFC3161'
    digest_algorithm = 'SHA256'
    url = $timestampUri.AbsoluteUri
  }
  promotion_eligible = $false
  verification_os = $VerifyOs
  selected_certificate = [ordered]@{
    store = 'CurrentUser\My'
    subject = $cert.Subject
    thumbprint = $thumb.ToLowerInvariant()
    public_key_oid = $cert.PublicKey.Oid.Value
    code_signing_eku = $true
  }
  signtool = [ordered]@{
    name = [IO.Path]::GetFileName($signtool)
    sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $signtool).Hash.ToLowerInvariant()
    file_version = (Get-Item -LiteralPath $signtool).VersionInfo.FileVersion
  }
  pre_sign_subject = [ordered]@{
    source = $manifestObject.source
    manifest_sha256 = $preSignManifestHash
    member_set_digest = $manifestObject.summary.member_set_digest
    executable_member_count = $files.Count
  }
  members = $members
  boundary = if ($ProductionCertificate) {
    'Signature verification is local evidence; certificate authority, key custody, revocation, reputation and endpoint policy remain separate.'
  } else {
    'Test signature exercises machinery only and cannot authorize release.'
  }
}
$json = $receipt | ConvertTo-Json -Depth 8
[IO.File]::WriteAllText($outPath, $json + "`n", [Text.UTF8Encoding]::new($false))
Write-Host "[ok] signed and timestamp-verified $($files.Count) PE member(s); receipt $OutReceipt"
