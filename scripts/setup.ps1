#Requires -Version 5.1
[CmdletBinding()]
param()
. (Join-Path $PSScriptRoot 'common.ps1')

Enable-UvPath
if (-not (Find-Application @('uv.exe'))) {
    Write-Host 'uvを公式インストーラーからユーザー環境に導入します。'
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    # https://docs.astral.sh/uv/getting-started/installation/ のWindows推奨手順。
    $installer = Invoke-RestMethod -Uri 'https://astral.sh/uv/install.ps1'
    Invoke-Expression $installer
    Enable-UvPath
}

$tools = Get-Tools
Invoke-Checked $tools.Uv @('--version') $script:ProjectRoot
Write-Host 'Python依存関係をセットアップします（Python未導入時はuvが取得）。'
Invoke-Checked $tools.Uv @('sync', '--locked') (Join-Path $script:ProjectRoot 'backend')
Write-Host 'フロントエンド依存関係をセットアップします。'
Invoke-Checked $tools.Pnpm @('install', '--frozen-lockfile') (Join-Path $script:ProjectRoot 'frontend')

$stateDirectory = Join-Path $script:ProjectRoot '.dev-state'
New-Item -ItemType Directory -Path $stateDirectory -Force | Out-Null
@{ fingerprint = Get-DependencyFingerprint } | ConvertTo-Json |
    Set-Content -LiteralPath (Join-Path $stateDirectory 'dependencies.json') -Encoding UTF8
Write-Host 'セットアップ完了。.\scripts\dev.ps1 で起動できます。' -ForegroundColor Green
