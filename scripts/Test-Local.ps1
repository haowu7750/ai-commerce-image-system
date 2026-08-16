[CmdletBinding()]
param(
    [switch]$SkipFrontend,
    [switch]$SkipBackend,
    [switch]$SkipSafety,
    [switch]$IncludeWebBuild
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'Workspace.Runtime.ps1')

$workspaceRoot = Get-WorkspaceRoot
$previousLocation = Get-Location
$previousImageProvider = $env:APP_IMAGE_PROVIDER
$previousTextProvider = $env:APP_TEXT_PROVIDER
$previousVisionProvider = $env:APP_VISION_PROVIDER
$previousImageModel = $env:APP_IMAGE_MODEL

try {
    $env:APP_IMAGE_PROVIDER = 'mock'
    $env:APP_TEXT_PROVIDER = 'mock'
    $env:APP_VISION_PROVIDER = 'mock'
    $env:APP_IMAGE_MODEL = 'gpt-image-2'

    if (-not $SkipSafety) {
        & (Join-Path $PSScriptRoot 'Test-Safety.ps1')
        if (-not $?) {
            throw 'Safety checks failed.'
        }
    }

    if (-not $SkipFrontend) {
        $pnpm = Resolve-WorkspacePnpm
        Assert-FrontendDependencies
        Set-Location $workspaceRoot

        Invoke-FrontendScript -Pnpm $pnpm -Command typecheck
        if ($LASTEXITCODE -ne 0) { throw 'Frontend typecheck failed.' }

        Invoke-FrontendScript -Pnpm $pnpm -Command test
        if ($LASTEXITCODE -ne 0) { throw 'Frontend tests failed.' }

        if ($IncludeWebBuild) {
            Invoke-FrontendScript -Pnpm $pnpm -Command build
            if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
        }
    }

    if (-not $SkipBackend) {
        $python = Resolve-WorkspacePython
        Assert-WorkspacePythonModules -Python $python -Modules @('fastapi', 'sqlalchemy', 'pytest', 'httpx', 'pydantic_settings')
        Set-Location (Join-Path $workspaceRoot 'backend')

        & $python -m pytest -q
        if ($LASTEXITCODE -ne 0) { throw 'Backend tests failed.' }
    }

    Write-Output 'Local checks passed. All Provider tests used Mock routing.'
}
finally {
    Set-Location $previousLocation

    if ($null -eq $previousImageProvider) { Remove-Item Env:APP_IMAGE_PROVIDER -ErrorAction SilentlyContinue } else { $env:APP_IMAGE_PROVIDER = $previousImageProvider }
    if ($null -eq $previousTextProvider) { Remove-Item Env:APP_TEXT_PROVIDER -ErrorAction SilentlyContinue } else { $env:APP_TEXT_PROVIDER = $previousTextProvider }
    if ($null -eq $previousVisionProvider) { Remove-Item Env:APP_VISION_PROVIDER -ErrorAction SilentlyContinue } else { $env:APP_VISION_PROVIDER = $previousVisionProvider }
    if ($null -eq $previousImageModel) { Remove-Item Env:APP_IMAGE_MODEL -ErrorAction SilentlyContinue } else { $env:APP_IMAGE_MODEL = $previousImageModel }
}
