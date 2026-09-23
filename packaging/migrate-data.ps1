param(
    [Parameter(Mandatory = $true)][string]$SourceData
)

$ErrorActionPreference = 'Stop'
$source = (Resolve-Path -LiteralPath $SourceData).Path
$target = Join-Path $env:LOCALAPPDATA 'XhsXuanpin\data'
$sourceDb = Join-Path $source 'xhs_xuanpin.db'
$targetDb = Join-Path $target 'xhs_xuanpin.db'
$sourceProfile = Join-Path $source 'browser_profile'
$targetProfile = Join-Path $target 'browser_profile'
$python = Join-Path $env:LOCALAPPDATA 'XhsXuanpin\python-env\Scripts\python.exe'
if ($source -eq $target -or -not (Test-Path -LiteralPath $sourceDb)) { throw '源数据目录无效' }
if (-not (Test-Path -LiteralPath $python)) { throw '请先运行安装器' }
if (Get-Process XhsXuanpin.App -ErrorAction SilentlyContinue) { throw '请先从托盘退出工作台' }
$port = [System.Net.Sockets.TcpClient]::new()
try {
    $port.Connect('127.0.0.1', 17861)
    throw '请先停止本地采集后端'
} catch [System.Net.Sockets.SocketException] {
    # Port is closed; SQLite is no longer in use by the backend.
} finally {
    $port.Dispose()
}

New-Item -ItemType Directory -Path $target -Force | Out-Null
if (Test-Path -LiteralPath $targetDb) {
    $count = & $python -c "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); print(c.execute('SELECT count(*) FROM products').fetchone()[0])" $targetDb
    if ($LASTEXITCODE -ne 0) { throw '目标数据库无法读取' }
    if ([int]$count -ne 0) { throw '目标数据库已有商品，停止迁移以避免覆盖' }
}
if ((Test-Path -LiteralPath $targetProfile) -and (Get-ChildItem -LiteralPath $targetProfile -Force | Select-Object -First 1)) {
    throw '目标浏览器资料已有内容，停止迁移以避免覆盖'
}

$backup = Join-Path $target ('migration-backup-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $backup -Force | Out-Null
if (Test-Path -LiteralPath $targetDb) {
    & $python -c 'import sqlite3,sys; source=sqlite3.connect(sys.argv[1]); target=sqlite3.connect(sys.argv[2]); source.backup(target); source.close(); target.close()' $targetDb (Join-Path $backup 'previous-target.db')
    if ($LASTEXITCODE -ne 0) { throw '目标数据库备份失败' }
}
& $python -c 'import sqlite3,sys; source=sqlite3.connect(sys.argv[1]); target=sqlite3.connect(sys.argv[2]); source.backup(target); source.close(); target.close()' $sourceDb (Join-Path $backup 'source.db')
if ($LASTEXITCODE -ne 0) { throw '源数据库备份失败' }

if (Test-Path -LiteralPath $sourceProfile) {
    New-Item -ItemType Directory -Path $targetProfile -Force | Out-Null
    Get-ChildItem -LiteralPath $sourceProfile -Force | Copy-Item -Destination $targetProfile -Recurse -Force
}
& $python -c 'import sqlite3,sys; source=sqlite3.connect(sys.argv[1]); target=sqlite3.connect(sys.argv[2]); source.backup(target); source.close(); target.close()' (Join-Path $backup 'source.db') $targetDb
if ($LASTEXITCODE -ne 0) { throw '目标数据库迁移失败' }
Write-Host "迁移完成：$target"
Write-Host "数据库备份：$backup"
