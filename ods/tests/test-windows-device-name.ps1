$ErrorActionPreference = "Stop"

# Regression test: the Windows installer must emit ODS_DEVICE_NAME derived from
# COMPUTERNAME (sanitized to the .env.schema.json pattern) so ods-mdns/ods-proxy
# hostnames and dashboard-api magic-link URLs use the machine's LAN identity
# instead of every Windows install colliding on the compose default "ods".

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
. (Join-Path $repoRoot "installers/windows/lib/env-generator.ps1")

# New-ODSEnv calls Write-AIWarn for non-fatal ACL issues and Get-LlamaCpuBudget
# for the CPU cap; stub the cross-lib helpers (detection.ps1/ui.ps1 are out of
# scope for this contract test).
if (-not (Get-Command Write-AIWarn -ErrorAction SilentlyContinue)) {
    function Write-AIWarn { param([string]$Message) Write-Host "WARN: $Message" }
}
if (-not (Get-Command Get-LlamaCpuBudget -ErrorAction SilentlyContinue)) {
    function Get-LlamaCpuBudget { param([string]$GpuBackend) return @{ Available = 4; Limit = 4; Reservation = 1 } }
}

$failures = 0
function Assert-Equal([string]$Label, [string]$Expected, [string]$Actual) {
    if ($Expected -eq $Actual) { Write-Host "PASS: $Label" }
    else { $script:failures++; Write-Host "FAIL: $Label expected=[$Expected] actual=[$Actual]" }
}
function Assert-True([string]$Label, [bool]$Condition) {
    if ($Condition) { Write-Host "PASS: $Label" }
    else { $script:failures++; Write-Host "FAIL: $Label" }
}
function Get-EnvValue([string]$EnvPath, [string]$Key) {
    foreach ($line in (Get-Content $EnvPath)) {
        if ($line -match "^$([regex]::Escape($Key))=(.*)$") { return $Matches[1] }
    }
    return $null
}

# --- Get-WindowsDeviceName sanitizer (schema: ^[a-z0-9][a-z0-9-]{0,30}[a-z0-9]$) ---
$savedName = $env:COMPUTERNAME
try {
    $env:COMPUTERNAME = "DESKTOP-ABC123"
    Assert-Equal "uppercase lowers" "desktop-abc123" (Get-WindowsDeviceName)

    $env:COMPUTERNAME = "My_PC.Build 01"
    Assert-Equal "invalid chars collapse" "my-pc-build-01" (Get-WindowsDeviceName)

    # Inner hyphen runs are preserved (matching the Linux sed pipeline); only
    # leading/trailing hyphens are trimmed.
    $env:COMPUTERNAME = "--EDGE--CASE--"
    Assert-Equal "edge dashes trimmed" "edge--case" (Get-WindowsDeviceName)

    $env:COMPUTERNAME = "A-Very-Long-Computer-Name-That-Exceeds-32"
    $long = Get-WindowsDeviceName
    Assert-True "capped at 32 chars" ($long.Length -le 32)
    Assert-True "capped value matches schema" ($long -match '^[a-z0-9]([a-z0-9-]{0,30}[a-z0-9])?$')

    $env:COMPUTERNAME = "___"
    Assert-Equal "unsalvageable falls back" "ods" (Get-WindowsDeviceName)

    $env:COMPUTERNAME = ""
    Assert-Equal "empty falls back" "ods" (Get-WindowsDeviceName)
} finally {
    $env:COMPUTERNAME = $savedName
}

# --- New-ODSEnv emits ODS_DEVICE_NAME and preserves operator overrides ---
$tierConfig = @{ TierName = "Tier 1"; LlmModel = "test-model"; GgufFile = "test.gguf"; MaxContext = 8192 }
$root = Join-Path ([IO.Path]::GetTempPath()) ("ods-devname-" + [guid]::NewGuid().ToString("N"))
try {
    $freshDir = Join-Path $root "fresh"
    New-Item -ItemType Directory -Force -Path $freshDir | Out-Null
    New-ODSEnv -InstallDir $freshDir -TierConfig $tierConfig -Tier "1" -GpuBackend "nvidia" | Out-Null
    $freshValue = Get-EnvValue (Join-Path $freshDir ".env") "ODS_DEVICE_NAME"
    Assert-True "fresh .env emits ODS_DEVICE_NAME" ($null -ne $freshValue)
    Assert-True "fresh ODS_DEVICE_NAME matches schema" ($freshValue -match '^[a-z0-9]([a-z0-9-]{0,30}[a-z0-9])?$')

    $rerunDir = Join-Path $root "rerun"
    New-Item -ItemType Directory -Force -Path $rerunDir | Out-Null
    Set-Content -LiteralPath (Join-Path $rerunDir ".env") -Value "ODS_DEVICE_NAME=studio-rig"
    New-ODSEnv -InstallDir $rerunDir -TierConfig $tierConfig -Tier "1" -GpuBackend "nvidia" | Out-Null
    Assert-Equal "operator ODS_DEVICE_NAME preserved" "studio-rig" (Get-EnvValue (Join-Path $rerunDir ".env") "ODS_DEVICE_NAME")
} finally {
    Remove-Item -Recurse -Force $root -ErrorAction SilentlyContinue
}

if ($failures -gt 0) { exit 1 }
Write-Host "All ODS_DEVICE_NAME tests passed."
