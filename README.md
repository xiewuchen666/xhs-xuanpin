# 小红书选品工作台

Windows x64 人工选品工作台。左侧接入 MuMu 中的小红书 App，右侧提供单品监控、店铺监控和选品中心。商品数据保存在本机 SQLite，采集服务仅监听本机地址。

## 下载安装

从本仓库的 [Releases](https://github.com/xiewuchen666/xhs-xuanpin/releases) 下载 `XhsXuanpin-Setup-win-x64.exe`。安装器会检查并按需安装 WebView2、Python 3.12、Google Chrome 和 MuMu；MuMu 的官方安装窗口可能需要手动操作。首次使用时，请自行在模拟器中安装小红书 App 并登录。工作台不保存账号密码，也不处理验证码或安全验证。

Windows x64 安装包使用自包含 .NET 8 发布，目标电脑无需预装 .NET Desktop Runtime。退出工作台请使用托盘菜单中的“退出程序”；窗口右上角关闭只会收起到托盘。

## 主要功能

- 浏览小红书商品详情并加入单品监控或选品中心。
- 定时采集商品数据，查看销量趋势与异常原因。
- 按商品或店铺筛选、排序，并导出汇总及采集明细。
- 按需关闭小红书或模拟器；允许打开模拟器进行人工安装、登录和排查。
- 安装版在工作台异常退出后有限次数地重启；托盘主动退出不会重启。

## 源码结构

| 路径 | 内容 |
| --- | --- |
| `src/XhsXuanpin.App/` | .NET 8 WPF 工作台、MuMu／ADB／scrcpy 接入与进程生命周期 |
| `backend/` | Python Flask 本地 API、Playwright 采集、SQLite、指标计算、任务调度和导出 |
| `web/` | WebView2 内的监控与选品界面 |
| `packaging/` | Inno Setup 安装器、依赖安装和工作台守护脚本 |
| `design/` | 已确认的设计约定、原型和静态验收图 |

产品范围见 [prd.md](prd.md)，技术方案见 [TECHNICAL.md](TECHNICAL.md)，当前发布状态与已知边界见 [CURRENT_TASK.md](CURRENT_TASK.md)。

## 从源码构建与检查

开发环境需要 Windows、.NET 8 SDK、Python 3.12、Chrome、WebView2 Runtime、MuMu 和 scrcpy。

```powershell
dotnet build XhsXuanpin.sln --configuration Release
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
.\.venv\Scripts\python.exe -m unittest discover -s backend\tests -p "test_*.py"
node --check web\app.js
```

安装包构建使用 `packaging/build.ps1`，还需要 Inno Setup 7 和 scrcpy 4.1。当前脚本按本项目的已验证环境读取 `%LOCALAPPDATA%\Programs\Inno Setup 7\ISCC.exe` 与 `D:\Programs\scrcpy`；在其他电脑打包前，需要调整这两个本机路径。安装包不包含开发用 `.venv` 或本机用户数据；这些目录也被 `.gitignore` 排除。

## 数据与限制

安装版的用户数据、浏览器资料和日志位于 `%LOCALAPPDATA%\XhsXuanpin\data`。工作台依赖本机持续运行，并受小红书页面变化、登录状态和平台安全验证影响；不会绕过这些验证。已知验收边界记录在 [CURRENT_TASK.md](CURRENT_TASK.md)。

这是非官方项目，与小红书平台没有隶属关系。
