$ErrorActionPreference = 'Stop'
$source = Split-Path -Parent $PSScriptRoot
$artifactRoot = Join-Path (Join-Path (Split-Path -Parent $source) 'xhs-xuanpin-release') 'artifacts'
New-Item -ItemType Directory -Path $artifactRoot -Force | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$stage = Join-Path $artifactRoot "stage-$stamp"
$buildBin = Join-Path $artifactRoot "build-bin-$stamp"
$compiler = Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 7\ISCC.exe'
$scrcpy = 'D:\Programs\scrcpy'
if (-not (Test-Path -LiteralPath $compiler)) { throw '未找到 Inno Setup 7 编译器' }
if (-not (Test-Path -LiteralPath (Join-Path $scrcpy 'scrcpy.exe'))) { throw '未找到已验证的 scrcpy 4.1 目录' }

dotnet publish (Join-Path $source 'src\XhsXuanpin.App\XhsXuanpin.App.csproj') -c Release -r win-x64 --self-contained true -o $stage "-p:BaseOutputPath=$buildBin\"
if ($LASTEXITCODE -ne 0) { throw 'WPF 发布失败' }

New-Item -ItemType Directory -Path (Join-Path $stage 'backend'), (Join-Path $stage 'web'), (Join-Path $stage 'scrcpy'), (Join-Path $stage 'setup') -Force | Out-Null
Get-ChildItem -LiteralPath (Join-Path $source 'backend') -File | Copy-Item -Destination (Join-Path $stage 'backend')
Get-ChildItem -LiteralPath (Join-Path $source 'web') -File | Copy-Item -Destination (Join-Path $stage 'web')
Get-ChildItem -LiteralPath $scrcpy -File | Copy-Item -Destination (Join-Path $stage 'scrcpy')
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'install-deps.ps1') -Destination (Join-Path $stage 'setup')
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'migrate-data.ps1') -Destination (Join-Path $stage 'setup')
New-Item -ItemType File -Path (Join-Path $stage 'installed.marker') | Out-Null

& $compiler "/DStageDir=$stage" "/DSourceDir=$source" "/DArtifactDir=$artifactRoot" (Join-Path $PSScriptRoot 'installer.iss')
if ($LASTEXITCODE -ne 0) { throw '安装器编译失败' }
Write-Host (Join-Path $artifactRoot 'XhsXuanpin-Setup-win-x64.exe')
