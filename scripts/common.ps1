# Windows PowerShell 5.1 / PowerShell 7 共通の開発用ヘルパー。
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$script:ProjectRoot = Split-Path -Parent $PSScriptRoot

function Find-Application([string[]]$Names) {
    foreach ($name in $Names) {
        $command = Get-Command $name -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($command) { return $command.Source }
    }
    return $null
}

function Enable-UvPath {
    # 永続PATHを書き換えず、既に導入済みのuvを現在のプロセスでも解決する。
    $bin = Join-Path $env:USERPROFILE '.local\bin'
    if ((Test-Path -LiteralPath (Join-Path $bin 'uv.exe')) -and
        -not (($env:Path -split ';') -contains $bin)) {
        $env:Path = "$bin;$env:Path"
    }
}

function Get-Tools {
    Enable-UvPath
    $uv = Find-Application @('uv.exe')
    $node = Find-Application @('node.exe')
    $pnpm = Find-Application @('pnpm.cmd', 'pnpm.exe')
    if (-not $uv) { throw 'uvがありません。先に .\scripts\setup.ps1 を実行してください。' }
    if (-not $node) { throw 'Node.js 22.12以降のLTSを https://nodejs.org/ から導入し、PowerShellを開き直してください。' }
    $nodeVersion = (& $node --version).Trim().TrimStart('v')
    if ($LASTEXITCODE -ne 0 -or [version]$nodeVersion -lt [version]'22.12.0') {
        throw "Node.js 22.12以降が必要です。現在: $nodeVersion"
    }
    if (-not $pnpm) { throw 'pnpmがありません。npm install --global pnpm@11.25.0 を実行してください。' }
    $pnpmVersion = (& $pnpm --version | Select-Object -Last 1).Trim()
    if ($LASTEXITCODE -ne 0 -or $pnpmVersion -notmatch '^11\.') {
        throw "pnpm 11が必要です。現在: $pnpmVersion。npm install --global pnpm@11.25.0 を実行してください。"
    }
    return @{ Uv = $uv; Node = $node; Pnpm = $pnpm }
}

function Invoke-Checked([string]$Executable, [string[]]$Arguments, [string]$Directory) {
    Push-Location -LiteralPath $Directory
    try {
        & $Executable @Arguments
        if ($LASTEXITCODE -ne 0) { throw "コマンドが失敗しました (終了コード $LASTEXITCODE): $Executable $($Arguments -join ' ')" }
    } finally { Pop-Location }
}

function Get-DependencyFingerprint {
    $files = @('backend\pyproject.toml', 'backend\uv.lock', 'frontend\package.json',
               'frontend\pnpm-lock.yaml', 'frontend\pnpm-workspace.yaml')
    return (($files | ForEach-Object {
        (Get-FileHash -LiteralPath (Join-Path $script:ProjectRoot $_) -Algorithm SHA256).Hash
    }) -join ':')
}

function Test-DevelopmentDependencies($Tools) {
    $stateFile = Join-Path $script:ProjectRoot '.dev-state\dependencies.json'
    if (-not (Test-Path -LiteralPath $stateFile)) { throw '初回セットアップが必要です。.\scripts\setup.ps1 を実行してください。' }
    $state = Get-Content -LiteralPath $stateFile -Raw | ConvertFrom-Json
    if ($state.fingerprint -ne (Get-DependencyFingerprint)) {
        throw '依存関係の定義が変更されています。.\scripts\setup.ps1 を再実行してください。'
    }
    foreach ($relative in @('backend\.venv\Scripts\python.exe', 'frontend\node_modules\vite\bin\vite.js')) {
        if (-not (Test-Path -LiteralPath (Join-Path $script:ProjectRoot $relative))) {
            throw "依存ファイルがありません: $relative。.\scripts\setup.ps1 を実行してください。"
        }
    }
    Invoke-Checked $Tools.Uv @('sync', '--locked', '--check') (Join-Path $script:ProjectRoot 'backend')
}

function Assert-AvailablePort([int]$Port) {
    $listeners = @([Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners())
    if ($listeners | Where-Object { $_.Port -eq $Port }) {
        $ownerText = ''
        if (Get-Command Get-NetTCPConnection -ErrorAction SilentlyContinue) {
            $owners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
                        Select-Object -ExpandProperty OwningProcess -Unique)
            if ($owners.Count) { $ownerText = " (PID: $($owners -join ', '))" }
        }
        throw "ポート $Port は既に使用中です$ownerText。使用中のサーバーを確認して終了してから再実行してください。既存プロセスは自動停止しません。"
    }
}

function Initialize-ProcessGroup {
    if ('ArenaDev.ProcessGroup' -as [type]) { return }
    # Job Objectにより子プロセスもまとめて停止。親PowerShellの終了時にもハンドルが閉じる。
    Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Diagnostics;
using System.Runtime.InteropServices;
namespace ArenaDev {
    public sealed class ProcessGroup : IDisposable {
        [StructLayout(LayoutKind.Sequential)] struct BasicLimits {
            public long ProcessTime, JobTime;
            public uint Flags;
            public UIntPtr MinWorkingSet, MaxWorkingSet;
            public uint ActiveProcesses;
            public UIntPtr Affinity;
            public uint Priority, Scheduling;
        }
        [StructLayout(LayoutKind.Sequential)] struct IoCounters {
            public ulong ReadOps, WriteOps, OtherOps, ReadBytes, WriteBytes, OtherBytes;
        }
        [StructLayout(LayoutKind.Sequential)] struct ExtendedLimits {
            public BasicLimits Basic;
            public IoCounters Io;
            public UIntPtr ProcessMemory, JobMemory, PeakProcessMemory, PeakJobMemory;
        }
        [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
        static extern IntPtr CreateJobObject(IntPtr attributes, string name);
        [DllImport("kernel32.dll", SetLastError=true)]
        static extern bool SetInformationJobObject(IntPtr job, int kind, ref ExtendedLimits limits, uint length);
        [DllImport("kernel32.dll", SetLastError=true)]
        static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);
        [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr handle);
        IntPtr handle;
        public ProcessGroup() {
            handle = CreateJobObject(IntPtr.Zero, null);
            if (handle == IntPtr.Zero) throw new Win32Exception();
            var limits = new ExtendedLimits();
            limits.Basic.Flags = 0x2000; // JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if (!SetInformationJobObject(handle, 9, ref limits, (uint)Marshal.SizeOf(limits))) {
                int error = Marshal.GetLastWin32Error(); Dispose(); throw new Win32Exception(error);
            }
        }
        public void Add(Process process) {
            if (!AssignProcessToJobObject(handle, process.Handle)) throw new Win32Exception();
        }
        public void Dispose() {
            if (handle != IntPtr.Zero) { CloseHandle(handle); handle = IntPtr.Zero; }
        }
    }
}
'@
}

function Start-DevProcess($Group, [string]$Executable, [string[]]$Arguments, [string]$Directory, [string]$LogPrefix) {
    # Windowsのコマンドライン規則に従い、空白を含むパスも単一引数として渡す。
    $quoted = @($Arguments | ForEach-Object { '"' + ([regex]::Replace($_, '(\\*)"', '$1$1\"') -replace '(\\+)$', '$1$1') + '"' })
    $process = Start-Process -FilePath $Executable -ArgumentList ($quoted -join ' ') -WorkingDirectory $Directory `
        -WindowStyle Hidden -PassThru -RedirectStandardOutput "$LogPrefix.out.log" -RedirectStandardError "$LogPrefix.err.log"
    try { $Group.Add($process) } catch {
        if (-not $process.HasExited) { Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue }
        throw
    }
    return $process
}

function Test-HttpReady([string]$Url) {
    try { return (Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 1).StatusCode -eq 200 }
    catch { return $false }
}
