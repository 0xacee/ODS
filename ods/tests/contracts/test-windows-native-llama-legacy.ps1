[Diagnostics.CodeAnalysis.SuppressMessageAttribute('PSReviewUnusedParameter', '', Justification = 'Fixture mocks keep the production command signatures.')]
[Diagnostics.CodeAnalysis.SuppressMessageAttribute('PSAvoidOverwritingBuiltInCmdlets', '', Justification = 'Task Scheduler, process and socket cmdlets are replaced by fixtures.')]
[CmdletBinding()]
param()
# Native llama-server for the non-Portal Windows installer (Round F): stage
# and qualify, the verified copy at <InstallDir>\llama-server, private launch
# options and key file, .env tuning and launch arguments (pinned runtime and
# model-store profiles), proof-gated start, the at-logon task, ownership-proven
# stops and the installer cutover from ODS's own Lemonade runtime. Task
# Scheduler, processes, sockets and HTTP are fixtures; nothing executes and
# only temporary files are written.
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
. (Join-Path $root 'installers/windows/lib/native-llama-runtime.ps1')
. (Join-Path $root 'installers/windows/lib/native-llama-args.ps1')
. (Join-Path $root 'installers/windows/lib/native-lemonade-retire.ps1')
. (Join-Path $root 'installers/windows/lib/native-llama-legacy.ps1')
$script:checks = 0
function Check([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
    $script:checks++
    Write-Host "PASS $Message"
}
function Get-Failure([scriptblock]$Action) {
    try { & $Action; return '' } catch { return $_.Exception.Message }
}
$script:output = @()
function Write-AI { param([string]$Message) $script:output += $Message }
function Write-AIWarn { param([string]$Message) $script:output += ('WARN ' + $Message) }
function Write-AISuccess { param([string]$Message) $script:output += ('OK ' + $Message) }
function Stop-Process { throw 'stops go through held handles only' }
function msiexec { throw 'msiexec must never run' }
# --help probes run the binary; the fixture binaries are inert text files.
$script:probed = @()
function Get-ODSNativeReasoningArgs { param($Executable, $Mode, $FallbackFormat) $script:probed += $Executable; return @('--reasoning', $Mode) }
function Get-ODSNativeCheckpointIntervalArgs {
    param($Executable, $Value)
    if (-not $Value) { return [pscustomobject]@{ Arguments = @(); Warning = '' } }
    return [pscustomobject]@{ Arguments = @('--checkpoint-every-n-tokens', $Value); Warning = '' }
}

$fixture = Join-Path ([IO.Path]::GetTempPath()) ('ods-native-legacy-' + [guid]::NewGuid().ToString('N'))
$null = New-Item -ItemType Directory -Path $fixture
$previousLocalAppData = $env:LOCALAPPDATA
$env:LOCALAPPDATA = Join-Path $fixture 'LocalAppData'
$install = Join-Path $fixture 'install dir'
$null = New-Item -ItemType Directory -Path (Join-Path $install 'data\models') -Force
$key = 'ab' * 32
try {
    # --- The verified copy at <InstallDir>\llama-server ---
    $pin = [pscustomobject]@{ ReleaseTag = 'b9014'; Build = 9014; Sha256 = ('c' * 64); Size = 33541404 }
    $versioned = Get-ODSNativeLlamaInstallDirectory $pin
    $null = New-Item -ItemType Directory -Path $versioned -Force
    foreach ($name in @('llama-server.exe', 'ggml-vulkan.dll', 'ggml-base.dll')) {
        [IO.File]::WriteAllText((Join-Path $versioned $name), "fixture $name; never executed")
    }
    function Write-PinRecord([string]$Directory, [string]$Tag, [string]$ZipSha) {
        $record = [ordered]@{ schemaVersion = 1; releaseTag = $Tag; asset = "llama-$Tag-bin-win-vulkan-x64.zip"; zipSha256 = $ZipSha
            zipSize = 1; source = 'fixture'; files = @(Get-ODSNativeLlamaFileManifest $Directory) }
        [IO.File]::WriteAllText((Join-Path $Directory 'pin.json'), ($record | ConvertTo-Json -Depth 4), [Text.UTF8Encoding]::new($false))
    }
    Write-PinRecord $versioned 'b9014' $pin.Sha256
    $runtime = Test-ODSNativeLlamaInstall -Directory $versioned -ExpectedZipSha256 $pin.Sha256 -ExpectedReleaseTag 'b9014'
    $published = Join-Path $install 'llama-server'
    $copy = Publish-ODSNativeLlamaRuntimeCopy -Runtime $runtime -Destination $published
    Check ($copy.Changed -and $copy.ExecutablePath -eq (Join-Path $published 'llama-server.exe') -and
        (Test-ODSNativeLlamaInstall -Directory $published -ExpectedZipSha256 $pin.Sha256 -ExpectedReleaseTag 'b9014').FileCount -eq 3) 'the qualified runtime is published to <InstallDir>\llama-server with its pin.json'
    Check (-not (Publish-ODSNativeLlamaRuntimeCopy -Runtime $runtime -Destination $published).Changed) 'a published copy that still verifies is kept as is'
    [IO.File]::AppendAllText((Join-Path $published 'ggml-vulkan.dll'), 'tampered')
    [IO.File]::WriteAllText((Join-Path $published 'evil.dll'), 'unpinned')
    $copy = Publish-ODSNativeLlamaRuntimeCopy -Runtime $runtime -Destination $published
    Check ($copy.Changed -and -not (Test-Path -LiteralPath (Join-Path $published 'evil.dll')) -and
        $null -ne (Test-ODSNativeLlamaInstall -Directory $published -ExpectedZipSha256 $pin.Sha256 -ExpectedReleaseTag 'b9014')) 'a damaged copy or one with an unpinned DLL is replaced as a whole'
    Write-PinRecord $published 'b8248' ('d' * 64)
    Check ((Publish-ODSNativeLlamaRuntimeCopy -Runtime $runtime -Destination $published).Changed) 'an older release at the published path is replaced (repin on upgrade)'
    Check (@(Get-ChildItem -LiteralPath $install -Force -Filter '.llama-server.*').Count -eq 0) 'no staging or previous copy is left beside the published runtime'
    Check ((Get-ODSNativeRuntimeDir).StartsWith((Join-Path $env:LOCALAPPDATA 'ODS'), [StringComparison]::OrdinalIgnoreCase) -and
        -not (Get-ODSNativeRuntimeDir).StartsWith($install, [StringComparison]::OrdinalIgnoreCase)) 'private runtime files live under %LOCALAPPDATA%\ODS, outside the install folder containers mount'

    # --- Launch options and the API key file ---
    $options = Write-ODSNativeLlamaLegacyOptions -Runtime $runtime -Device ([pscustomobject]@{ Name = 'Vulkan1' })
    $read = Read-ODSNativeLlamaLegacyOptions
    Check ($read.Device -eq 'Vulkan1' -and $read.ReleaseTag -eq 'b9014' -and $read.ZipSha256 -eq $pin.Sha256 -and
        $read.ApiKeyPath -eq (Join-Path (Get-ODSNativeRuntimeDir) 'api-key') -and $read.LogPath -eq (Join-Path (Get-ODSNativeRuntimeDir) 'llama-server.log')) 'launch options record the qualified device and the pinned runtime identity'
    Check ((Write-ODSNativeLlamaLegacyOptions -Runtime $runtime -Device $null).Device -eq 'none') 'no Vulkan device records the explicit CPU route'
    [IO.File]::WriteAllText((Join-Path (Get-ODSNativeRuntimeDir) 'runtime-options.json'), '{"schemaVersion":1,"Device":"Vulkan0,CPU"}')
    Check ((Get-Failure { $null = Read-ODSNativeLlamaLegacyOptions }) -match 'invalid') 'tampered launch options are refused'
    $options = Write-ODSNativeLlamaLegacyOptions -Runtime $runtime -Device ([pscustomobject]@{ Name = 'Vulkan1' })
    $envMap = @{ LLAMA_SERVER_API_KEY = $key }
    Check ((Sync-ODSNativeLlamaLegacyApiKey -EnvMap $envMap -Path $options.ApiKeyPath) -eq $key) 'the key comes from LLAMA_SERVER_API_KEY in .env'
    $bytes = [IO.File]::ReadAllBytes($options.ApiKeyPath)
    Check ($bytes.Length -eq 64 -and [Text.Encoding]::ASCII.GetString($bytes) -ceq $key) 'the key file holds exactly the 64 hex characters: no BOM, no newline'
    $stamp = (Get-Item -LiteralPath $options.ApiKeyPath).LastWriteTimeUtc
    Start-Sleep -Milliseconds 50
    $null = Sync-ODSNativeLlamaLegacyApiKey -EnvMap $envMap -Path $options.ApiKeyPath
    Check ((Get-Item -LiteralPath $options.ApiKeyPath).LastWriteTimeUtc -eq $stamp) 'an up-to-date key file is not rewritten'
    $rotated = 'cd' * 32
    $null = Sync-ODSNativeLlamaLegacyApiKey -EnvMap @{ LLAMA_SERVER_API_KEY = $rotated } -Path $options.ApiKeyPath
    Check ([IO.File]::ReadAllText($options.ApiKeyPath) -ceq $rotated) 'a rotated .env key reaches the key file before the next launch'
    foreach ($bad in @('', 'not-a-key', ('AB' * 32))) {
        Check ((Get-Failure { $null = Sync-ODSNativeLlamaLegacyApiKey -EnvMap @{ LLAMA_SERVER_API_KEY = $bad } -Path $options.ApiKeyPath }) -match 'LLAMA_SERVER_API_KEY') "a missing or malformed .env key ('$bad') stops the launch"
    }
    $null = Sync-ODSNativeLlamaLegacyApiKey -EnvMap $envMap -Path $options.ApiKeyPath

    # --- Launch arguments from .env (pinned runtime) ---
    $pinnedExe = Join-Path $published 'llama-server.exe'
    $modelPath = Join-Path (Join-Path $install 'data\models') 'Qwen3.6-35B-A3B-Q4_K_M.gguf'
    $selection = [pscustomobject]@{ modelPath = $modelPath; profile = $null }
    $envMap = @{ GGUF_FILE = 'Qwen3.6-35B-A3B-Q4_K_M.gguf'; CTX_SIZE = '131072'; MAX_CONTEXT = '131072'; LLAMA_REASONING = 'off'
        LLAMA_ARG_FLASH_ATTN = 'on'; LLAMA_ARG_CACHE_TYPE_K = 'q8_0'; LLAMA_ARG_SPEC_TYPE = 'draft-mtp'; LLAMA_ARG_SPEC_DRAFT_TYPE_K = 'q4_0'
        LLAMA_ARG_NO_CACHE_PROMPT = 'true'; LLAMA_PARALLEL = '4'; LLAMA_SERVER_API_KEY = $key }
    $launch = New-ODSNativeLlamaLegacyLaunch -EnvMap $envMap -Selection $selection -Port 8080 -Options $options -PinnedExecutable $pinnedExe
    $expected = @('--model', $modelPath, '--alias', 'Qwen3.6-35B-A3B-Q4_K_M.gguf', '--host', '127.0.0.1', '--port', '8080',
        '--ctx-size', '131072', '--parallel', '1', '--n-gpu-layers', 'auto', '--device', 'Vulkan1', '--metrics', '--no-webui',
        '--api-key-file', $options.ApiKeyPath, '--log-file', $options.LogPath, '--reasoning', 'off',
        '--flash-attn', 'on', '--cache-type-k', 'q8_0', '--spec-type', 'draft-mtp', '--spec-draft-type-k', 'q4_0', '--no-cache-prompt')
    Check ((@($launch.Arguments) -join '|') -ceq ($expected -join '|')) 'the pinned runtime gets the Round F contract plus the allow-listed .env tunables'
    Check ($launch.Pinned -and $launch.ExecutablePath -eq $pinnedExe -and $launch.GgufFile -eq 'Qwen3.6-35B-A3B-Q4_K_M.gguf' -and $launch.ContextSize -eq 131072) 'the launch proves the .env model and context'
    Check (@(@($launch.Warnings) -match 'LLAMA_PARALLEL=4 is ignored').Count -eq 1) 'LLAMA_PARALLEL cannot add slots: one slot keeps the context proof valid'
    Check (-not (ConvertTo-ODSNativeLlamaArgumentString $launch.Arguments).Contains($key)) 'the key never appears on the command line'
    $envMap.LLAMA_ARG_FLASH_ATTN = 'on --host 0.0.0.0'
    Check ((Get-Failure { $null = New-ODSNativeLlamaLegacyLaunch -EnvMap $envMap -Selection $selection -Port 8080 -Options $options -PinnedExecutable $pinnedExe }) -match 'not allowed') 'a .env tunable cannot smuggle a listener or another flag'
    $envMap.LLAMA_ARG_FLASH_ATTN = 'on'
    $cpu = [pscustomobject]@{ schemaVersion = 1; Device = 'none'; ApiKeyPath = $options.ApiKeyPath; LogPath = $options.LogPath; ReleaseTag = 'b9014'; ZipSha256 = $pin.Sha256 }
    $cpuArgs = @((New-ODSNativeLlamaLegacyLaunch -EnvMap $envMap -Selection $selection -Port 8080 -Options $cpu -PinnedExecutable $pinnedExe).Arguments) -join ' '
    Check ($cpuArgs -match '--n-gpu-layers 0 --device none') 'the CPU route is explicit: no GPU layers and --device none'
    $envMap.CTX_SIZE = 'lots'
    Check ((Get-Failure { $null = New-ODSNativeLlamaLegacyLaunch -EnvMap $envMap -Selection $selection -Port 8080 -Options $options -PinnedExecutable $pinnedExe }) -match 'CTX_SIZE') 'a malformed CTX_SIZE stops the launch'
    $envMap.CTX_SIZE = '131072'
    $unicode = [pscustomobject]@{ modelPath = (Join-Path (Join-Path $install 'data\models') ('Modell-' + [char]0x00E9 + '.gguf')); profile = $null }
    Check ((Get-Failure { $null = New-ODSNativeLlamaLegacyLaunch -EnvMap $envMap -Selection $unicode -Port 8080 -Options $options -PinnedExecutable $pinnedExe }) -match 'ASCII') 'a non-ASCII GGUF name is refused with an explanation'

    # --- A registered model-store profile keeps its own qualified runtime ---
    $profileExe = Join-Path $fixture 'SSD runtime\llama-server.exe'
    $profileSelection = [pscustomobject]@{ modelPath = (Join-Path $fixture 'SSD modelos\model.gguf'); profile = [pscustomobject]@{
            backend = 'vulkan'; executable = $profileExe; contextLength = 16384
            args = @('--parallel', '1', '--flash-attn', 'on', '--cache-type-k', 'q4_0', '--cache-type-v', 'q4_0', '--spec-type', 'draft-mtp') } }
    $script:probed = @()
    $profileLaunch = New-ODSNativeLlamaLegacyLaunch -EnvMap @{ CTX_SIZE = '8192'; LLAMA_REASONING = 'off' } -Selection $profileSelection -Port 8080 -Options $options -PinnedExecutable $pinnedExe
    $joined = ConvertTo-ODSNativeLlamaArgumentString $profileLaunch.Arguments
    Check (-not $profileLaunch.Pinned -and $profileLaunch.ExecutablePath -eq $profileExe -and $script:probed.Count -eq 0) 'a profile runs its own qualified runtime and is not probed'
    Check ($joined.Contains('"--alias" "model.gguf"') -and $joined.Contains('"--host" "127.0.0.1"') -and $joined.Contains('"--no-webui"') -and
        $joined.Contains('"--api-key-file"') -and $joined.Contains('"--device" "Vulkan1"') -and $joined.Contains('"--ctx-size" "8192"') -and
        $joined.Contains('"--reasoning-format" "none"') -and $joined.EndsWith('"--spec-type" "draft-mtp"') -and
        $joined.Contains('"' + $profileSelection.modelPath + '"')) 'a profile keeps its arguments and gains loopback, alias, key file, device and reasoning off'
    $profileSelection.profile.backend = 'rocm'
    Check (-not ((New-ODSNativeLlamaLegacyLaunch -EnvMap @{ CTX_SIZE = '8192' } -Selection $profileSelection -Port 8080 -Options $options -PinnedExecutable $pinnedExe).Arguments -contains '--device')) 'a non-Vulkan profile is not given a Vulkan device name'

    # --- Proof-gated start ---
    $script:listeners = @()
    function Get-NetTCPConnection { param($LocalPort, $State, $ErrorAction) return @($script:listeners) }
    $script:started = @()
    $script:child = $null
    function New-FakeProcess([int]$Id) {
        $process = [pscustomobject]@{ Id = $Id; Handle = [IntPtr]1; HasExited = $false; ExitCode = 0; StartTime = [datetime]'2026-10-04T12:00:00'; Killed = $false; Disposed = $false }
        $process | Add-Member -MemberType ScriptMethod -Name Kill -Value { $this.Killed = $true; $this.HasExited = $true }
        $process | Add-Member -MemberType ScriptMethod -Name WaitForExit -Value { param($Milliseconds) return $true }
        $process | Add-Member -MemberType ScriptMethod -Name Dispose -Value { $this.Disposed = $true }
        return $process
    }
    function Start-Process {
        param($FilePath, $ArgumentList, $WorkingDirectory, $WindowStyle, [switch]$PassThru)
        $script:started += [pscustomobject]@{ FilePath = $FilePath; ArgumentList = [string]$ArgumentList; WindowStyle = $WindowStyle; WorkingDirectory = $WorkingDirectory }
        $script:child = New-FakeProcess 4242
        return $script:child
    }
    $script:startupFailure = ''
    function Wait-ODSNativeLlamaStartup { param($Port, $Process, $TimeoutSeconds) if ($script:startupFailure) { throw $script:startupFailure } }
    $script:listenerChecks = @()
    function Assert-ODSNativeLlamaListener { param($Port, $ProcessId, $ExecutablePath) $script:listenerChecks += "$Port/$ProcessId/$ExecutablePath" }
    $script:proofContext = 131072
    $script:proofKey = ''
    function Get-ODSNativeLlamaModelProof {
        param($Port, $GgufFile, $ModelPaths, $ContextSize, $ApiKey)
        $script:proofKey = $ApiKey
        $verified = $script:proofContext -ge $ContextSize -and $script:proofContext - $ContextSize -lt 256
        return [pscustomobject]@{ ModelId = $GgufFile; RuntimeContext = $script:proofContext; ContextVerified = $verified
            ContextLength = $ContextSize; Message = "llama.cpp loaded $GgufFile with $($script:proofContext) tokens of context, less than the planned $ContextSize." }
    }
    $pidFile = Join-Path $install 'data\llama-server.pid'
    [IO.File]::WriteAllText($options.LogPath, 'previous run')
    $envMap.LLAMA_PARALLEL = ''
    $launch = New-ODSNativeLlamaLegacyLaunch -EnvMap $envMap -Selection $selection -Port 8080 -Options $options -PinnedExecutable $pinnedExe
    $result = Start-ODSNativeLlamaLegacyProcess -Launch $launch -Port 8080 -ApiKey $key -PidFile $pidFile
    $ready = Read-ODSNativeLlamaJson (Join-Path (Get-ODSNativeRuntimeDir) 'ready.json')
    Check ($result.ProcessId -eq 4242 -and ([IO.File]::ReadAllText($pidFile)).Trim() -eq '4242' -and $ready.ProcessId -eq 4242 -and
        $ready.ModelId -eq 'Qwen3.6-35B-A3B-Q4_K_M.gguf' -and $ready.Port -eq 8080 -and $ready.ExecutablePath -eq $pinnedExe) 'a proven start records the PID and ready.json with the served model'
    Check ($script:started[-1].WindowStyle -eq 'Hidden' -and $script:started[-1].WorkingDirectory -eq $published -and
        -not $script:started[-1].ArgumentList.Contains($key) -and $script:listenerChecks[-1] -eq "8080/4242/$pinnedExe" -and $script:proofKey -eq $key) 'the start is hidden, loopback-proven and authenticates /props without putting the key on argv'
    Check ([IO.File]::ReadAllText($options.LogPath + '.1') -eq 'previous run') 'the previous llama-server log is kept as one generation'
    $script:proofContext = 65536
    Check ((Get-Failure { $null = Start-ODSNativeLlamaLegacyProcess -Launch $launch -Port 8080 -ApiKey $key -PidFile $pidFile }) -match 'less than the planned 131072') 'a context below the plan fails the proof'
    Check ($script:child.Killed -and -not (Test-Path -LiteralPath $pidFile) -and -not (Test-Path -LiteralPath (Join-Path (Get-ODSNativeRuntimeDir) 'ready.json'))) 'a failed proof stops the launched process through its handle and leaves no readiness record'
    $script:proofContext = 131072
    $script:startupFailure = 'llama-server exited during startup with code -1073741515. A DLL it needs is missing (0xC0000135), most likely the Microsoft Visual C++ 2015-2022 Redistributable (x64).'
    Check ((Get-Failure { $null = Start-ODSNativeLlamaLegacyProcess -Launch $launch -Port 8080 -ApiKey $key -PidFile $pidFile }) -match 'Visual C\+\+') 'a startup crash surfaces its explained exit code'
    $script:startupFailure = ''
    $script:listeners = @([pscustomobject]@{ OwningProcess = 77 })
    Check (-not (Wait-ODSNativeLlamaLegacyPortFree -Port 8080 -TimeoutSeconds 0)) 'a listener that stays on the port is reported as busy'
    $script:listeners = @()
    Check (Wait-ODSNativeLlamaLegacyPortFree -Port 8080 -TimeoutSeconds 0) 'a free port is reported free'
    $realPortFree = ${function:Wait-ODSNativeLlamaLegacyPortFree}
    function Wait-ODSNativeLlamaLegacyPortFree { param([int]$Port, [int]$TimeoutSeconds = 15) return $false }
    $script:started = @()
    Check ((Get-Failure { $null = Start-ODSNativeLlamaLegacyProcess -Launch $launch -Port 8080 -ApiKey $key -PidFile $pidFile }) -match 'already in use' -and $script:started.Count -eq 0) 'a busy port stops the start before any process is launched'
    Set-Item -Path Function:Wait-ODSNativeLlamaLegacyPortFree -Value $realPortFree

    # --- The at-logon task ---
    $taskArguments = Get-ODSNativeLlamaLegacyTaskArguments $install
    Check ($taskArguments -ceq ('-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + (Join-Path $install 'ods.ps1') + '" native-llm-start "' + $install + '"') -and
        -not $taskArguments.Contains($key)) 'the task runs "ods.ps1 native-llm-start" for this installation, with no secret in its action'
    $script:registered = $null
    function New-ScheduledTaskAction { param($Execute, $Argument, $WorkingDirectory) return [pscustomobject]@{ Execute = $Execute; Arguments = $Argument; WorkingDirectory = $WorkingDirectory } }
    function New-ScheduledTaskTrigger { param([switch]$AtLogOn, $User) return [pscustomobject]@{ AtLogOn = [bool]$AtLogOn; User = $User } }
    function New-ScheduledTaskSettingsSet { param([switch]$AllowStartIfOnBatteries, [switch]$DontStopIfGoingOnBatteries, $ExecutionTimeLimit, $RestartCount, $RestartInterval)
        return [pscustomobject]@{ ExecutionTimeLimit = $ExecutionTimeLimit; RestartCount = $RestartCount; RestartInterval = $RestartInterval } }
    function Resolve-ODSInteractiveScheduledTaskUser { return 'FIXTURE\user' }
    function New-ODSInteractiveScheduledTaskPrincipal { param($RunLevel) return [pscustomobject]@{ RunLevel = $RunLevel } }
    function Register-ScheduledTask {
        param($TaskName, $TaskPath, $Action, $Trigger, $Settings, $Principal, [switch]$Force, $ErrorAction, $Description)
        $script:registered = [pscustomobject]@{ TaskName = $TaskName; TaskPath = $TaskPath; Action = $Action; Trigger = $Trigger; Settings = $Settings; Principal = $Principal; Force = [bool]$Force }
    }
    Register-ODSNativeLlamaLegacyTask -InstallDir $install
    Check ($script:registered.TaskName -eq 'ODSNativeLlamaRuntime' -and $script:registered.TaskPath -eq '\' -and $script:registered.Force -and
        $script:registered.Action.Execute -eq 'powershell.exe' -and $script:registered.Action.Arguments -ceq $taskArguments -and
        $script:registered.Action.WorkingDirectory -eq $install) 'ODSNativeLlamaRuntime runs the ods.ps1 launcher from the install folder'
    Check ($script:registered.Trigger.AtLogOn -and $script:registered.Trigger.User -eq 'FIXTURE\user' -and $script:registered.Principal.RunLevel -eq 'Limited' -and
        $script:registered.Settings.ExecutionTimeLimit -eq [TimeSpan]::Zero -and $script:registered.Settings.RestartCount -eq 3 -and
        $script:registered.Settings.RestartInterval -eq (New-TimeSpan -Minutes 1)) 'it starts at the user''s logon, at Limited integrity, with three restarts a minute apart'

    $script:task = $null
    $script:unreadable = $false
    $script:queried = @()
    function Get-ScheduledTask {
        [CmdletBinding()]
        param([string]$TaskName, [string]$TaskPath)
        $script:queried += $TaskName
        if ($script:unreadable) { Write-Error -Message 'Access is denied.' -Category PermissionDenied; return }
        if ($script:task -and $TaskName -eq $script:task.TaskName) { return $script:task }
    }
    function New-LlamaTask([object[]]$Actions, [string]$State = 'Ready') {
        return [pscustomobject]@{ TaskName = 'ODSNativeLlamaRuntime'; TaskPath = '\'; State = $State; Actions = $Actions }
    }
    Check ($null -eq (Get-ODSNativeLlamaLegacyTask -InstallDir $install)) 'no task means nothing to stop'
    $script:task = New-LlamaTask @([pscustomobject]@{ Execute = 'powershell.exe'; Arguments = $taskArguments })
    Check ((Get-ODSNativeLlamaLegacyTask -InstallDir $install).Owned) 'the Round F launcher action is ODS''s'
    $script:task = New-LlamaTask @([pscustomobject]@{ Execute = $pinnedExe; Arguments = '"--model" "x"' })
    Check ((Get-ODSNativeLlamaLegacyTask -InstallDir $install).Owned) 'the earlier direct launch of the published llama-server.exe is ODS''s'
    foreach ($action in @(
        @([pscustomobject]@{ Execute = 'C:\Tools\llama-server.exe'; Arguments = '' }),
        @([pscustomobject]@{ Execute = 'powershell.exe'; Arguments = ($taskArguments + ' ; calc') }),
        @([pscustomobject]@{ Execute = 'powershell.exe'; Arguments = $taskArguments }, [pscustomobject]@{ Execute = 'calc.exe'; Arguments = '' }))) {
        $script:task = New-LlamaTask $action
        Check (-not (Get-ODSNativeLlamaLegacyTask -InstallDir $install).Owned) "an unknown ODSNativeLlamaRuntime action is not adopted ($($action[0].Execute))"
    }
    $script:unreadable = $true
    Check ((Get-Failure { $null = Get-ODSNativeLlamaLegacyTask -InstallDir $install }) -match 'Cannot read') 'an unreadable task fails closed'
    $script:unreadable = $false

    # --- Stops: only processes ODS launches, proven by executable ---
    $script:calls = @()
    function Disable-ScheduledTask { param($TaskName, $TaskPath, $ErrorAction) $script:calls += "disable:$TaskName" }
    function Stop-ScheduledTask { param($TaskName, $TaskPath, $ErrorAction) $script:calls += "stop:$TaskName" }
    $script:nodes = @(
        [pscustomobject]@{ ProcessId = 100; ParentProcessId = 4; ExecutablePath = $pinnedExe },
        [pscustomobject]@{ ProcessId = 200; ParentProcessId = 4; ExecutablePath = 'C:\Tools\llama.cpp\llama-server.exe' },
        [pscustomobject]@{ ProcessId = 300; ParentProcessId = 4; ExecutablePath = $profileExe },
        [pscustomobject]@{ ProcessId = 400; ParentProcessId = 4; ExecutablePath = 'C:\Users\fixture\AppData\Local\lemonade_server\bin\lemonade-server.exe' })
    function Get-CimInstance { param($ClassName, $Filter, $ErrorAction) return $script:nodes }
    $script:treeRoots = @()
    function Get-ODSPortalOwnedProcessTree([object[]]$Roots, [object[]]$Nodes) {
        $script:treeRoots += @($Roots | ForEach-Object { $_.ProcessId })
        return [pscustomobject]@{ Nodes = $Roots; Handles = @() }
    }
    $script:stopRequests = 0
    function Stop-ODSPortalOwnedProcesses($Handles) { $script:stopRequests++ }
    $script:task = New-LlamaTask @([pscustomobject]@{ Execute = 'powershell.exe'; Arguments = $taskArguments }) 'Running'
    Set-Content -LiteralPath $pidFile -Value '100'
    $script:listeners = @([pscustomobject]@{ OwningProcess = 200 }, [pscustomobject]@{ OwningProcess = 100 })
    $stopped = Stop-ODSNativeLlamaLegacyRuntime -InstallDir $install -PidFile $pidFile -Port 8080
    Check ($stopped -eq 1 -and ($script:treeRoots -join ',') -eq '100' -and $script:stopRequests -eq 1) 'only the published llama-server is stopped; another llama-server.exe on the port is left alone'
    Check (($script:calls -join ',') -eq 'disable:ODSNativeLlamaRuntime,stop:ODSNativeLlamaRuntime' -and -not (Test-Path -LiteralPath $pidFile)) 'the logon task is disarmed first and the matching PID record is cleared'
    $script:treeRoots = @(); $script:calls = @()
    $script:listeners = @([pscustomobject]@{ OwningProcess = 300 })
    $stopped = Stop-ODSNativeLlamaLegacyRuntime -InstallDir $install -PidFile $pidFile -Port 8080 -ExecutablePaths @($profileExe)
    Check ($stopped -eq 1 -and ($script:treeRoots -join ',') -eq '300') 'the active model-store runtime is ODS''s too'
    $script:treeRoots = @()
    Set-Content -LiteralPath $pidFile -Value '400'
    $script:listeners = @([pscustomobject]@{ OwningProcess = 400 })
    $script:task = New-LlamaTask @([pscustomobject]@{ Execute = 'C:\Tools\other.exe'; Arguments = '' }) 'Running'
    $script:calls = @(); $script:output = @()
    $stopped = Stop-ODSNativeLlamaLegacyRuntime -InstallDir $install -PidFile $pidFile -Port 8080
    Check ($stopped -eq 0 -and (Test-Path -LiteralPath $pidFile) -and $script:calls.Count -eq 0 -and (@($script:output) -join ' ') -match 'stops no process') 'a Lemonade PID record and a foreign task action are left for the retire step'

    # A reinstall without the native AMD runtime (cloud, another GPU) must not
    # leave the old model starting at every logon.
    $script:unregistered = @()
    function Unregister-ScheduledTask { param($TaskName, $TaskPath, [switch]$Confirm, $ErrorAction) $script:unregistered += ($TaskPath + $TaskName) }
    Check (-not (Remove-ODSNativeLlamaLegacyRuntime -InstallDir $install -PidFile $pidFile -Port 8080) -and $script:unregistered.Count -eq 0) 'a logon task ODS did not write is never removed'
    $script:task = New-LlamaTask @([pscustomobject]@{ Execute = 'powershell.exe'; Arguments = $taskArguments }) 'Ready'
    $script:calls = @()
    Check ((Remove-ODSNativeLlamaLegacyRuntime -InstallDir $install -PidFile $pidFile -Port 8080) -and ($script:unregistered -join ',') -eq '\ODSNativeLlamaRuntime' -and
        $script:calls -contains 'disable:ODSNativeLlamaRuntime') 'a reinstall without the native AMD runtime disarms, stops and removes ODS''s logon task'

    # --- Registered model-store runtime of the active model, read without running anything ---
    $registry = @{ schemaVersion = 1; stores = @(@{ id = 'ssd'; hostPath = 'D:/models'; profiles = @{ 'model.gguf' = @{ backend = 'vulkan'; executable = $profileExe } } }) }
    [IO.File]::WriteAllText((Join-Path $install 'data\model-stores.json'), ($registry | ConvertTo-Json -Depth 6))
    Check ((Get-ODSNativeLlamaLegacyProfileExecutable -InstallDir $install -EnvMap @{ ODS_ACTIVE_MODEL_STORE = 'ssd'; GGUF_FILE = 'model.gguf' }) -eq $profileExe) 'the active store profile names its runtime'
    Check ((Get-ODSNativeLlamaLegacyProfileExecutable -InstallDir $install -EnvMap @{ ODS_ACTIVE_MODEL_STORE = 'default'; GGUF_FILE = 'model.gguf' }) -eq '') 'the default store has no profile runtime'

    # --- Stage and qualify before anything changes ---
    $script:qualification = $null
    function Get-ODSNativeLlamaPin { param($SourceRoot) return [pscustomobject]@{ ReleaseTag = 'b9014'; Build = 9014; Size = 33541404; Sha256 = ('c' * 64) } }
    function Install-ODSNativeLlamaRuntime { param($Pin) return $runtime }
    function Test-ODSNativeLlamaQualification { param($ExecutablePath, $ExpectedBuild, $AdapterName)
        if ($script:qualification -is [string]) { throw $script:qualification }
        return $script:qualification }
    $script:qualification = [pscustomobject]@{ Build = 9014; Devices = @(); Device = [pscustomobject]@{ Name = 'Vulkan0'; Description = 'AMD Radeon(TM) 8060S Graphics'; TotalMiB = 98304 }; PolicyHint = '' }
    $stage = Initialize-ODSNativeLlamaLegacyRuntime -SourceRoot $fixture -AdapterName 'AMD Radeon(TM) 8060S Graphics'
    Check ($stage.Device.Name -eq 'Vulkan0' -and $stage.Runtime.ReleaseTag -eq 'b9014') 'a qualified Vulkan device is staged'
    $script:qualification = [pscustomobject]@{ Build = 9014; Devices = @([pscustomobject]@{ Name = 'Vulkan0'; Description = 'llvmpipe' }); Device = $null; PolicyHint = '' }
    $script:output = @()
    $stage = Initialize-ODSNativeLlamaLegacyRuntime -SourceRoot $fixture -AdapterName 'AMD Radeon RX 7900 XTX'
    Check ($null -eq $stage.Device -and (@($script:output) -join ' ') -match 'no usable Vulkan device.*llvmpipe.*run on the CPU') 'a fresh install without a Vulkan device takes the CPU route with a driver message'
    Check ((Get-Failure { $null = Initialize-ODSNativeLlamaLegacyRuntime -SourceRoot $fixture -AdapterName 'AMD Radeon RX 7900 XTX' -HasExistingRuntime $true }) -match 'was not changed') 'an existing GPU install is left as it was when Vulkan is gone'
    $script:qualification = 'llama-server.exe --version failed with exit code -1073741515. A DLL it needs is missing (0xC0000135), most likely the Microsoft Visual C++ 2015-2022 Redistributable (x64).'
    Check ((Get-Failure { $null = Initialize-ODSNativeLlamaLegacyRuntime -SourceRoot $fixture -AdapterName 'x' }) -match 'Visual C\+\+') 'a binary that cannot run stops setup with the explained cause'

    # --- Installer cutover from ODS's own Lemonade ---
    $script:order = @()
    $script:lemonade = $null
    $script:left = ''
    $script:exitCode = 0
    $script:readyModel = 'Qwen3.6-35B-A3B-Q4_K_M.gguf'
    function Get-WindowsODSEnvMap { param($InstallDir) return @{ GGUF_FILE = 'Qwen3.6-35B-A3B-Q4_K_M.gguf'; LLAMA_SERVER_API_KEY = $key } }
    function Get-ODSLegacyLemonadeRuntime { param($InstallDir, $Port) $script:order += 'lemonade:inspect'; return $script:lemonade }
    function Stop-ODSNativeLlamaLegacyRuntime { param($InstallDir, $PidFile, $Port, $ExecutablePaths) $script:order += 'llama:stop'; return 0 }
    function Stop-ODSLegacyLemonadeRuntime { param($Runtime, $PidFile, $Port) $script:order += 'lemonade:stop'; return [pscustomobject]@{ Stopped = 2; Left = $script:left } }
    function Publish-ODSNativeLlamaRuntimeCopy { param($Runtime, $Destination) $script:order += 'publish'; return [pscustomobject]@{ Changed = $true } }
    function Register-ODSNativeLlamaLegacyTask { param($InstallDir) $script:order += 'register' }
    function Get-ScheduledTaskInfo { param($TaskName, $TaskPath, $InputObject, $ErrorAction) return [pscustomobject]@{ LastRunTime = [datetime]'1999-11-30' } }
    function Start-ScheduledTask {
        param($TaskName, $TaskPath, $ErrorAction)
        $script:order += "start:$TaskName"
        if ($script:exitCode -eq 0) {
            $record = @{ ProcessId = 4242; ExecutablePath = $pinnedExe; Port = 8080; ModelId = $script:readyModel; ContextLength = 131072 }
            Write-ODSPrivateEnvFile -Path (Join-Path (Get-ODSNativeRuntimeDir) 'ready.json') -Content ($record | ConvertTo-Json -Compress)
        } else {
            Write-ODSNativeLlamaLegacyLog 'llama-server exited during startup with code 1.'
        }
    }
    function Wait-ODSNativeLlamaLegacyTask { param($PreviousRunTime, $TimeoutSeconds) $script:order += 'wait'; return $script:exitCode }
    function Assert-ODSNativeLlamaListener { param($Port, $ProcessId, $ExecutablePath) $script:order += "listener:$ProcessId" }
    function Complete-ODSLegacyLemonadeRetirement { param($Runtime, $InstallDir) $script:order += 'lemonade:complete' }
    function Remove-ODSNativeLlamaOldRuntimes { param($KeepDirectory, $PreviousDirectory) $script:order += 'gc' }
    $stage = [pscustomobject]@{ Runtime = $runtime; Device = [pscustomobject]@{ Name = 'Vulkan0' } }
    $ownedLemonade = [pscustomobject]@{ Owned = $true; Reason = ''; Generation = 'direct' }

    $script:lemonade = $ownedLemonade
    $ready = Invoke-ODSNativeLlamaLegacyCutover -InstallDir $install -Stage $stage -Port 8080 -PidFile $pidFile
    Check (($script:order -join ',') -eq 'lemonade:inspect,llama:stop,lemonade:stop,publish,register,start:ODSNativeLlamaRuntime,wait,listener:4242,lemonade:complete,gc') 'cutover: stop ODS''s runtimes, publish, start through the task, prove, then retire Lemonade'
    Check ($ready.ModelId -eq 'Qwen3.6-35B-A3B-Q4_K_M.gguf' -and (Read-ODSNativeLlamaLegacyOptions).Device -eq 'Vulkan0' -and
        [IO.File]::ReadAllText((Read-ODSNativeLlamaLegacyOptions).ApiKeyPath) -ceq $key) 'the cutover writes the device and the .env key before the first start'

    $script:order = @(); $script:output = @()
    $script:lemonade = [pscustomobject]@{ Owned = $false; Reason = 'its action is not one ODS wrote' }
    $null = Invoke-ODSNativeLlamaLegacyCutover -InstallDir $install -Stage $stage -Port 8080 -PidFile $pidFile
    Check (-not ($script:order -contains 'lemonade:stop') -and -not ($script:order -contains 'lemonade:complete') -and
        (@($script:output) -join ' ') -match 'left it unchanged') 'a Lemonade task ODS cannot prove it owns is never stopped or removed'

    $script:order = @()
    $script:lemonade = $ownedLemonade
    $script:left = 'Port 8080 is still used by LemonadeServer.exe, which ODS cannot prove it started, so ODS left it running.'
    Check ((Get-Failure { $null = Invoke-ODSNativeLlamaLegacyCutover -InstallDir $install -Stage $stage -Port 8080 -PidFile $pidFile }) -match 'left it running' -and
        -not ($script:order -contains 'publish')) 'a port held by a Lemonade ODS did not start stops the cutover before anything is published'
    $script:left = ''

    $script:order = @()
    $script:exitCode = 1
    $failure = Get-Failure { $null = Invoke-ODSNativeLlamaLegacyCutover -InstallDir $install -Stage $stage -Port 8080 -PidFile $pidFile }
    Check ($failure -match 'did not start: .*exited during startup with code 1' -and $failure -match 'stays registered but disabled' -and
        -not ($script:order -contains 'lemonade:complete') -and -not ($script:order -contains 'gc')) 'a failed start names its cause, keeps the old task disabled and keeps the previous runtimes'
    $script:exitCode = 0

    $script:order = @()
    $script:readyModel = 'Qwen3.5-2B-Q4_K_M.gguf'
    Check ((Get-Failure { $null = Invoke-ODSNativeLlamaLegacyCutover -InstallDir $install -Stage $stage -Port 8080 -PidFile $pidFile }) -match 'not Qwen3\.6-35B-A3B-Q4_K_M\.gguf' -and
        -not ($script:order -contains 'lemonade:complete')) 'a start that serves another model is not accepted'
    $script:readyModel = 'Qwen3.6-35B-A3B-Q4_K_M.gguf'

    Check (@($script:queried | Where-Object { $_ -ne 'ODSNativeLlamaRuntime' }).Count -eq 0) 'only ODSNativeLlamaRuntime is looked up here; no other task is touched'
} finally {
    $env:LOCALAPPDATA = $previousLocalAppData
    Remove-Item -LiteralPath $fixture -Recurse -Force -ErrorAction SilentlyContinue
}
Write-Host "PASS ($script:checks checks)"
