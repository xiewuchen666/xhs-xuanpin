$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$compiler = Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 7\ISCC.exe'
$root = Join-Path $env:TEMP ('xhs-installer-check-' + [guid]::NewGuid().ToString('N'))
$stage = Join-Path $root 'stage'

New-Item -ItemType Directory -Path (Join-Path $stage 'setup'), (Join-Path $stage 'backend') -Force | Out-Null
try {
    Set-Content -LiteralPath (Join-Path $stage 'installed.marker') -Value 'installed'
    Set-Content -LiteralPath (Join-Path $stage 'backend\requirements.txt') -Value 'fake-package==1.0'
    @'
param([switch]$CheckOnly, [string]$Step, [string]$InstallerPath, [string]$RequirementsPath, [string]$StartupReportPath)
Add-Content -LiteralPath $env:XHS_TEST_LOG -Value "$Step|$CheckOnly"
if ($env:XHS_TEST_MODE -eq 'fail' -and $Step -eq 'Python' -and $CheckOnly) { exit 1 }
if ($env:XHS_TEST_MODE -eq 'startup_fail' -and $Step -eq 'MuMuStartup') {
    Set-Content -LiteralPath $StartupReportPath -Value 'Service: MuMuRemoteService' -Encoding Ascii
    exit 1
}
exit 0
'@ | Set-Content -LiteralPath (Join-Path $stage 'setup\install-deps.ps1')

    $iss = Get-Content -LiteralPath (Join-Path $repo 'packaging\installer.iss') -Raw
    $iss = $iss -replace '(?m)^AppId=.*$', 'AppId={{D57FD7BB-5B66-4E7E-9BB8-3B1B6E47F0AB}'
    $iss = $iss -replace '(?m)^AppName=.*$', 'AppName=Xhs Installer Regression Probe'
    $iss = $iss -replace '(?m)^DefaultGroupName=.*$', 'DefaultGroupName=Xhs Installer Regression Probe'
    $iss = $iss -replace '(?m)^CloseApplications=.*$', ('CloseApplications=no' + [Environment]::NewLine + 'CreateUninstallRegKey=no' + [Environment]::NewLine + 'Uninstallable=no')
    $iss = $iss -replace '(?ms)^\[Icons\]\r?\n.*?(?=^\[Tasks\])', ('[Icons]' + [Environment]::NewLine)
    $iss = $iss -replace '(?ms)^\[Tasks\]\r?\n.*?(?=^\[Code\])', ('[Tasks]' + [Environment]::NewLine)
    $iss = $iss.Replace('https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe', 'http://127.0.0.1:1/python.exe')
    $issPath = Join-Path $root 'probe.iss'
    Set-Content -LiteralPath $issPath -Value $iss -Encoding UTF8
    & $compiler "/DStageDir=$stage" "/DSourceDir=$repo" "/DArtifactDir=$root" $issPath | Select-Object -Last 3
    if ($LASTEXITCODE -ne 0) { throw 'Probe installer compile failed' }
    $exe = Join-Path $root 'XhsXuanpin-Setup-win-x64.exe'

    $env:XHS_TEST_LOG = Join-Path $root 'failure-steps.log'
    $env:XHS_TEST_MODE = 'fail'
    $failApp = Join-Path $root 'fail-app'
    $p = Start-Process -FilePath $exe -ArgumentList @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/NOICONS', ('/DIR="' + $failApp + '"'), ('/LOG="' + (Join-Path $root 'failure.log') + '"')) -WindowStyle Hidden -Wait -PassThru
    $failSteps = @(Get-Content -LiteralPath $env:XHS_TEST_LOG)
    if ($p.ExitCode -eq 0 -or (Test-Path -LiteralPath (Join-Path $failApp 'installed.marker')) -or ($failSteps -match '^Chrome')) {
        throw "Failure path did not stop before copying the app. Exit=$($p.ExitCode), Steps=$($failSteps -join ',')"
    }
    Write-Host "Failure path passed: exit=$($p.ExitCode), app not copied"

    $env:XHS_TEST_LOG = Join-Path $root 'success-steps.log'
    $env:XHS_TEST_MODE = 'success'
    $successApp = Join-Path $root 'success-app'
    $p = Start-Process -FilePath $exe -ArgumentList @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/NOICONS', ('/DIR="' + $successApp + '"'), ('/LOG="' + (Join-Path $root 'success.log') + '"')) -WindowStyle Hidden -Wait -PassThru
    $successSteps = @(Get-Content -LiteralPath $env:XHS_TEST_LOG)
    if ($p.ExitCode -ne 0 -or -not (Test-Path -LiteralPath (Join-Path $successApp 'installed.marker')) -or -not ($successSteps -match '^MuMuStartup\|False$') -or -not ($successSteps -match '^PythonPackages')) {
        throw "Success path did not finish. Exit=$($p.ExitCode), Steps=$($successSteps -join ',')"
    }
    Write-Host "Success path passed: exit=$($p.ExitCode), app copied"

    $env:XHS_TEST_LOG = Join-Path $root 'startup-failure-steps.log'
    $env:XHS_TEST_MODE = 'startup_fail'
    $startupApp = Join-Path $root 'startup-failure-app'
    $p = Start-Process -FilePath $exe -ArgumentList @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/NOICONS', ('/DIR="' + $startupApp + '"'), ('/LOG="' + (Join-Path $root 'startup-failure.log') + '"')) -WindowStyle Hidden -Wait -PassThru
    $startupSteps = @(Get-Content -LiteralPath $env:XHS_TEST_LOG)
    if ($p.ExitCode -ne 0 -or -not (Test-Path -LiteralPath (Join-Path $startupApp 'installed.marker')) -or
        -not ($startupSteps -match '^MuMuStartup\|False$') -or
        [array]::IndexOf($startupSteps, 'MuMuStartup|False') -lt [array]::IndexOf($startupSteps, 'PythonPackages|False')) {
        throw "MuMu startup failure blocked app installation. Exit=$($p.ExitCode), Steps=$($startupSteps -join ',')"
    }
    Write-Host "MuMu startup failure path passed: exit=$($p.ExitCode), app copied"
} finally {
    Remove-Item Env:\XHS_TEST_LOG, Env:\XHS_TEST_MODE -ErrorAction SilentlyContinue
    $resolvedRoot = [System.IO.Path]::GetFullPath($root)
    $resolvedTemp = [System.IO.Path]::GetFullPath($env:TEMP).TrimEnd('\') + '\'
    if (-not $resolvedRoot.StartsWith($resolvedTemp, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw 'Unsafe temporary cleanup path'
    }
    if (Test-Path -LiteralPath $resolvedRoot) { Remove-Item -LiteralPath $resolvedRoot -Recurse -Force }
}
