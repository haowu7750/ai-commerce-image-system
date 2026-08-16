[CmdletBinding()]
param(
    [switch]$Check
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path.TrimEnd("\")
$ports = @(3100, 8100)
$listeners = @(
    Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
        Where-Object { $_.LocalPort -in $ports }
)

if ($listeners.Count -eq 0) {
    Write-Host "The commerce image system is not listening on ports 3100/8100."
    exit 0
}

$targets = @{}
foreach ($listener in $listeners) {
    $cursor = [int]$listener.OwningProcess
    $chain = @()
    for ($depth = 0; $depth -lt 8 -and $cursor -gt 0; $depth++) {
        $process = Get-CimInstance Win32_Process -Filter "ProcessId=$cursor" -ErrorAction SilentlyContinue
        if ($null -eq $process) { break }
        $chain += $process
        $cursor = [int]$process.ParentProcessId
    }

    $verified = @(
        $chain | Where-Object {
            $_.CommandLine -and
                $_.CommandLine.IndexOf($projectRoot, [StringComparison]::OrdinalIgnoreCase) -ge 0
        }
    )
    if ($verified.Count -eq 0) {
        throw "Port $($listener.LocalPort) is owned by an unverified process. Refusing to stop it."
    }

    $launcher = @(
        $verified | Where-Object {
            $_.CommandLine -match "scripts[\\/]start_local\.py"
        }
    ) | Select-Object -Last 1
    $target = if ($launcher) { $launcher } else { $verified | Select-Object -Last 1 }
    $targets[[int]$target.ProcessId] = $target
}

foreach ($target in $targets.Values) {
    Write-Host "Verified project process tree: PID $($target.ProcessId) $($target.Name)"
    if (-not $Check) {
        & taskkill.exe /PID $target.ProcessId /T /F | Out-Host
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to stop verified project process PID $($target.ProcessId)."
        }
    }
}

if ($Check) {
    Write-Host "Stop check passed; no process was changed."
} else {
    Write-Host "Commerce image system stopped."
}
