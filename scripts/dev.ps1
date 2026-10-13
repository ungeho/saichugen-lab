#Requires -Version 5.1
[CmdletBinding()]
param(
    [switch]$NoBrowser,
    [ValidateRange(0, 3600)][int]$StopAfterSeconds = 0
)
. (Join-Path $PSScriptRoot 'common.ps1')

$tools = Get-Tools
Assert-AvailablePort 8000
Assert-AvailablePort 5173
Test-DevelopmentDependencies $tools
Initialize-ProcessGroup
$group = New-Object ArenaDev.ProcessGroup
$servers = @()
$logs = @()
$offsets = @{}

function Show-NewLogs {
    foreach ($log in $logs) {
        if (Test-Path -LiteralPath $log.path) {
            $lines = @(Get-Content -LiteralPath $log.path -Encoding UTF8 -ErrorAction SilentlyContinue)
            $previous = $offsets[$log.path]
            if ($null -eq $previous) { $previous = 0 }
            for ($i = $previous; $i -lt $lines.Count; $i++) {
                Write-Host "[$($log.name)] $($lines[$i])"
            }
            $offsets[$log.path] = $lines.Count
        }
    }
}

try {
    $logDirectory = Join-Path $script:ProjectRoot ('.dev-state\logs\' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
    New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
    $backendLog = Join-Path $logDirectory 'backend'
    $frontendLog = Join-Path $logDirectory 'frontend'
    foreach ($serverName in @('backend', 'frontend')) {
        foreach ($stream in @('out', 'err')) {
            $logs += @{ name = $serverName; path = (Join-Path $logDirectory "$serverName.$stream.log") }
        }
    }
    Write-Host "ログ保存先: $logDirectory"
    $servers += Start-DevProcess $group $tools.Uv @('run', '--locked', 'uvicorn', 'strategy_arena.api.app:app',
        '--app-dir', 'src', '--host', '127.0.0.1', '--port', '8000') (Join-Path $script:ProjectRoot 'backend') $backendLog
    # pnpm devと同じViteエントリをNodeから起動し、cmdラッパーを挟まず管理する。
    $servers += Start-DevProcess $group $tools.Node @((Join-Path $script:ProjectRoot 'frontend\node_modules\vite\bin\vite.js'),
        '--host', '127.0.0.1', '--port', '5173', '--strictPort') (Join-Path $script:ProjectRoot 'frontend') $frontendLog
    $deadline = (Get-Date).AddSeconds(60)
    $ready = $false
    while ((Get-Date) -lt $deadline) {
        Show-NewLogs
        foreach ($server in $servers) {
            if ($server.HasExited) { throw "開発サーバーが起動中に終了しました (PID $($server.Id))。ログを確認してください。" }
        }
        if ((Test-HttpReady 'http://127.0.0.1:8000/api/health') -and (Test-HttpReady 'http://127.0.0.1:5173/')) {
            $ready = $true
            break
        }
        Start-Sleep -Milliseconds 250
    }
    if (-not $ready) { throw '60秒以内に起動を確認できませんでした。上記のログを確認してください。' }
    Write-Host '起動完了: http://127.0.0.1:5173/  API: http://127.0.0.1:8000/api/health' -ForegroundColor Green
    Write-Host 'このPowerShellに両サーバーのログを表示します。Ctrl+Cで両方を停止します。'
    if (-not $NoBrowser) { Start-Process 'http://127.0.0.1:5173/' }
    $started = Get-Date
    while ($true) {
        Show-NewLogs
        foreach ($server in $servers) {
            if ($server.HasExited) { throw "開発サーバーが終了しました (PID $($server.Id))。両サーバーを停止します。" }
        }
        if ($StopAfterSeconds -gt 0 -and ((Get-Date) - $started).TotalSeconds -ge $StopAfterSeconds) { break }
        Start-Sleep -Milliseconds 250
    }
} finally {
    $group.Dispose()
    foreach ($server in $servers) { $server.WaitForExit(5000) | Out-Null; $server.Dispose() }
    Show-NewLogs
    Write-Host 'このスクリプトが起動した開発サーバーを停止しました。ログファイルは保持します。'
}
