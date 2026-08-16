$script:WorkspaceUtf8 = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = $script:WorkspaceUtf8
$OutputEncoding = $script:WorkspaceUtf8

$script:WorkspaceRuntimeRoot = Split-Path -Parent $PSScriptRoot

function Get-WorkspaceRoot {
    return $script:WorkspaceRuntimeRoot
}

function Repair-WorkspaceProcessPathCasing {
    # Some managed shells expose both Path and PATH. Windows Start-Process
    # copies variables into a case-insensitive dictionary and otherwise fails.
    $pathValue = $env:Path
    if ([string]::IsNullOrWhiteSpace($pathValue)) {
        $pathValue = $env:PATH
    }
    if (-not [string]::IsNullOrWhiteSpace($pathValue)) {
        [Environment]::SetEnvironmentVariable('PATH', $null, [EnvironmentVariableTarget]::Process)
        [Environment]::SetEnvironmentVariable('Path', $pathValue, [EnvironmentVariableTarget]::Process)
    }
}

function Test-ExecutableCandidate {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string[]]$ProbeArguments
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return $false
    }

    try {
        & $Path @ProbeArguments *> $null
        return $LASTEXITCODE -eq 0
    }
    catch {
        return $false
    }
}

function Resolve-WorkspacePnpm {
    $pathCommand = Get-Command pnpm -CommandType Application -ErrorAction SilentlyContinue
    $isCodexFallbackWrapper = $null -ne $pathCommand -and $pathCommand.Source -match '\\codex-runtimes\\.*\\bin\\fallback\\pnpm\.cmd$'
    if ($null -ne $pathCommand -and -not $isCodexFallbackWrapper -and (Test-ExecutableCandidate -Path $pathCommand.Source -ProbeArguments @('--version'))) {
        return [PSCustomObject]@{
            FilePath = $pathCommand.Source
            PrefixArguments = @()
            DisplayPath = $pathCommand.Source
            RunMode = 'pnpm'
        }
    }

    $userProfile = $env:USERPROFILE
    if ([string]::IsNullOrWhiteSpace($userProfile)) {
        throw 'USERPROFILE is not available, so the Codex bundled pnpm fallback cannot be resolved.'
    }
    $nodePath = Join-Path $userProfile '.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe'
    $pnpmCliPath = Join-Path $userProfile '.cache\codex-runtimes\codex-primary-runtime\dependencies\node\node_modules\pnpm\bin\pnpm.mjs'
    if ((Test-Path -LiteralPath $nodePath -PathType Leaf) -and (Test-Path -LiteralPath $pnpmCliPath -PathType Leaf)) {
        & $nodePath $pnpmCliPath --version *> $null
        if ($LASTEXITCODE -eq 0) {
            return [PSCustomObject]@{
                FilePath = $nodePath
                PrefixArguments = @($pnpmCliPath)
                DisplayPath = "$nodePath $pnpmCliPath"
                RunMode = 'direct'
            }
        }
    }

    throw 'No usable pnpm executable was found. Put pnpm on PATH or use a Codex bundled runtime. This script never installs dependencies.'
}

function Resolve-WorkspaceNode {
    $pathCommand = Get-Command node -CommandType Application -ErrorAction SilentlyContinue
    if ($null -ne $pathCommand -and (Test-ExecutableCandidate -Path $pathCommand.Source -ProbeArguments @('--version'))) {
        return $pathCommand.Source
    }

    $userProfile = $env:USERPROFILE
    if ([string]::IsNullOrWhiteSpace($userProfile)) {
        throw 'USERPROFILE is not available, so the Codex bundled Node fallback cannot be resolved.'
    }
    $nodePath = Join-Path $userProfile '.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe'
    if (Test-ExecutableCandidate -Path $nodePath -ProbeArguments @('--version')) {
        return $nodePath
    }

    throw 'No usable Node.js executable was found. This script never installs Node.js.'
}

function Invoke-FrontendScript {
    param(
        [Parameter(Mandatory = $true)][object]$Pnpm,
        [Parameter(Mandatory = $true)][ValidateSet('dev', 'build', 'typecheck', 'test')][string]$Command,
        [string[]]$AdditionalArguments = @()
    )

    if ($Pnpm.RunMode -eq 'pnpm') {
        $pnpmArguments = @('--dir', 'frontend', $Command) + $AdditionalArguments
        Invoke-WorkspacePnpm -Pnpm $Pnpm -Arguments $pnpmArguments
        return
    }

    $workspaceRoot = Get-WorkspaceRoot
    $node = Resolve-WorkspaceNode
    switch ($Command) {
        'dev' {
            $entryPoint = Join-Path $workspaceRoot 'frontend\node_modules\next\dist\bin\next'
            $commandArguments = @('dev') + $AdditionalArguments
        }
        'build' {
            $entryPoint = Join-Path $workspaceRoot 'frontend\node_modules\next\dist\bin\next'
            $commandArguments = @('build', '--webpack') + $AdditionalArguments
        }
        'typecheck' {
            $entryPoint = Join-Path $workspaceRoot 'frontend\node_modules\typescript\bin\tsc'
            $commandArguments = @('--noEmit') + $AdditionalArguments
        }
        'test' {
            $entryPoint = Join-Path $workspaceRoot 'frontend\node_modules\vitest\vitest.mjs'
            $commandArguments = @('run') + $AdditionalArguments
        }
    }

    if (-not (Test-Path -LiteralPath $entryPoint -PathType Leaf)) {
        throw "Frontend command entry point is missing: $entryPoint. Install dependencies manually as documented in README."
    }
    $previousLocation = Get-Location
    try {
        Set-Location (Join-Path $workspaceRoot 'frontend')
        & $node $entryPoint @commandArguments
    }
    finally {
        Set-Location $previousLocation
    }
}

function Invoke-WorkspacePnpm {
    param(
        [Parameter(Mandatory = $true)][object]$Pnpm,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    $prefixArguments = @($Pnpm.PrefixArguments)
    & $Pnpm.FilePath @prefixArguments @Arguments
}

function Resolve-WorkspacePython {
    foreach ($commandName in @('python', 'python3')) {
        $pathCommand = Get-Command $commandName -CommandType Application -ErrorAction SilentlyContinue
        $pythonProbe = 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'
        if ($null -ne $pathCommand -and (Test-ExecutableCandidate -Path $pathCommand.Source -ProbeArguments @('-c', $pythonProbe))) {
            return $pathCommand.Source
        }
    }

    $workspaceRoot = Get-WorkspaceRoot
    $userProfile = $env:USERPROFILE
    if ([string]::IsNullOrWhiteSpace($userProfile)) {
        throw 'USERPROFILE is not available, so the Codex bundled Python fallback cannot be resolved.'
    }
    $candidates = @(
        (Join-Path $workspaceRoot '.venv\Scripts\python.exe'),
        (Join-Path $userProfile '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe')
    )
    foreach ($candidate in $candidates) {
        if (Test-ExecutableCandidate -Path $candidate -ProbeArguments @('-c', $pythonProbe)) {
            return $candidate
        }
    }

    throw 'Python 3.11 or newer was not found on PATH, in the root .venv, or in the known Codex bundled runtime. This script never installs Python.'
}

function Assert-WorkspacePythonModules {
    param(
        [Parameter(Mandatory = $true)][string]$Python,
        [Parameter(Mandatory = $true)][string[]]$Modules
    )

    $probe = "import importlib.util,sys; missing=[m for m in sys.argv[1:] if importlib.util.find_spec(m) is None]; print('missing=' + ','.join(missing) if missing else 'python-modules-ok'); raise SystemExit(1 if missing else 0)"
    & $Python -c $probe @Modules
    if ($LASTEXITCODE -ne 0) {
        throw 'Backend Python dependencies are missing. Follow the one-time manual setup in README and activate the root .venv. This script never runs pip install.'
    }
}

function Assert-FrontendDependencies {
    $workspaceRoot = Get-WorkspaceRoot
    $requiredFiles = @(
        (Join-Path $workspaceRoot 'frontend\node_modules\next\dist\bin\next'),
        (Join-Path $workspaceRoot 'frontend\node_modules\typescript\bin\tsc'),
        (Join-Path $workspaceRoot 'frontend\node_modules\vitest\vitest.mjs')
    )
    if (@($requiredFiles | Where-Object { -not (Test-Path -LiteralPath $_ -PathType Leaf) }).Count -gt 0) {
        throw 'Frontend dependencies are missing. Manually run pnpm install --frozen-lockfile as documented in README. This script never installs dependencies.'
    }
}
