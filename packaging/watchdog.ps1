$ErrorActionPreference = 'Stop'
$appPath = Join-Path (Split-Path -Parent $PSScriptRoot) 'XhsXuanpin.App.exe'
$logDirectory = Join-Path $env:LOCALAPPDATA 'XhsXuanpin\data\logs'
$logPath = Join-Path $logDirectory 'watchdog.log'

function Write-WatchdogLog([string]$message) {
    try {
        [System.IO.Directory]::CreateDirectory($logDirectory) | Out-Null
        if ([System.IO.File]::Exists($logPath) -and (Get-Item -LiteralPath $logPath).Length -ge 2MB) {
            $backup = "$logPath.1"
            if ([System.IO.File]::Exists($backup)) { Remove-Item -LiteralPath $backup }
            Move-Item -LiteralPath $logPath -Destination $backup
        }
        [System.IO.File]::AppendAllText(
            $logPath,
            "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss.fff') | WATCHDOG | $message`r`n",
            [System.Text.UTF8Encoding]::new($false))
    } catch {
        # Logging must not interrupt process supervision.
    }
}

function Activate-Workbench {
    try {
        $event = [System.Threading.EventWaitHandle]::OpenExisting('Local\XhsXuanpin.App.Activate')
        try { [void]$event.Set() } finally { $event.Dispose() }
    } catch [System.Threading.WaitHandleCannotBeOpenedException] {
        # The main window has not finished starting yet.
    }
}

function Test-WorkbenchRunning {
    foreach ($candidate in (Get-Process -Name 'XhsXuanpin.App' -ErrorAction SilentlyContinue)) {
        try {
            if ([string]::Equals($candidate.Path, $appPath, [System.StringComparison]::OrdinalIgnoreCase)) {
                return $true
            }
        } catch {
        }
    }
    return $false
}

if (-not [System.IO.File]::Exists($appPath) -or
    -not [System.IO.File]::Exists((Join-Path (Split-Path -Parent $appPath) 'installed.marker'))) {
    Write-WatchdogLog "Installed workbench not found: $appPath"
    exit 1
}

$mutex = [System.Threading.Mutex]::new($false, 'Local\XhsXuanpin.Watchdog')
$ownsMutex = $false
try {
    try { $ownsMutex = $mutex.WaitOne(0) }
    catch [System.Threading.AbandonedMutexException] { $ownsMutex = $true }
    if (-not $ownsMutex) {
        Activate-Workbench
        return
    }

    # A direct EXE launch is outside this watchdog. Do not create a second instance.
    if (Test-WorkbenchRunning) {
        Write-WatchdogLog 'Workbench is already running without this watchdog; activating it'
        Activate-Workbench
        return
    }

    Write-WatchdogLog 'Watchdog started'
    $restartTimes = @()
    while ($true) {
        if (-not [System.IO.File]::Exists($appPath)) {
            Write-WatchdogLog 'Workbench executable is missing; watchdog stopped'
            break
        }
        if (Test-WorkbenchRunning) {
            Write-WatchdogLog 'Another workbench instance started outside the watchdog; watchdog stopped'
            Activate-Workbench
            break
        }

        $runId = [guid]::NewGuid().ToString('N')
        $exitMarker = Join-Path $logDirectory "watchdog-exit-$runId"
        $process = $null
        $exitCode = 'unavailable'
        $startError = $null
        $env:XHS_XUANPIN_WATCHDOG_TOKEN = $runId
        try {
            $process = Start-Process -FilePath $appPath -WorkingDirectory (Split-Path -Parent $appPath) -PassThru
            Write-WatchdogLog "Workbench started; pid=$($process.Id)"
        } catch {
            $startError = $_.Exception.Message
            Write-WatchdogLog "Workbench start failed; pid=none; reason=$startError"
        } finally {
            Remove-Item Env:XHS_XUANPIN_WATCHDOG_TOKEN -ErrorAction SilentlyContinue
        }

        if ($process) {
            $process.WaitForExit()
            $exitCode = $process.ExitCode
            $normalExit = $false
            if ([System.IO.File]::Exists($exitMarker)) {
                try { $normalExit = [System.IO.File]::ReadAllText($exitMarker).Trim() -eq [string]$process.Id }
                catch { Write-WatchdogLog "Could not read exit marker; pid=$($process.Id)" }
            }
            Remove-Item -LiteralPath $exitMarker -ErrorAction SilentlyContinue
            if ($normalExit) {
                Write-WatchdogLog "Workbench exited normally; pid=$($process.Id); exit_code=$exitCode; watchdog stopped"
                $process.Dispose()
                break
            }
            Write-WatchdogLog "Workbench ended unexpectedly; pid=$($process.Id); exit_code=$exitCode; reason=external termination or unknown"
            $process.Dispose()
            if (Test-WorkbenchRunning) {
                Write-WatchdogLog 'Another workbench instance is running; watchdog stopped'
                break
            }
        }

        $now = Get-Date
        $restartTimes = @($restartTimes | Where-Object { $_ -gt $now.AddMinutes(-10) })
        if ($restartTimes.Count -ge 3) {
            Write-WatchdogLog 'Three automatic restarts within ten minutes; watchdog stopped'
            break
        }
        $restartTimes += $now
        Write-WatchdogLog "Restart scheduled; attempt=$($restartTimes.Count)/3"
        Start-Sleep -Seconds 2
    }
} catch {
    Write-WatchdogLog "Watchdog failed; reason=$($_.Exception.Message)"
} finally {
    if ($ownsMutex) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
