param(
    [switch]$CheckOnly,
    [ValidateSet('All', 'WebView2', 'Python', 'Chrome', 'MuMu', 'PythonPackages')]
    [string]$Step = 'All',
    [string]$InstallerPath
)

$ErrorActionPreference = 'Stop'
$appDir = Split-Path -Parent $PSScriptRoot
$userRoot = Join-Path $env:LOCALAPPDATA 'XhsXuanpin'
$pythonEnv = Join-Path $userRoot 'python-env'
$downloadDir = Join-Path $env:TEMP 'XhsXuanpin-Setup'
$logDir = Join-Path $userRoot 'data\logs'
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
Start-Transcript -Path (Join-Path $logDir 'setup.log') -Append | Out-Null

function Get-MuMuDirectory {
    foreach ($root in @('HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall', 'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall', 'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall')) {
        foreach ($key in (Get-ChildItem -LiteralPath $root -ErrorAction SilentlyContinue)) {
            $item = Get-ItemProperty -LiteralPath $key.PSPath -ErrorAction SilentlyContinue
            if ($item.DisplayName -notlike '*MuMu*') { continue }
            foreach ($value in @($item.InstallLocation, $item.UninstallString, $item.DisplayIcon)) {
                if (-not $value) { continue }
                $path = [regex]::Match($value, '^(?:"([^"]+)"|(.+?\.(?:exe|ico))|(.+))').Groups
                $candidate = @($path[1].Value, $path[2].Value, $path[3].Value) | Where-Object { $_ } | Select-Object -First 1
                if (Test-Path -LiteralPath $candidate -PathType Leaf) { $candidate = Split-Path -Parent $candidate }
                for ($i = 0; $i -lt 3 -and $candidate; $i++) {
                    if ((Test-Path -LiteralPath (Join-Path $candidate 'nx_main\adb.exe')) -and
                        (Test-Path -LiteralPath (Join-Path $candidate 'nx_main\MuMuManager.exe'))) {
                        return $candidate
                    }
                    $candidate = Split-Path -Parent $candidate
                }
            }
        }
    }
    foreach ($process in (Get-Process -Name 'MuMuNxMain', 'MuMuNxDevice', 'MuMuManager' -ErrorAction SilentlyContinue)) {
        if (-not $process.Path) { continue }
        $candidate = Split-Path -Parent $process.Path
        for ($i = 0; $i -lt 5 -and $candidate; $i++) {
            if ((Test-Path -LiteralPath (Join-Path $candidate 'nx_main\adb.exe')) -and
                (Test-Path -LiteralPath (Join-Path $candidate 'nx_main\MuMuManager.exe'))) {
                return $candidate
            }
            $candidate = Split-Path -Parent $candidate
        }
    }
    return $null
}

function Get-Python312 {
    foreach ($path in @((Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'), (Join-Path $env:ProgramFiles 'Python312\python.exe'))) {
        if (Test-Path -LiteralPath $path) {
            & $path -c 'import sys; assert sys.version_info[:2] == (3, 12)' 2>$null
            if ($LASTEXITCODE -eq 0) { return $path }
        }
    }
    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($launcher) {
        $path = & $launcher.Source -3.12 -c 'import sys; print(sys.executable)' 2>$null
        if ($LASTEXITCODE -eq 0 -and (Test-Path -LiteralPath $path)) { return $path }
    }
    return $null
}

function Test-WebView2 {
    $id = '{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}'
    foreach ($root in @("HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\$id", "HKCU:\SOFTWARE\Microsoft\EdgeUpdate\Clients\$id")) {
        $version = (Get-ItemProperty -LiteralPath $root -Name pv -ErrorAction SilentlyContinue).pv
        if ($version -and $version -ne '0.0.0.0') { return $true }
    }
    return $false
}

function Get-Chrome {
    foreach ($path in @((Join-Path $env:ProgramW6432 'Google\Chrome\Application\chrome.exe'), (Join-Path ${env:ProgramFiles(x86)} 'Google\Chrome\Application\chrome.exe'), (Join-Path $env:LOCALAPPDATA 'Google\Chrome\Application\chrome.exe'))) {
        if (Test-Path -LiteralPath $path) { return $path }
    }
    return $null
}

function Get-OfficialInstaller($url, $fileName, $publisher) {
    if ($InstallerPath) {
        $path = (Resolve-Path -LiteralPath $InstallerPath).Path
    } else {
        New-Item -ItemType Directory -Path $downloadDir -Force | Out-Null
        $path = Join-Path $downloadDir $fileName
        Invoke-WebRequest -Uri $url -OutFile $path
    }
    $signature = Get-AuthenticodeSignature -LiteralPath $path
    if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notlike "*$publisher*") {
        throw "安装包签名验证失败：$fileName"
    }
    return $path
}

function Run-Installer($file, $arguments, [switch]$Elevate) {
    $options = @{ FilePath = $file; Wait = $true; PassThru = $true }
    if ($arguments) { $options.ArgumentList = $arguments }
    if ($Elevate -and -not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        $options.Verb = 'RunAs'
    }
    $process = Start-Process @options
    if ($process.ExitCode -ne 0) { throw "依赖安装失败：$(Split-Path $file -Leaf)，退出码 $($process.ExitCode)" }
}

function Install-MuMu($file) {
    $installer = Start-Process -FilePath $file -PassThru
    $deadline = (Get-Date).AddMinutes(30)
    do {
        $directory = Get-MuMuDirectory
        if ($directory) { return $directory }
        if ($installer.HasExited -and $installer.ExitCode -ne 0) {
            throw "MuMu 安装程序退出码 $($installer.ExitCode)"
        }
        Start-Sleep -Seconds 2
    } while ((Get-Date) -lt $deadline)
    throw '30 分钟内未检测到可用的 MuMu，请查看安装状态后重新运行安装器'
}

try {
    if (-not [Environment]::Is64BitOperatingSystem) { throw '只支持 Windows x64' }
    if (-not (Test-Path -LiteralPath (Join-Path $appDir 'backend\requirements.txt'))) { throw '缺少后端依赖清单' }

    if (($Step -eq 'All' -or $Step -eq 'WebView2') -and -not (Test-WebView2)) {
        if ($CheckOnly) { throw '缺少 WebView2 Runtime' }
        $file = Get-OfficialInstaller 'https://go.microsoft.com/fwlink/p/?LinkId=2124703' 'WebView2Setup.exe' 'Microsoft Corporation'
        Run-Installer $file '/silent /install'
        if (-not (Test-WebView2)) { throw 'WebView2 安装后仍未检测到' }
    }

    if (($Step -eq 'All' -or $Step -eq 'Python') -and -not (Get-Python312)) {
        if ($CheckOnly) { throw '缺少 Python 3.12' }
        $file = Get-OfficialInstaller 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe' 'Python-3.12.10-amd64.exe' 'Python Software Foundation'
        Run-Installer $file '/quiet InstallAllUsers=0 PrependPath=0 Include_launcher=1 Include_test=0'
        if (-not (Get-Python312)) { throw 'Python 3.12 安装后仍未检测到' }
    }

    if (($Step -eq 'All' -or $Step -eq 'Chrome') -and -not (Get-Chrome)) {
        if ($CheckOnly) { throw '缺少 Google Chrome' }
        $file = Get-OfficialInstaller 'https://dl.google.com/dl/chrome/install/googlechromestandaloneenterprise64.msi' 'GoogleChromeEnterprise64.msi' 'Google LLC'
        Run-Installer 'msiexec.exe' "/i `"$file`" /qn /norestart" -Elevate
        if (-not (Get-Chrome)) { throw 'Chrome 安装后仍未检测到' }
    }

    if (($Step -eq 'All' -or $Step -eq 'MuMu') -and -not (Get-MuMuDirectory)) {
        if ($CheckOnly) { throw '缺少 MuMu 模拟器' }
        $file = Get-OfficialInstaller 'https://mumu.nie.netease.com/api/dl/win?channel=gw-win' 'MuMuSetup.exe' 'NetEase (Hangzhou) Network Co., Ltd'
        $directory = Install-MuMu $file
        Write-Host "MuMu 已就绪：$directory"
    }

    if ($Step -eq 'All' -or $Step -eq 'PythonPackages') {
        $envPython = Join-Path $pythonEnv 'Scripts\python.exe'
        if (-not (Test-Path -LiteralPath $envPython)) {
            if ($CheckOnly) { throw '缺少工作台 Python 环境' }
            $python = Get-Python312
            if (-not $python) { throw '请先安装 Python 3.12' }
            New-Item -ItemType Directory -Path $userRoot -Force | Out-Null
            & $python -m venv $pythonEnv
            if ($LASTEXITCODE -ne 0) { throw '创建 Python 环境失败' }
        }
        if (-not $CheckOnly) {
            & $envPython -m pip install --disable-pip-version-check -r (Join-Path $appDir 'backend\requirements.txt')
            if ($LASTEXITCODE -ne 0) { throw '安装 Python 依赖失败' }
        }
        & $envPython -c 'import flask, apscheduler, playwright, openpyxl'
        if ($LASTEXITCODE -ne 0) { throw 'Python 依赖验证失败' }
    }
    Write-Host "$Step 检查通过"
} catch {
    Write-Host "依赖安装失败：$_"
    exit 1
} finally {
    Stop-Transcript | Out-Null
}
