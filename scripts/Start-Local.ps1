[CmdletBinding()]
param(
    [switch]$BackendOnly,
    [switch]$FrontendOnly,
    [int]$BackendPort = 8100,
    [int]$FrontendPort = 3100
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ($BackendOnly -and $FrontendOnly) {
    throw 'BackendOnly and FrontendOnly cannot be used together.'
}

$workspaceRoot = Split-Path -Parent $PSScriptRoot
$python = [System.IO.Path]::Combine(
    $workspaceRoot,
    '.venv',
    'Scripts',
    'python.exe'
)
$launcher = [System.IO.Path]::Combine(
    $PSScriptRoot,
    'start_local.py'
)

if (-not [System.IO.File]::Exists($python)) {
    throw "Project Python environment is missing: $python"
}

$launcherArguments = @($launcher)
if ($PSBoundParameters.ContainsKey('BackendPort')) {
    $launcherArguments += @('--backend-port', [string]$BackendPort)
}
if ($PSBoundParameters.ContainsKey('FrontendPort')) {
    $launcherArguments += @('--frontend-port', [string]$FrontendPort)
}
if ($BackendOnly) {
    $launcherArguments += '--backend-only'
}
if ($FrontendOnly) {
    $launcherArguments += '--frontend-only'
}

& $python @launcherArguments
if ($LASTEXITCODE -ne 0) {
    throw 'Local system launcher exited with an error.'
}
