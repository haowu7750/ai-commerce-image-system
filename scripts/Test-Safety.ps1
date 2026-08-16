[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'Workspace.Runtime.ps1')

$workspaceRoot = Get-WorkspaceRoot
$failures = [System.Collections.Generic.List[string]]::new()

function Assert-TextMatch {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Pattern,
        [Parameter(Mandatory = $true)][string]$FailureMessage
    )

    if (-not (Select-String -LiteralPath $Path -Pattern $Pattern -Quiet -Encoding UTF8)) {
        $failures.Add($FailureMessage)
    }
}

$backendConfig = Join-Path $workspaceRoot 'backend\app\config.py'
Assert-TextMatch -Path $backendConfig -Pattern 'env_prefix="APP_"' -FailureMessage 'Backend Provider settings must use the APP_ environment prefix.'
Assert-TextMatch -Path $backendConfig -Pattern 'image_provider: Literal\["mock", "shulicode"\] = "mock"' -FailureMessage 'The code default for APP_IMAGE_PROVIDER must remain mock.'
Assert-TextMatch -Path $backendConfig -Pattern 'image_model: str = Field' -FailureMessage 'The image model must remain a validated Settings field.'
Assert-TextMatch -Path $backendConfig -Pattern 'default="gpt-image-2"' -FailureMessage 'The image model default must remain gpt-image-2.'

$handoffCandidates = @(
    Get-ChildItem -LiteralPath $workspaceRoot -Directory |
        Where-Object {
            $_.Name -like '*_v0.1' -and
            (Test-Path -LiteralPath (Join-Path $_.FullName 'manifest.json') -PathType Leaf)
        }
)
$handoffRoot = if ($handoffCandidates.Count -eq 1) { $handoffCandidates[0].FullName } else { $null }
$handoffHashes = @(
    'F8EF97895F853676C2D0DF3149AFDF1C62D346C8EB81DF18419D7710A2059EB1',
    '7B29C5B84D14C8816B20A2073408D21FE7AE08FAC5A3D08A0442704FE8032FF2',
    '5A992AC65D0EC7FFD87FD06C4125696820CFA64BAA11E62DA16A786C46272409',
    'ABA5D04CE84535DE25218E4458D93399A52FE5A59872E2D3BF03B14EF6EB670F',
    'E5A8440B23D3FCF4E93E5F745AF82F6A1153C95F025A15A6BD0A62D3B5C08D4F',
    '9C8247202769D2E4536DB1009A6EA29A8015483957FA1AFAEC6B36A9EB1DB050',
    'FCD9CC1847A25AC3B4098D38A747309CB690376C86DADE41C0D640C3C2911B2A',
    '73C5757730BD83E65643C82F1971BDCB9C5794008A699FF81917CC15A5C3AC3F',
    'E9203A1E40C6CBAE11EEEA2151C994B0A6DA4F18E9BD087FA1C93A35C8D1BFEA'
)
if ($null -eq $handoffRoot) {
    $failures.Add('The original V0.1 handoff directory is missing.')
}
else {
    $handoffManifestPath = Join-Path $handoffRoot 'manifest.json'
    $handoffManifest = Get-Content -LiteralPath $handoffManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $handoffNames = @($handoffManifest.document_order) + @('AGENTS.md', 'manifest.json')
    $actualHandoffFiles = @(Get-ChildItem -LiteralPath $handoffRoot -Recurse -File)
    $actualHandoffDirectories = @(Get-ChildItem -LiteralPath $handoffRoot -Recurse -Directory)
    if ($actualHandoffFiles.Count -ne $handoffHashes.Count -or $actualHandoffDirectories.Count -ne 0) {
        $failures.Add('The original V0.1 handoff package file/directory shape changed from the recorded baseline.')
    }
    for ($index = 0; $index -lt $handoffNames.Count; $index++) {
        $handoffName = [string]$handoffNames[$index]
        $handoffPath = Join-Path $handoffRoot $handoffName
        if (-not (Test-Path -LiteralPath $handoffPath -PathType Leaf)) {
            $failures.Add("Original handoff file is missing: $handoffName")
            continue
        }
        $actualHash = (Get-FileHash -LiteralPath $handoffPath -Algorithm SHA256).Hash
        if ($actualHash -ne $handoffHashes[$index]) {
            $failures.Add("Original handoff file changed from the recorded SHA-256 baseline: $handoffName")
        }
    }
}

$scriptFiles = Get-ChildItem -LiteralPath (Join-Path $workspaceRoot 'scripts') -File -Filter '*.ps1'
$installPattern = '(?i)^\s*(?:&\s+)?(?:(?:pnpm|npm|yarn)\s+install\b|pip\s+install\b|(?:python|python3|\$[A-Za-z_][A-Za-z0-9_]*)\s+-m\s+pip\s+install\b|poetry\s+install\b|uv\s+sync\b)'
foreach ($scriptFile in $scriptFiles) {
    if (Select-String -LiteralPath $scriptFile.FullName -Pattern $installPattern -Quiet -Encoding UTF8) {
        $failures.Add("Installer command found in script: $($scriptFile.Name)")
    }
}

$sourceFiles = [System.Collections.Generic.List[System.IO.FileInfo]]::new()
foreach ($relativeRoot in @('backend\app', 'frontend\app', 'frontend\src', 'scripts')) {
    $scanRoot = Join-Path $workspaceRoot $relativeRoot
    if (Test-Path -LiteralPath $scanRoot -PathType Container) {
        Get-ChildItem -LiteralPath $scanRoot -Recurse -File |
            Where-Object { $_.Extension -in @('.py', '.ts', '.tsx', '.js', '.mjs', '.cjs', '.json', '.ps1') } |
            ForEach-Object { $sourceFiles.Add($_) }
    }
}

$secretPatterns = @(
    'sk-[A-Za-z0-9_-]{20,}',
    '(?i)APP_IMAGE_API_KEY\s*=\s*[A-Za-z0-9_-]{16,}',
    '(?i)Bearer\s+[A-Za-z0-9._-]{20,}'
)
foreach ($sourceFile in $sourceFiles) {
    foreach ($pattern in $secretPatterns) {
        if (Select-String -LiteralPath $sourceFile.FullName -Pattern $pattern -Quiet -Encoding UTF8) {
            $relativePath = $sourceFile.FullName.Substring($workspaceRoot.Length).TrimStart('\')
            $failures.Add("Credential-shaped literal found in source: $relativePath")
            break
        }
    }
}

if ($failures.Count -gt 0) {
    Write-Error ("Safety checks failed:`n- " + ($failures -join "`n- "))
    exit 1
}

Write-Output 'Safety checks passed: Mock default, gpt-image-2 lock, handoff SHA-256 baseline, no installer commands, and no credential-shaped source literals.'
