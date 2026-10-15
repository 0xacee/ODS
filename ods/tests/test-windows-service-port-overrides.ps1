param([string]$SourceRoot = (Split-Path -Parent $PSScriptRoot))
$ErrorActionPreference = 'Stop'
. (Join-Path $SourceRoot 'installers/windows/lib/llm-endpoint.ps1')
. (Join-Path $SourceRoot 'installers/windows/lib/detection.ps1')
. (Join-Path $SourceRoot 'installers/windows/lib/env-generator.ps1')
function Get-ODSDockerMemoryGB { return 0 }
function Get-LlamaCpuBudget { return @{ Limit = '4.0'; Reservation = '1.0'; Available = '4.0' } }
function docker { throw 'Docker must not run in this fixture' }
function Test-WindowsLemonadeWhisperPortConflict { return $false }
function Stop-Process { throw 'No process may be stopped by port preflight' }
function Write-AIWarn { param($Message) }
function Write-AIError { param($Message) }
function Write-AI { param($Message) }

$script:checks = 0
$script:failures = @()
function Assert-Equal($Actual, $Expected, [string]$Label) {
    $script:checks++
    if ("$Actual" -cne "$Expected") { $script:failures += "$Label expected '$Expected', got '$Actual'" }
}
function Read-Ast([string]$Path) {
    $tokens = $null; $parseErrors = $null
    $tree = [System.Management.Automation.Language.Parser]::ParseFile($Path, [ref]$tokens, [ref]$parseErrors)
    if ($parseErrors.Count) { throw $parseErrors[0].Message }
    return $tree
}
$phasePath = Join-Path $SourceRoot 'installers/windows/phases/04-requirements.ps1'
$phaseAst = Read-Ast $phasePath
foreach ($name in @('Get-WindowsODSSelectedPortConflicts', 'Assert-WindowsODSSelectedPortAvailability')) {
    $node = $phaseAst.Find({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name }, $true)
    . ([scriptblock]::Create($node.Extent.Text))
}
# Execute the real selected-port assembly, without hardware requirements or services.
$phaseText = Get-Content -LiteralPath $phasePath -Raw
$start = $phaseText.IndexOf('$_portsToCheck = [ordered]@{')
$end = $phaseText.IndexOf('$_portConflicts = @(', $start)
if ($start -lt 0 -or $end -lt $start) { throw 'Selected-port assembly was not found' }
$portBlock = [scriptblock]::Create($phaseText.Substring($start, $end - $start))
function Resolve-WindowsLlmPreflightPort { return 0 } # Native/LLM alias routing is a separate contract.
function Get-SelectedPorts([string]$InstallDir, [bool]$Features = $true) {
    $enableRecommended = $enableVoice = $enableWorkflows = $enableRag = $Features
    $enableHermes = $enableComfyui = $enableDeepResearch = $enablePrivacyShield = $Features
    $gpuInfo = @{ Backend = 'none' }; $cloudMode = $true
    $script:NATIVE_LLM_PORT = 8080
    . $portBlock
    return ,$_portsToCheck
}
$defaults = [ordered]@{
    DASHBOARD_PORT = 3001; DASHBOARD_REMOTE_PORT = 3011; DASHBOARD_API_PORT = 3002
    WEBUI_PORT = 3000; WHISPER_PORT = 9000; TTS_PORT = 8880; N8N_PORT = 5678
    QDRANT_PORT = 6333; QDRANT_GRPC_PORT = 6334; EMBEDDINGS_PORT = 8090
    LITELLM_PORT = 4000; SEARXNG_PORT = 8888; TOKEN_SPY_PORT = 3005
    HERMES_PROXY_PORT = 9120; APE_PORT = 7890; COMFYUI_PORT = 8188
    PERPLEXICA_PORT = 3004; SHIELD_PORT = 8085; OPENCODE_PORT = 3003
}
$labels = @{
    DASHBOARD_PORT = 'Dashboard'; DASHBOARD_REMOTE_PORT = 'Dashboard (remote)'; DASHBOARD_API_PORT = 'Dashboard API'
    WEBUI_PORT = 'Open WebUI (chat)'; WHISPER_PORT = 'Whisper (STT)'; TTS_PORT = 'Kokoro (TTS)'; N8N_PORT = 'n8n (workflows)'
    QDRANT_PORT = 'Qdrant (vector DB)'; QDRANT_GRPC_PORT = 'Qdrant (gRPC)'; EMBEDDINGS_PORT = 'TEI (embeddings)'
    LITELLM_PORT = 'LiteLLM (API gateway)'; SEARXNG_PORT = 'SearXNG (search)'; TOKEN_SPY_PORT = 'Token Spy (usage monitor)'
    HERMES_PROXY_PORT = 'Hermes auth proxy'; APE_PORT = 'APE (agent policy engine)'; COMFYUI_PORT = 'ComfyUI (image generation)'
    PERPLEXICA_PORT = 'Perplexica (deep research)'; SHIELD_PORT = 'Privacy Shield'
}
$saved = @{}
$fixture = Join-Path ([IO.Path]::GetTempPath()) ('ods-service-ports-' + [Guid]::NewGuid().ToString('N'))
$fixture = [IO.Path]::GetFullPath($fixture)
New-Item -ItemType Directory -Path $fixture | Out-Null
$tier = @{ TierName = 'Port fixture'; LlmModel = 'test'; GgufFile = 'test.gguf'; MaxContext = 4096 }
function Generate-Env {
    New-ODSEnv -InstallDir $fixture -TierConfig $tier -Tier '3' -GpuBackend 'nvidia' | Out-Null
    return Get-WindowsODSEnvMap -InstallDir $fixture
}
try {
    foreach ($key in $defaults.Keys) {
        $saved[$key] = [Environment]::GetEnvironmentVariable($key)
        [Environment]::SetEnvironmentVariable($key, $null)
    }
    foreach ($case in @('defaults', 'persisted', 'process', 'retained-rerun', 'invalid-process', 'invalid-both')) {
        $expected = @{}
        foreach ($key in $defaults.Keys) {
            $value = [int]$defaults[$key]
            if ($case -in @('persisted', 'invalid-process')) { $value += 10000 }
            if ($case -in @('process', 'retained-rerun')) { $value += 20000 }
            $expected[$key] = $value
            $override = $null
            if ($case -eq 'process') { $override = [string]$value }
            if ($case -eq 'invalid-process') { $override = '70000' }
            if ($case -eq 'invalid-both') { $override = 'not-a-port' }
            [Environment]::SetEnvironmentVariable($key, $override)
        }
        if ($case -in @('persisted', 'invalid-process', 'invalid-both')) {
            $lines = foreach ($key in $defaults.Keys) {
                if ($case -eq 'invalid-both') { "$key=0" } else { "$key=$($expected[$key])" }
            }
            Set-Content -LiteralPath (Join-Path $fixture '.env') -Value $lines
        }
        $selected = Get-SelectedPorts $fixture
        $generated = Generate-Env
        foreach ($key in $defaults.Keys) {
            Assert-Equal $generated[$key] $expected[$key] "$case generated $key"
            if ($labels.ContainsKey($key)) { Assert-Equal $selected[$labels[$key]] $expected[$key] "$case preflight $key" }
        }
    }
    foreach ($key in $defaults.Keys) {
        foreach ($value in @('1', '65535', '0', '-1', '65536', '1.5', '')) {
            [Environment]::SetEnvironmentVariable($key, $value)
            $expectedPort = if ($value -in @('1', '65535')) { [int]$value } else { 12345 }
            Assert-Equal (Resolve-WindowsODSPort -Name $key -DefaultPort $defaults[$key] -ExistingEnv @{ $key = '12345' }) $expectedPort "validated $key $value"
        }
        [Environment]::SetEnvironmentVariable($key, $null)
    }
    $selected = Get-SelectedPorts $fixture $false
    Assert-Equal $selected.Count 4 'Disabled optional features do not add port checks'
    Assert-Equal $selected['Dashboard (remote)'] 3011 'Remote Dashboard is still required without optional features'
    $script:occupied = 3011
    function Test-WindowsPortInUse {
        param([int]$Port)
        return @{ InUse = ($Port -eq $script:occupied); ProcessId = 4242; ProcessName = 'fixture-owner' }
    }
    $conflicts = @(Get-WindowsODSSelectedPortConflicts -PortsToCheck $selected)
    Assert-Equal $conflicts.Count 1 'Occupied required remote Dashboard listener is detected'
    $aborted = $false
    try { $null = Assert-WindowsODSSelectedPortAvailability -Conflicts $conflicts -NonInteractive }
    catch { $aborted = $_.Exception.Message -eq 'ODS_INSTALL_ABORTED' }
    Assert-Equal $aborted $true 'Remote Dashboard collision aborts non-interactive install'
    $env:N8N_PORT = '15679'; $script:occupied = 5678
    $selected = Get-SelectedPorts $fixture
    Assert-Equal @(Get-WindowsODSSelectedPortConflicts -PortsToCheck $selected).Count 0 'n8n override leaves unrelated default-port listener alone'
    $script:occupied = 15679
    Assert-Equal @(Get-WindowsODSSelectedPortConflicts -PortsToCheck $selected).Count 1 'n8n selected-port listener is a real conflict'

    # Execute real shortcut URL construction; never write Desktop/Start Menu files.
    $installerAst = Read-Ast (Join-Path $SourceRoot 'installers/windows/install-windows.ps1')
    $assignment = $installerAst.Find({ param($n) $n -is [System.Management.Automation.Language.AssignmentStatementAst] -and $n.Left.Extent.Text -eq '$dashboardUrl' }, $true)
    $dashboardPort = 13101
    . ([scriptblock]::Create($assignment.Extent.Text))
    Assert-Equal $dashboardUrl 'http://localhost:13101' 'Shortcuts use selected Dashboard port'
    $urlAssignment = $installerAst.Find({ param($n) $n -is [System.Management.Automation.Language.AssignmentStatementAst] -and $n.Left.Extent.Text -eq '$urlContent' }, $true)
    $iconContent = 'IconIndex=0'
    . ([scriptblock]::Create($urlAssignment.Extent.Text))
    Assert-Equal ($urlContent.Contains('URL=http://localhost:13101')) $true 'InternetShortcut content uses selected port'

    $windowsEnvMap = @{ PERPLEXICA_PORT = '13004' }; $perplexicaPort = 0
    $readinessEnv = $windowsEnvMap
    $readinessFunction = $installerAst.Find({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Get-ReadinessPort' }, $true)
    . ([scriptblock]::Create($readinessFunction.Extent.Text))
    $assignment = $installerAst.Find({ param($n) $n -is [System.Management.Automation.Language.AssignmentStatementAst] -and $n.Left.Extent.Text -eq '$perplexicaPort' }, $true)
    if ($assignment) { . ([scriptblock]::Create($assignment.Extent.Text)) }
    function Set-PerplexicaConfig { param($PerplexicaPort, $LlmModel, $LlmBaseUrl, $ApiKey) $script:configuredPort = $PerplexicaPort; return $true }
    $call = $installerAst.Find({ param($n) $n -is [System.Management.Automation.Language.AssignmentStatementAst] -and $n.Left.Extent.Text -eq '$perplexicaOk' }, $true)
    . ([scriptblock]::Create($call.Extent.Text))
    Assert-Equal $script:configuredPort 13004 'Perplexica configuration uses selected published port'
} finally {
    foreach ($key in $saved.Keys) { [Environment]::SetEnvironmentVariable($key, $saved[$key]) }
    $expectedParent = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\', '/')
    if ([IO.Path]::GetDirectoryName($fixture).TrimEnd('\', '/') -ne $expectedParent -or
        [IO.Path]::GetFileName($fixture) -notmatch '^ods-service-ports-[a-f0-9]{32}$' -or
        ((Get-Item -LiteralPath $fixture -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Unsafe fixture cleanup path' }
    Remove-Item -LiteralPath $fixture -Recurse -Force
}
foreach ($failure in $script:failures) { Write-Host "FAIL $failure" }
Write-Host "$($script:checks - $script:failures.Count)/$($script:checks) service-port checks passed"
if ($script:failures.Count) { exit 1 }
