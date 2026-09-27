$ErrorActionPreference = 'Stop'
$root = Join-Path $env:TEMP ("xhs-watchdog-test-" + [guid]::NewGuid().ToString('N'))
$appDirectory = Join-Path $root 'app'
$setupDirectory = Join-Path $appDirectory 'setup'
$logs = Join-Path $root 'profile\XhsXuanpin\data\logs'
$appPath = Join-Path $appDirectory 'XhsXuanpin.App.exe'
$watchdogPath = Join-Path $setupDirectory 'watchdog.ps1'
$powershellPath = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
$previousLocalAppData = $env:LOCALAPPDATA
$guardian = $null

try {
    New-Item -ItemType Directory -Path $setupDirectory, $logs -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot '..\watchdog.ps1'), (Join-Path $PSScriptRoot '..\launch-watchdog.vbs') -Destination $setupDirectory
    New-Item -ItemType File -Path (Join-Path $appDirectory 'installed.marker') | Out-Null

    $source = @'
using System;
using System.Diagnostics;
using System.IO;
using System.Threading;
public static class Program {
    public static int Main() {
        string mode = File.ReadAllText(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "mode.txt")).Trim();
        if (mode == "normal") {
            string token = Environment.GetEnvironmentVariable("XHS_XUANPIN_WATCHDOG_TOKEN");
            string logs = Path.Combine(Environment.GetEnvironmentVariable("LOCALAPPDATA"), "XhsXuanpin", "data", "logs");
            Directory.CreateDirectory(logs);
            File.WriteAllText(Path.Combine(logs, "watchdog-exit-" + token), Process.GetCurrentProcess().Id.ToString());
            return 0;
        }
        if (mode == "wait") Thread.Sleep(30000);
        return 23;
    }
}
'@
    Set-Content -LiteralPath (Join-Path $root 'Program.cs') -Value $source -Encoding Ascii
    Set-Content -LiteralPath (Join-Path $root 'build.ps1') -Value 'param($SourcePath,$OutputPath); Add-Type -Path $SourcePath -OutputAssembly $OutputPath -OutputType WindowsApplication' -Encoding Ascii
    & $powershellPath -NoProfile -File (Join-Path $root 'build.ps1') (Join-Path $root 'Program.cs') $appPath
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $appPath)) { throw 'Watchdog test app compilation failed' }

    $env:LOCALAPPDATA = Join-Path $root 'profile'
    Set-Content -LiteralPath (Join-Path $appDirectory 'mode.txt') -Value 'normal'
    & (Join-Path $env:WINDIR 'System32\wscript.exe') (Join-Path $setupDirectory 'launch-watchdog.vbs')
    for ($attempt = 0; $attempt -lt 50; $attempt++) {
        if ((Test-Path -LiteralPath (Join-Path $logs 'watchdog.log')) -and
            (Get-Content -LiteralPath (Join-Path $logs 'watchdog.log') -Raw) -match 'exited normally') { break }
        Start-Sleep -Milliseconds 100
    }
    $normalLog = Get-Content -LiteralPath (Join-Path $logs 'watchdog.log') -Raw
    if ($normalLog -notmatch 'exited normally' -or $normalLog -match 'Restart scheduled') {
        throw 'Normal exit restarted the workbench'
    }
    Start-Sleep -Milliseconds 200

    Remove-Item -LiteralPath (Join-Path $logs 'watchdog.log')
    Set-Content -LiteralPath (Join-Path $appDirectory 'mode.txt') -Value 'abnormal'
    & $powershellPath -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $watchdogPath
    $abnormalLog = Get-Content -LiteralPath (Join-Path $logs 'watchdog.log') -Raw
    if (([regex]::Matches($abnormalLog, 'Workbench started; pid=')).Count -ne 4 -or
        ([regex]::Matches($abnormalLog, 'Restart scheduled; attempt=')).Count -ne 3 -or
        $abnormalLog -notmatch 'Three automatic restarts within ten minutes') {
        throw 'Abnormal exit restart limit was not enforced'
    }

    Remove-Item -LiteralPath (Join-Path $logs 'watchdog.log')
    Set-Content -LiteralPath (Join-Path $appDirectory 'mode.txt') -Value 'wait'
    $guardian = Start-Process -FilePath $powershellPath -ArgumentList "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$watchdogPath`"" -WindowStyle Hidden -PassThru
    $seen = @{}
    for ($cycle = 0; $cycle -lt 4; $cycle++) {
        $deadline = (Get-Date).AddSeconds(20)
        do {
            $mock = Get-Process -Name 'XhsXuanpin.App' -ErrorAction SilentlyContinue | Where-Object {
                try {
                    [string]::Equals($_.Path, $appPath, [System.StringComparison]::OrdinalIgnoreCase) -and
                    -not $seen.ContainsKey($_.Id)
                } catch { $false }
            } | Select-Object -First 1
            if ($mock) { break }
            Start-Sleep -Milliseconds 100
        } while ((Get-Date) -lt $deadline)
        if (-not $mock) { throw "Watchdog did not launch mock process $($cycle + 1)" }
        $seen[$mock.Id] = $true
        Stop-Process -Id $mock.Id -Force
    }
    if (-not $guardian.WaitForExit(10000)) { throw 'Watchdog did not stop after the restart limit' }
    $killLog = Get-Content -LiteralPath (Join-Path $logs 'watchdog.log') -Raw
    if (([regex]::Matches($killLog, 'Restart scheduled; attempt=')).Count -ne 3 -or
        $killLog -notmatch 'Three automatic restarts within ten minutes') {
        throw 'Forced termination did not follow the restart limit'
    }

    Write-Host 'Watchdog normal exit, forced termination and restart limit passed'
} finally {
    if ($guardian -and -not $guardian.HasExited) { Stop-Process -Id $guardian.Id -Force }
    if ($guardian) { $guardian.Dispose() }
    Get-Process -Name 'XhsXuanpin.App' -ErrorAction SilentlyContinue | Where-Object {
        try { [string]::Equals($_.Path, $appPath, [System.StringComparison]::OrdinalIgnoreCase) }
        catch { $false }
    } | Stop-Process -Force
    $env:LOCALAPPDATA = $previousLocalAppData
    $resolvedRoot = [System.IO.Path]::GetFullPath($root)
    $resolvedTemp = [System.IO.Path]::GetFullPath($env:TEMP).TrimEnd('\') + '\'
    if ($resolvedRoot.StartsWith($resolvedTemp, [System.StringComparison]::OrdinalIgnoreCase) -and
        [System.IO.Path]::GetFileName($resolvedRoot).StartsWith('xhs-watchdog-test-')) {
        Remove-Item -LiteralPath $resolvedRoot -Recurse -Force
    }
}
