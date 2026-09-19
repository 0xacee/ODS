$ErrorActionPreference = "Stop"

# Regression test: Windows LAN installs must emit HOST_LAN_IP so the OpenClaw
# container can whitelist the host's LAN origin in the Control UI
# (config/openclaw/inject-token.js). Linux/macOS installers already populate
# it; the Windows generator dropped it entirely.

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

$tierConfig = @{ TierName = "Tier 1"; LlmModel = "test-model"; GgufFile = "test.gguf"; MaxContext = 8192 }
$root = Join-Path ([IO.Path]::GetTempPath()) ("ods-hostlan-" + [guid]::NewGuid().ToString("N"))

try {
    # Case 1: -Lan install emits HOST_LAN_IP key (detection may yield "" on
    # hosts without a LAN route — the key must exist either way).
    $lanDir = Join-Path $root "lan"
    New-Item -ItemType Directory -Force -Path $lanDir | Out-Null
    New-ODSEnv -InstallDir $lanDir -TierConfig $tierConfig -Tier "1" -GpuBackend "nvidia" -EnableLan $true | Out-Null
    $lanEnv = Join-Path $lanDir ".env"
    Assert-True "LAN .env exists" (Test-Path $lanEnv)
    $lanValue = Get-EnvValue $lanEnv "HOST_LAN_IP"
    Assert-True "LAN .env emits HOST_LAN_IP" ($null -ne $lanValue)
    Assert-True "LAN HOST_LAN_IP empty or IPv4" ($lanValue -eq "" -or $lanValue -match '^\d{1,3}(\.\d{1,3}){3}$')
    Assert-True "LAN BIND_ADDRESS=0.0.0.0" ((Get-EnvValue $lanEnv "BIND_ADDRESS") -eq "0.0.0.0")

    # Case 2: loopback install emits HOST_LAN_IP with an empty value so the
    # compose ${HOST_LAN_IP:-} fallback is a no-op.
    $localDir = Join-Path $root "local"
    New-Item -ItemType Directory -Force -Path $localDir | Out-Null
    New-ODSEnv -InstallDir $localDir -TierConfig $tierConfig -Tier "1" -GpuBackend "nvidia" | Out-Null
    $localEnv = Join-Path $localDir ".env"
    $localValue = Get-EnvValue $localEnv "HOST_LAN_IP"
    Assert-True "loopback .env emits HOST_LAN_IP" ($null -ne $localValue)
    Assert-True "loopback HOST_LAN_IP empty" ($localValue -eq "")

    # Case 3: operator-set HOST_LAN_IP in an existing .env is preserved across
    # reruns (matches Linux _env_get semantics).
    $rerunDir = Join-Path $root "rerun"
    New-Item -ItemType Directory -Force -Path $rerunDir | Out-Null
    Set-Content -LiteralPath (Join-Path $rerunDir ".env") -Value "HOST_LAN_IP=203.0.113.7`nBIND_ADDRESS=0.0.0.0"
    New-ODSEnv -InstallDir $rerunDir -TierConfig $tierConfig -Tier "1" -GpuBackend "nvidia" -EnableLan $true | Out-Null
    Assert-True "operator HOST_LAN_IP preserved" ((Get-EnvValue (Join-Path $rerunDir ".env") "HOST_LAN_IP") -eq "203.0.113.7")
} finally {
    Remove-Item -Recurse -Force $root -ErrorAction SilentlyContinue
}

if ($failures -gt 0) { exit 1 }
Write-Host "All HOST_LAN_IP tests passed."
