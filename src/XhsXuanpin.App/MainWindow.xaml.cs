using System.Diagnostics;
using System.ComponentModel;
using System.IO;
using System.Net.Http;
using System.Net.Http.Json;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using System.Windows;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using System.Windows.Interop;
using System.Windows.Threading;

namespace XhsXuanpin.App;

public partial class MainWindow : Window
{
    private static readonly HttpClient Http = new() { BaseAddress = new Uri("http://127.0.0.1:17861") };
    private readonly RuntimeCoordinator _runtime = new();
    private readonly System.Windows.Forms.Panel _phonePanel = new() { BackColor = System.Drawing.Color.FromArgb(36, 36, 36) };
    private readonly System.Windows.Forms.NotifyIcon _trayIcon;
    private readonly DispatcherTimer _pageStateTimer = new() { Interval = TimeSpan.FromSeconds(1) };
    private NativeMethods.LowLevelMouseProc? _phoneMouseHookProc;
    private IntPtr _phoneMouseHook;
    private bool _phoneKeyboardActive;
    private bool _phoneVisible = true;
    private GridLength _expandedPhoneWidth = new(459, GridUnitType.Pixel);
    private bool _workspaceReady;
    private bool _androidReady;
    private bool _androidInitializationFailed;
    private bool _monitorBusy;
    private bool _globalCollectionToggleBusy;
    private bool _autoCollectionEnabled = true;
    private bool _xhsToggleBusy;
    private bool _mumuControlBusy;
    private bool _xhsInstalled;
    private bool _xhsRunning;
    private bool _xhsLiveSurfaceReady;
    private bool _pageStateRefreshInProgress;
    private DateTime _pageMessageHoldUntilUtc;
    private DateTime _lastProductSummaryRefreshUtc = DateTime.MinValue;
    private DateTime _lastCollectorStatusRefreshUtc = DateTime.MinValue;
    private DateTime _lastXhsAppStateRefreshUtc = DateTime.MinValue;
    private AndroidProductSummary? _currentProductSummary;
    private bool _windowSizing;
    private Task? _androidInitializationTask;
    private string _workspaceView = "single";

    private const int WmNcHitTest = 0x0084;
    private const int WmEnterSizeMove = 0x0231;
    private const int WmExitSizeMove = 0x0232;
    private const int HtLeft = 10;
    private const int HtRight = 11;
    private const int HtTop = 12;
    private const int HtTopLeft = 13;
    private const int HtTopRight = 14;
    private const int HtBottom = 15;
    private const int HtBottomLeft = 16;
    private const int HtBottomRight = 17;

    public MainWindow()
    {
        InitializeComponent();
        var workArea = SystemParameters.WorkArea;
        MinWidth = Math.Min(MinWidth, workArea.Width);
        MinHeight = Math.Min(MinHeight, workArea.Height);
        Width = Math.Min(Width, workArea.Width);
        Height = Math.Min(Height, workArea.Height);
        WindowStartupLocation = WindowStartupLocation.Manual;
        Left = workArea.Left + (workArea.Width - Width) / 2;
        Top = workArea.Top + (workArea.Height - Height) / 2;
        if (workArea.Width < 1180)
        {
            _phoneVisible = false;
            PhoneColumn.MinWidth = 0;
            PhoneColumn.Width = new GridLength(0);
            PhoneSplitter.IsEnabled = false;
            PhoneToggleLabel.Text = "›";
            PhoneToggle.ToolTip = "展开手机预览";
        }
        UpdateCompactHeader();
        _trayIcon = CreateTrayIcon();
        PhoneHost.Child = _phonePanel;
        _phonePanel.Resize += (_, _) =>
        {
            if (!_windowSizing) _runtime.ResizePhone(_phonePanel.ClientSize);
        };
        PhoneViewport.SizeChanged += (_, _) =>
        {
            if (!_windowSizing) FitPhoneSurface();
        };
        SizeChanged += (_, _) =>
        {
            UpdateCompactHeader();
            if (!_windowSizing) FitPhoneSurface();
        };
        StateChanged += (_, _) => UpdateWindowStateButton();
        SourceInitialized += MainWindow_SourceInitialized;
        _pageStateTimer.Tick += async (_, _) =>
        {
            CurrentTimeText.Text = DateTime.Now.ToString("HH:mm");
            await RefreshPageStateAsync();
        };
        Loaded += MainWindow_Loaded;
        Closing += MainWindow_Closing;
        UpdateWindowStateButton();
        UpdateMuMuControlButton();
        Closed += (_, _) =>
        {
            AppLogger.Info("MainWindow", "Main window closed; disposing runtime");
            var icon = _trayIcon.Icon;
            _trayIcon.Visible = false;
            _trayIcon.ContextMenuStrip?.Dispose();
            _trayIcon.Dispose();
            icon?.Dispose();
            _pageStateTimer.Stop();
            RemovePhoneMouseHook();
            _runtime.Dispose();
            Workspace.Dispose();
            PhoneHost.Dispose();
            _phonePanel.Dispose();
        };
    }

    private System.Windows.Forms.NotifyIcon CreateTrayIcon()
    {
        var resource = System.Windows.Application.GetResourceStream(
            new Uri("pack://application:,,,/Assets/logo.ico"))
            ?? throw new InvalidOperationException("未找到应用图标资源");
        using var stream = resource.Stream;
        using var sourceIcon = new System.Drawing.Icon(stream);

        var menu = new System.Windows.Forms.ContextMenuStrip();
        var openItem = menu.Items.Add("打开主界面");
        var exitItem = menu.Items.Add("退出程序");
        var trayIcon = new System.Windows.Forms.NotifyIcon
        {
            ContextMenuStrip = menu,
            Icon = (System.Drawing.Icon)sourceIcon.Clone(),
            Text = "小红书选品工作台",
            Visible = true
        };

        openItem.Click += (_, _) => Dispatcher.BeginInvoke(RestoreFromTray);
        exitItem.Click += (_, _) => Dispatcher.BeginInvoke(
            () => ((App)System.Windows.Application.Current).ExitApplication());
        trayIcon.DoubleClick += (_, _) => Dispatcher.BeginInvoke(RestoreFromTray);
        return trayIcon;
    }

    private void MainWindow_Closing(object? sender, CancelEventArgs e)
    {
        if (((App)System.Windows.Application.Current).IsExiting) return;
        e.Cancel = true;
        HideToTray();
    }

    internal async Task PrepareForExitAsync()
    {
        _pageStateTimer.Stop();
        _runtime.BeginShutdown();
        if (_androidInitializationTask is not null) await _androidInitializationTask;
        await _runtime.StopForExitAsync();
    }

    private void HideToTray()
    {
        ShowInTaskbar = false;
        Hide();
        AppLogger.Info("MainWindow", "Main window hidden to notification area");
    }

    internal void RestoreFromTray()
    {
        if (!Dispatcher.CheckAccess())
        {
            Dispatcher.BeginInvoke(RestoreFromTray);
            return;
        }

        if (!IsVisible) Show();
        ShowInTaskbar = true;
        if (WindowState == WindowState.Minimized)
            WindowState = WindowState.Normal;
        Activate();
        Topmost = true;
        Topmost = false;
        Focus();
        AppLogger.Info("MainWindow", "Main window restored from notification area");
    }

    private async void MainWindow_Loaded(object sender, RoutedEventArgs e)
    {
        AppLogger.Info("MainWindow", "Main window loaded; initializing workspace");
        CurrentTimeText.Text = DateTime.Now.ToString("HH:mm");
        try
        {
            await _runtime.StartBackendAsync();
            if (((App)System.Windows.Application.Current).IsExiting) return;
            SetBackendHealthy();
            var webviewData = Environment.GetEnvironmentVariable("XHS_XUANPIN_DATA_DIR");
            var webviewEnvironment = File.Exists(Path.Combine(AppContext.BaseDirectory, "installed.marker"))
                ? await Microsoft.Web.WebView2.Core.CoreWebView2Environment.CreateAsync(
                    userDataFolder: Path.Combine(webviewData!, "webview2"))
                : null;
            await Workspace.EnsureCoreWebView2Async(webviewEnvironment);
            Workspace.CoreWebView2.NewWindowRequested += Workspace_NewWindowRequested;
            Workspace.CoreWebView2.DownloadStarting += Workspace_DownloadStarting;
            Workspace.CoreWebView2.WebMessageReceived += Workspace_WebMessageReceived;
            NavigateWorkspace("single");
            _workspaceReady = true;
            _pageStateTimer.Start();
            await RefreshPageStateAsync();
            if (((App)System.Windows.Application.Current).IsExiting) return;
            AppLogger.Info("MainWindow", "Workspace initialization completed; starting Android in background");
            _androidInitializationTask = InitializeAndroidInBackgroundAsync();
        }
        catch (Exception ex)
        {
            AppLogger.Error("MainWindow", "Workspace initialization failed", ex);
            _androidInitializationFailed = true;
            AndroidStatus.Text = "Android · 未启动";
            AndroidStatusDot.Fill = System.Windows.Media.Brushes.IndianRed;
            GlobalServiceStatus.Text = "采集服务异常";
            GlobalServiceDot.Fill = System.Windows.Media.Brushes.IndianRed;
            BridgeTitle.Text = "工作台启动失败";
            BridgeStatus.Text = ex.Message;
            SetProductActionsVisible(false);
            UpdateXhsAppToggleButton();
        }
    }

    private async Task InitializeAndroidInBackgroundAsync()
    {
        try
        {
            await _runtime.StartAndroidAsync(_phonePanel.Handle);
            if (_runtime.IsManualMuMuControl) return;
            _runtime.ResizePhone(_phonePanel.ClientSize);
            InstallPhoneMouseHook();
            _xhsInstalled = await _runtime.IsXhsInstalledAsync();
            _androidReady = true;
            _androidInitializationFailed = false;
            AndroidStatus.Text = "Android · 已连接";
            AndroidStatusDot.Fill = new System.Windows.Media.SolidColorBrush(System.Windows.Media.Color.FromRgb(0x00, 0xB4, 0x2A));
            await RefreshXhsAppStateAsync(force: true);
            if (!_xhsInstalled)
            {
                BridgeTitle.Text = "请先安装小红书";
                BridgeStatus.Text = "点击“打开模拟器”完成安装和登录，再返回工作台";
            }
            FitPhoneSurface();
            AppLogger.Info("MainWindow", "Android background initialization completed");
        }
        catch (Exception ex)
        {
            if (((App)System.Windows.Application.Current).IsExiting) return;
            if (_runtime.IsManualMuMuControl)
            {
                ShowManualMuMuStatus("可在模拟器中安装、登录或排查；完成后返回工作台后台运行");
                return;
            }
            AppLogger.Error("MainWindow", "Android background initialization failed; workspace remains available", ex);
            _androidInitializationFailed = true;
            AndroidStatus.Text = "Android · 启动失败";
            AndroidStatusDot.Fill = System.Windows.Media.Brushes.IndianRed;
            BridgeTitle.Text = "Android 暂不可用";
            BridgeStatus.Text = $"右侧监控和后台采集可继续使用；{ex.Message}";
            SetProductActionsVisible(false);
            UpdateXhsAppToggleButton();
        }
    }

    private void SetBackendHealthy()
    {
        GlobalServiceStatus.Text = "采集服务正常";
        GlobalServiceDot.Fill = new System.Windows.Media.SolidColorBrush(System.Windows.Media.Color.FromRgb(0x1F, 0xA6, 0x63));
    }

    private async Task RefreshCollectorStatusAsync()
    {
        try
        {
            var status = await Http.GetFromJsonAsync<RuntimeStatusResponse>("/api/runtime/status");
            if (status is null) return;

            GlobalCollectionIntervalText.Text = $"全局采集 {status.auto_interval_minutes} 分钟";
            _autoCollectionEnabled = status.auto_enabled;
            UpdateGlobalCollectionToggleButton();
            if (status.latest_job?.status == "blocked")
            {
                GlobalCollectionStateText.Text = " · 需人工验证";
                GlobalCollectionStateText.Foreground = System.Windows.Media.Brushes.IndianRed;
            }
            else if (!status.worker_alive)
            {
                GlobalCollectionStateText.Text = " · 服务异常";
                GlobalCollectionStateText.Foreground = System.Windows.Media.Brushes.IndianRed;
            }
            else if (!status.auto_enabled)
            {
                GlobalCollectionStateText.Text = " · 已关闭";
                GlobalCollectionStateText.Foreground = new System.Windows.Media.SolidColorBrush(System.Windows.Media.Color.FromRgb(0x89, 0x89, 0x89));
            }
            else if (status.scheduler_running)
            {
                GlobalCollectionStateText.Text = " · 运行中";
                GlobalCollectionStateText.Foreground = new System.Windows.Media.SolidColorBrush(System.Windows.Media.Color.FromRgb(0x1F, 0xA6, 0x63));
            }
            else
            {
                GlobalCollectionStateText.Text = " · 启动中";
                GlobalCollectionStateText.Foreground = new System.Windows.Media.SolidColorBrush(System.Windows.Media.Color.FromRgb(0xE8, 0x9A, 0x19));
            }

            var nextAuto = status.scheduled?.FirstOrDefault(item => item.id == "auto_collect");
            if (nextAuto is not null && DateTimeOffset.TryParse(nextAuto.next_run_time, out var nextRun))
                GlobalCollectionStateText.ToolTip = $"下次自动采集：{nextRun:MM-dd HH:mm:ss}";
            else
                GlobalCollectionStateText.ToolTip = null;
        }
        catch
        {
            GlobalCollectionStateText.Text = " · 状态未知";
            GlobalCollectionStateText.Foreground = new System.Windows.Media.SolidColorBrush(System.Windows.Media.Color.FromRgb(0xE8, 0x9A, 0x19));
        }
    }

    private void UpdateGlobalCollectionToggleButton()
    {
        if (_globalCollectionToggleBusy)
        {
            GlobalCollectionToggleButton.IsEnabled = false;
            GlobalCollectionToggleButton.Content = "处理中…";
            return;
        }

        GlobalCollectionToggleButton.IsEnabled = true;
        GlobalCollectionToggleButton.Content = _autoCollectionEnabled ? "暂停采集" : "开始采集";
        GlobalCollectionToggleButton.ToolTip = _autoCollectionEnabled
            ? "暂停全局自动采集；不影响手动立即采集"
            : "恢复全局自动采集";
    }

    private async void GlobalCollectionToggleButton_Click(object sender, RoutedEventArgs e)
    {
        if (_globalCollectionToggleBusy)
            return;

        var targetEnabled = !_autoCollectionEnabled;
        _globalCollectionToggleBusy = true;
        UpdateGlobalCollectionToggleButton();

        try
        {
            using var response = await Http.PostAsJsonAsync(
                "/api/settings",
                new { auto_enabled = targetEnabled });
            response.EnsureSuccessStatusCode();

            _autoCollectionEnabled = targetEnabled;
            if (Workspace.CoreWebView2 is not null)
            {
                var checkedValue = targetEnabled ? "true" : "false";
                await Workspace.CoreWebView2.ExecuteScriptAsync(
                    $"(() => {{ const el = document.querySelector('#autoEnabledInput'); if (el) el.checked = {checkedValue}; }})()");
            }

            await RefreshCollectorStatusAsync();
        }
        catch (Exception ex)
        {
            AppLogger.Error("MainWindow", "Global collection toggle failed", ex);
            GlobalCollectionStateText.Text = " · 切换失败";
            GlobalCollectionStateText.Foreground = System.Windows.Media.Brushes.IndianRed;
            GlobalCollectionStateText.ToolTip = ex.Message;
        }
        finally
        {
            _globalCollectionToggleBusy = false;
            UpdateGlobalCollectionToggleButton();
        }
    }

    private async void SettingsButton_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            if (Workspace?.CoreWebView2 is not null)
            {
                await Workspace.CoreWebView2.ExecuteScriptAsync("window.dispatchEvent(new CustomEvent('xhs-open-settings'))");
            }
        }
        catch (Exception ex)
        {
            AppLogger.Error("MainWindow", "Open settings failed", ex);
        }
    }

    private async Task RefreshXhsAppStateAsync(bool force = false)
    {
        if (!force &&
            DateTime.UtcNow - _lastXhsAppStateRefreshUtc < TimeSpan.FromSeconds(2))
            return;

        _xhsRunning = await _runtime.IsXhsRunningAsync();
        if (!_xhsRunning)
        {
            _xhsLiveSurfaceReady = false;
        }
        else if (force)
        {
            _xhsLiveSurfaceReady = await _runtime.WaitForXhsLiveSurfaceStableAsync(
                requiredStableChecks: 2,
                checkIntervalMilliseconds: 250,
                maxChecks: 12);
        }
        else if (!_xhsLiveSurfaceReady)
        {
            _xhsLiveSurfaceReady = await _runtime.WaitForXhsLiveSurfaceStableAsync(requiredStableChecks: 2, checkIntervalMilliseconds: 200, maxChecks: 3);
        }

        _lastXhsAppStateRefreshUtc = DateTime.UtcNow;
        UpdateXhsAppToggleButton();
        UpdatePhoneSurfaceMode();
    }

    private void UpdateXhsAppToggleButton()
    {
        if (_runtime.IsManualMuMuControl)
        {
            XhsAppToggleButton.IsEnabled = false;
            XhsAppToggleButton.Content = "手动操作中";
            XhsAppToggleButton.ToolTip = "完成模拟器操作后，点击“返回工作台后台运行”";
            return;
        }

        if (_mumuControlBusy)
        {
            XhsAppToggleButton.IsEnabled = false;
            XhsAppToggleButton.Content = "处理中…";
            return;
        }

        if (!_androidReady)
        {
            XhsAppToggleButton.IsEnabled = false;
            XhsAppToggleButton.Content = _androidInitializationFailed ? "Android 不可用" : "初始化中…";
            XhsAppToggleButton.ToolTip = _androidInitializationFailed
                ? "Android 初始化失败；右侧监控和后台采集仍可使用"
                : "Android 正在后台初始化；右侧监控和后台采集已可使用";
            return;
        }

        if (_xhsToggleBusy)
        {
            XhsAppToggleButton.IsEnabled = false;
            XhsAppToggleButton.Content = "处理中…";
            return;
        }

        if (!_xhsInstalled)
        {
            XhsAppToggleButton.IsEnabled = false;
            XhsAppToggleButton.Content = "未安装小红书";
            XhsAppToggleButton.ToolTip = "点击旁边的“打开模拟器”完成安装";
            return;
        }

        XhsAppToggleButton.IsEnabled = true;
        XhsAppToggleButton.Content = _xhsRunning ? "关闭小红书" : "启动小红书";
        XhsAppToggleButton.ToolTip = _xhsRunning
            ? "选择仅关闭小红书，或同时关闭模拟器；后台采集继续运行"
            : "唤醒 Android 并启动手机画面和小红书 App";
    }

    private void UpdateMuMuControlButton()
    {
        MuMuControlButton.IsEnabled = !_mumuControlBusy;
        MuMuControlButton.Content = _runtime.IsManualMuMuControl ? "返回工作台后台运行" : "打开模拟器";
        MuMuControlButton.ToolTip = _runtime.IsManualMuMuControl
            ? "完成安装、登录或排查后，重新接入工作台并收起模拟器窗口"
            : "打开 MuMu，安装或登录小红书，也可手动排查模拟器问题";
    }

    private void ShowManualMuMuStatus(string message)
    {
        AndroidStatus.Text = "Android · 手动操作";
        AndroidStatusDot.Fill = System.Windows.Media.Brushes.DarkOrange;
        BridgeTitle.Text = "模拟器由你操作";
        BridgeStatus.Text = message;
        _xhsLiveSurfaceReady = false;
        SetProductActionsVisible(false);
        UpdatePhoneSurfaceMode(layoutChanged: true);
        UpdateXhsAppToggleButton();
        UpdateMuMuControlButton();
    }

    private async void MuMuControlButton_Click(object sender, RoutedEventArgs e)
    {
        if (_mumuControlBusy) return;
        var returning = _runtime.IsManualMuMuControl;
        _mumuControlBusy = true;
        UpdateMuMuControlButton();
        try
        {
            if (!returning)
            {
                var openTask = _runtime.OpenMuMuForManualControlAsync();
                ShowManualMuMuStatus("可在模拟器中安装、登录或排查；完成后返回工作台后台运行");
                await openTask;
                return;
            }

            if (_androidInitializationTask is not null) await _androidInitializationTask;
            _runtime.EndManualMuMuControl();
            AndroidStatus.Text = "Android · 正在连接";
            AndroidStatusDot.Fill = System.Windows.Media.Brushes.DarkOrange;
            await _runtime.StartAndroidAsync(_phonePanel.Handle);
            await _runtime.StartXhsAsync();
            _xhsInstalled = await _runtime.IsXhsInstalledAsync();
            _runtime.ResizePhone(_phonePanel.ClientSize);
            InstallPhoneMouseHook();
            _androidReady = true;
            _androidInitializationFailed = false;
            await RefreshXhsAppStateAsync(force: true);
            if (!_xhsRunning) throw new InvalidOperationException("小红书未能启动，请在模拟器中检查后重试");
            await _runtime.HideMuMuForWorkbenchAsync();
            AndroidStatus.Text = "Android · 已连接";
            AndroidStatusDot.Fill = new System.Windows.Media.SolidColorBrush(System.Windows.Media.Color.FromRgb(0x00, 0xB4, 0x2A));
            BridgeTitle.Text = _xhsLiveSurfaceReady ? "小红书已启动" : "小红书正在启动";
            BridgeStatus.Text = _xhsLiveSurfaceReady
                ? "打开商品详情后可继续加入监控或店铺监控"
                : "等待手机画面稳定后自动显示";
            AppLogger.Info("MainWindow", "MuMu returned to workbench background mode");
        }
        catch (Exception ex)
        {
            if (((App)System.Windows.Application.Current).IsExiting) return;
            AppLogger.Error("MainWindow", "MuMu manual control switch failed", ex);
            if (returning)
            {
                try { await _runtime.OpenMuMuForManualControlAsync(); }
                catch (Exception showError) { AppLogger.Warning("MainWindow", $"MuMu window restore failed: {showError.Message}"); }
            }
            ShowManualMuMuStatus(ex.Message);
        }
        finally
        {
            _mumuControlBusy = false;
            UpdateMuMuControlButton();
            UpdateXhsAppToggleButton();
        }
    }

    private void UpdatePhoneSurfaceMode(bool layoutChanged = false)
    {
        var showLivePhone = _phoneVisible && _xhsRunning && _xhsLiveSurfaceReady;
        var visibility = showLivePhone ? Visibility.Visible : Visibility.Hidden;
        var visibilityChanged = PhoneHost.Visibility != visibility;
        if (!showLivePhone)
            _runtime.SetPhoneVisible(false);

        PhoneHost.Visibility = visibility;
        XhsLaunchPlaceholder.Visibility = _phoneVisible && !showLivePhone
            ? Visibility.Visible
            : Visibility.Hidden;

        var liveSurfaceStarting = _phoneVisible && _xhsRunning && !_xhsLiveSurfaceReady;
        if (!layoutChanged && !visibilityChanged && !liveSurfaceStarting)
        {
            _runtime.SetPhoneVisible(showLivePhone);
            return;
        }

        Dispatcher.BeginInvoke(() =>
        {
            if (_phoneVisible)
                FitPhoneSurface();
            _runtime.SetPhoneVisible(_phoneVisible && _xhsRunning && _xhsLiveSurfaceReady);
        }, DispatcherPriority.Loaded);
    }

    private async void XhsAppToggleButton_Click(object sender, RoutedEventArgs e)
    {
        if (_xhsToggleBusy)
            return;

        _xhsToggleBusy = true;
        UpdateXhsAppToggleButton();

        try
        {
            var closeMuMu = _xhsRunning ? ShowCloseXhsChoice() : null;
            if (_xhsRunning && closeMuMu is null) return;
            _currentProductSummary = null;
            _lastProductSummaryRefreshUtc = DateTime.MinValue;
            SetProductActionsVisible(false);

            if (_xhsRunning)
            {
                _xhsLiveSurfaceReady = false;
                UpdatePhoneSurfaceMode(layoutChanged: true);
                BridgeTitle.Text = "正在关闭小红书";
                BridgeStatus.Text = "正在停止手机画面流；后台监控采集继续运行";
                if (closeMuMu == true) await _runtime.StopXhsAndMuMuAsync();
                else await _runtime.StopXhsAsync();
                _xhsRunning = false;
                _xhsLiveSurfaceReady = false;
                if (closeMuMu == true)
                {
                    AndroidStatus.Text = "Android · 已关闭";
                    AndroidStatusDot.Fill = System.Windows.Media.Brushes.Gray;
                }
                BridgeTitle.Text = "小红书已关闭";
                BridgeStatus.Text = "需要选品时点击左上角“启动小红书”";
            }
            else
            {
                _xhsLiveSurfaceReady = false;
                UpdatePhoneSurfaceMode(layoutChanged: true);
                BridgeTitle.Text = "正在启动小红书";
                BridgeStatus.Text = "启动完成前继续显示占位画面";
                await _runtime.StartXhsAsync();
                AndroidStatus.Text = "Android · 已连接";
                AndroidStatusDot.Fill = new System.Windows.Media.SolidColorBrush(System.Windows.Media.Color.FromRgb(0x00, 0xB4, 0x2A));
                _xhsRunning = await _runtime.IsXhsRunningAsync();
                _xhsLiveSurfaceReady = _xhsRunning &&
                    await _runtime.WaitForXhsLiveSurfaceStableAsync(
                        requiredStableChecks: 3,
                        checkIntervalMilliseconds: 300,
                        maxChecks: 30);

                if (_xhsLiveSurfaceReady)
                {
                    BridgeTitle.Text = "小红书已启动";
                    BridgeStatus.Text = "打开商品详情后可继续加入监控或店铺监控";
                }
                else
                {
                    BridgeTitle.Text = "小红书正在启动";
                    BridgeStatus.Text = "等待 scrcpy 正确读取窗口并稳定后自动切换到实时画面";
                }
            }

            _lastXhsAppStateRefreshUtc = DateTime.UtcNow;
            UpdatePhoneSurfaceMode(layoutChanged: true);
        }
        catch (Exception ex)
        {
            AppLogger.Error("MainWindow", "Xiaohongshu app toggle failed", ex);
            BridgeTitle.Text = "小红书开关操作失败";
            BridgeStatus.Text = ex.Message;
            _lastXhsAppStateRefreshUtc = DateTime.MinValue;
            try
            {
                await RefreshXhsAppStateAsync(force: true);
            }
            catch
            {
            }
        }
        finally
        {
            _xhsToggleBusy = false;
            UpdateXhsAppToggleButton();
        }
    }

    private bool? ShowCloseXhsChoice()
    {
        var dialog = new Window
        {
            Owner = this,
            Title = "关闭小红书",
            Width = 390,
            Height = 165,
            ResizeMode = ResizeMode.NoResize,
            WindowStartupLocation = WindowStartupLocation.CenterOwner,
            ShowInTaskbar = false,
            Background = System.Windows.Media.Brushes.White,
            FontFamily = FontFamily
        };
        var panel = new System.Windows.Controls.StackPanel { Margin = new Thickness(20) };
        panel.Children.Add(new System.Windows.Controls.TextBlock
        {
            Text = "请选择关闭范围；右侧后台采集不受影响。",
            Margin = new Thickness(0, 0, 0, 22),
            FontSize = 13
        });
        var buttons = new System.Windows.Controls.StackPanel
        {
            Orientation = System.Windows.Controls.Orientation.Horizontal,
            HorizontalAlignment = System.Windows.HorizontalAlignment.Right
        };
        var onlyXhs = new System.Windows.Controls.Button { Content = "仅关闭小红书", Padding = new Thickness(12, 6, 12, 6), Margin = new Thickness(0, 0, 8, 0) };
        var withMuMu = new System.Windows.Controls.Button { Content = "同时关闭模拟器", Padding = new Thickness(12, 6, 12, 6) };
        onlyXhs.Click += (_, _) => dialog.DialogResult = false;
        withMuMu.Click += (_, _) => dialog.DialogResult = true;
        buttons.Children.Add(onlyXhs);
        buttons.Children.Add(withMuMu);
        panel.Children.Add(buttons);
        dialog.Content = panel;
        return dialog.ShowDialog();
    }

    private void InstallPhoneMouseHook()
    {
        if (_phoneMouseHook != IntPtr.Zero) return;
        _phoneMouseHookProc = PhoneMouseHookCallback;
        _phoneMouseHook = NativeMethods.SetWindowsHookEx(
            NativeMethods.WhMouseLl,
            _phoneMouseHookProc,
            NativeMethods.GetModuleHandle(null),
            0);
        if (_phoneMouseHook == IntPtr.Zero)
            throw new InvalidOperationException("无法初始化手机输入焦点监听");
    }

    private void RemovePhoneMouseHook()
    {
        if (_phoneMouseHook != IntPtr.Zero)
        {
            NativeMethods.UnhookWindowsHookEx(_phoneMouseHook);
            _phoneMouseHook = IntPtr.Zero;
        }
        _phoneMouseHookProc = null;
    }

    private IntPtr PhoneMouseHookCallback(int code, IntPtr message, IntPtr data)
    {
        if (code >= 0 && message.ToInt32() == NativeMethods.WmLButtonDown)
        {
            var info = System.Runtime.InteropServices.Marshal.PtrToStructure<NativeMethods.MsllHookStruct>(data);
            var insidePhone = _runtime.ContainsPhoneScreenPoint(info.Point.X, info.Point.Y);
            Dispatcher.BeginInvoke(DispatcherPriority.Input, new Action(() =>
            {
                _phoneKeyboardActive = insidePhone && PhoneHost.IsVisible;
                if (_phoneKeyboardActive)
                {
                    PhoneKeyboardSink.Focus();
                    Keyboard.Focus(PhoneKeyboardSink);
                }
            }));
        }

        return NativeMethods.CallNextHookEx(_phoneMouseHook, code, message, data);
    }

    private async void PhoneKeyboardSink_PreviewTextInput(object sender, TextCompositionEventArgs e)
    {
        if (!_phoneKeyboardActive || string.IsNullOrEmpty(e.Text)) return;
        e.Handled = true;
        await _runtime.InjectTextAsync(e.Text);
    }

    private async void PhoneKeyboardSink_PreviewKeyDown(object sender, System.Windows.Input.KeyEventArgs e)
    {
        if (!_phoneKeyboardActive) return;

        if (e.Key == Key.V && Keyboard.Modifiers.HasFlag(ModifierKeys.Control))
        {
            if (System.Windows.Clipboard.ContainsText())
            {
                e.Handled = true;
                await _runtime.InjectTextAsync(System.Windows.Clipboard.GetText());
            }
            return;
        }

        var keyCode = e.Key switch
        {
            Key.Back => "KEYCODE_DEL",
            Key.Delete => "KEYCODE_FORWARD_DEL",
            Key.Enter => "KEYCODE_ENTER",
            Key.Escape => "KEYCODE_BACK",
            Key.Left => "KEYCODE_DPAD_LEFT",
            Key.Right => "KEYCODE_DPAD_RIGHT",
            Key.Up => "KEYCODE_DPAD_UP",
            Key.Down => "KEYCODE_DPAD_DOWN",
            Key.Home => "KEYCODE_MOVE_HOME",
            Key.End => "KEYCODE_MOVE_END",
            Key.Tab => "KEYCODE_TAB",
            _ => null
        };

        if (keyCode is null) return;
        e.Handled = true;
        await _runtime.InjectKeyEventAsync(keyCode);
    }

    private static void Workspace_NewWindowRequested(
        object? sender,
        Microsoft.Web.WebView2.Core.CoreWebView2NewWindowRequestedEventArgs e)
    {
        if (!Uri.TryCreate(e.Uri, UriKind.Absolute, out var uri) ||
            (uri.Scheme != Uri.UriSchemeHttp && uri.Scheme != Uri.UriSchemeHttps))
            return;

        e.Handled = true;
        Process.Start(new ProcessStartInfo(uri.AbsoluteUri)
        {
            UseShellExecute = true
        });
    }

    private void Workspace_DownloadStarting(
        object? sender,
        Microsoft.Web.WebView2.Core.CoreWebView2DownloadStartingEventArgs e)
    {
        var suggestedName = System.IO.Path.GetFileName(e.ResultFilePath);
        if (string.IsNullOrWhiteSpace(suggestedName))
            suggestedName = "小红书选品导出.xlsx";

        var extension = System.IO.Path.GetExtension(suggestedName).ToLowerInvariant();
        var dialog = new Microsoft.Win32.SaveFileDialog
        {
            FileName = suggestedName,
            AddExtension = true,
            DefaultExt = extension,
            Filter = extension switch
            {
                ".csv" => "CSV 文件 (*.csv)|*.csv|所有文件 (*.*)|*.*",
                ".xlsx" => "Excel 工作簿 (*.xlsx)|*.xlsx|所有文件 (*.*)|*.*",
                _ => "所有文件 (*.*)|*.*"
            }
        };

        e.Handled = true;
        if (dialog.ShowDialog(this) == true)
        {
            e.ResultFilePath = dialog.FileName;
            return;
        }

        e.Cancel = true;
    }

    private async void Workspace_WebMessageReceived(
        object? sender,
        Microsoft.Web.WebView2.Core.CoreWebView2WebMessageReceivedEventArgs e)
    {
        WorkspaceMessage? message;
        try
        {
            message = JsonSerializer.Deserialize<WorkspaceMessage>(e.WebMessageAsJson);
        }
        catch (JsonException)
        {
            return;
        }

        if (message?.type != "export")
            return;

        var format = (message.format ?? "").Trim().ToLowerInvariant();
        var module = (message.module ?? "").Trim();
        var detailPeriod = (message.detail_period ?? "").Trim();
        if (format is not ("csv" or "xlsx") ||
            module is not ("single" or "selection" or "shops") ||
            (detailPeriod.Length > 0 && (format != "xlsx" || module == "shops" || detailPeriod is not ("24h" or "7d" or "30d"))))
        {
            PostWorkspaceExportResult(false, "导出参数无效。");
            return;
        }

        var label = module switch
        {
            "shops" => "店铺监控",
            "selection" => "选品中心",
            _ => "单品监控"
        };
        var extension = "." + format;
        var detailLabel = detailPeriod switch { "24h" => "近24小时销量明细", "7d" => "近7天销量明细", "30d" => "近30天销量明细", _ => "" };
        var dialog = new Microsoft.Win32.SaveFileDialog
        {
            FileName = $"{label}-{(detailLabel.Length > 0 ? detailLabel + "-" : "")}{DateTime.Now:yyyyMMdd-HHmmss}{extension}",
            AddExtension = true,
            DefaultExt = extension,
            Filter = format == "csv"
                ? "CSV 文件 (*.csv)|*.csv|所有文件 (*.*)|*.*"
                : "Excel 工作簿 (*.xlsx)|*.xlsx|所有文件 (*.*)|*.*"
        };

        if (dialog.ShowDialog(this) != true)
        {
            PostWorkspaceExportResult(false, "已取消导出。", cancelled: true);
            return;
        }

        try
        {
            var payload = JsonSerializer.Serialize(new
            {
                module,
                format,
                rows = message.rows,
                detail_period = detailPeriod
            });
            using var content = new StringContent(payload, Encoding.UTF8, "application/json");
            using var response = await Http.PostAsync("/api/export", content);
            if (!response.IsSuccessStatusCode)
            {
                var detail = await response.Content.ReadAsStringAsync();
                throw new InvalidOperationException(
                    string.IsNullOrWhiteSpace(detail) ? $"HTTP {(int)response.StatusCode}" : detail);
            }

            var bytes = await response.Content.ReadAsByteArrayAsync();
            await System.IO.File.WriteAllBytesAsync(dialog.FileName, bytes);
            PostWorkspaceExportResult(true, $"已导出到：{dialog.FileName}");
        }
        catch (Exception ex)
        {
            AppLogger.Error("MainWindow", "Export failed", ex);
            PostWorkspaceExportResult(false, $"导出失败：{ex.Message}");
        }
    }

    private void PostWorkspaceExportResult(bool ok, string message, bool cancelled = false)
    {
        if (Workspace.CoreWebView2 is null)
            return;
        var payload = JsonSerializer.Serialize(new
        {
            type = "export-result",
            ok,
            cancelled,
            message
        });
        Workspace.CoreWebView2.PostWebMessageAsJson(payload);
    }

    private void FitPhoneSurface()
    {
        if (!_phoneVisible) return;

        var availableWidth = Math.Max(0, PhoneViewport.ActualWidth);
        var availableHeight = Math.Max(0, PhoneViewport.ActualHeight);
        if (availableWidth <= 0 || availableHeight <= 0) return;

        var width = Math.Min(availableWidth, availableHeight * 9d / 16d);
        var height = width * 16d / 9d;
        PhoneHost.Width = Math.Floor(width);
        PhoneHost.Height = Math.Floor(height);

        // WindowsFormsHost may finish resizing one layout pass after WPF has
        // assigned its final size. Force scrcpy to follow the settled host
        // size on the render queue so it cannot remain at the small startup
        // size in the top-left corner.
        Dispatcher.BeginInvoke(() =>
        {
            if (_phoneVisible)
                _runtime.ResizePhone(_phonePanel.ClientSize);
        }, DispatcherPriority.Render);
    }

    private void PhoneToggle_Click(object sender, RoutedEventArgs e)
    {
        if (_phoneVisible)
        {
            _expandedPhoneWidth = PhoneColumn.Width;
            _phoneVisible = false;
            PhoneColumn.MinWidth = 0;
            PhoneColumn.Width = new GridLength(0);
            PhoneSplitter.IsEnabled = false;
        }
        else
        {
            _phoneVisible = true;
            PhoneColumn.MinWidth = 260;
            PhoneColumn.MaxWidth = 680;
            PhoneColumn.Width = _expandedPhoneWidth;
            PhoneSplitter.IsEnabled = true;
        }

        PhoneToggleLabel.Text = _phoneVisible ? "‹" : "›";
        PhoneToggle.ToolTip = _phoneVisible ? "收起手机预览" : "展开手机预览";
        UpdateCompactHeader();
        Dispatcher.InvokeAsync(() =>
        {
            if (_phoneVisible) FitPhoneSurface();
            UpdatePhoneSurfaceMode(layoutChanged: true);
        }, DispatcherPriority.Loaded);
    }

    private void UpdateCompactHeader()
    {
        var width = ActualWidth > 0 ? ActualWidth : Width;
        var compact = width < 1550;
        ServiceStatusChip.Visibility = compact ? Visibility.Collapsed : Visibility.Visible;
        CollectionIntervalChip.Visibility = compact ? Visibility.Collapsed : Visibility.Visible;
        HeaderDivider.Visibility = compact ? Visibility.Collapsed : Visibility.Visible;
        MessagesButton.Visibility = compact ? Visibility.Collapsed : Visibility.Visible;
        CurrentTimeText.Visibility = compact ? Visibility.Collapsed : Visibility.Visible;
        GlobalCollectionToggleButton.Visibility = width < 900 ? Visibility.Collapsed : Visibility.Visible;
        SettingsButton.Visibility = width < 820 ? Visibility.Collapsed : Visibility.Visible;
        BrandTitle.Visibility = width < 820 ? Visibility.Collapsed : Visibility.Visible;
        BrandVersion.Visibility = width < 820 ? Visibility.Collapsed : Visibility.Visible;
        if (_phoneVisible)
            PhoneColumn.MaxWidth = Math.Min(680, Math.Max(260,
                width - (width < 820 ? 420 : width < 900 ? 480 : 550)));
        GlobalTabsHost.Margin = _phoneVisible ? new Thickness(0) :
            new Thickness(width < 820 ? 52 : 300, 0, 0, 0);
    }

    private void PhoneSplitter_DragCompleted(object sender, DragCompletedEventArgs e)
    {
        if (!_phoneVisible) return;
        _expandedPhoneWidth = PhoneColumn.Width;
        Dispatcher.InvokeAsync(FitPhoneSurface, DispatcherPriority.Loaded);
    }

    private void MainWindow_SourceInitialized(object? sender, EventArgs e)
    {
        if (PresentationSource.FromVisual(this) is not HwndSource source) return;
        source.AddHook(WindowProc);

        var style = NativeMethods.GetWindowLongPtr(source.Handle, NativeMethods.GwlStyle).ToInt64();
        style |= NativeMethods.WsClipChildren | NativeMethods.WsClipSiblings;
        NativeMethods.SetWindowLongPtr(source.Handle, NativeMethods.GwlStyle, new IntPtr(style));
    }

    private IntPtr WindowProc(IntPtr hwnd, int msg, IntPtr wParam, IntPtr lParam, ref bool handled)
    {
        if (msg == WmEnterSizeMove)
        {
            _windowSizing = true;
            return IntPtr.Zero;
        }

        if (msg == WmExitSizeMove)
        {
            _windowSizing = false;
            Dispatcher.BeginInvoke(() =>
            {
                FitPhoneSurface();
                _runtime.ResizePhone(_phonePanel.ClientSize);
            }, DispatcherPriority.Render);
            return IntPtr.Zero;
        }

        if (msg != WmNcHitTest || WindowState == WindowState.Maximized)
            return IntPtr.Zero;

        if (!NativeMethods.GetWindowRect(hwnd, out var rect))
            return IntPtr.Zero;

        var raw = lParam.ToInt64();
        var x = unchecked((short)(raw & 0xFFFF));
        var y = unchecked((short)((raw >> 16) & 0xFFFF));
        var dpi = System.Windows.Media.VisualTreeHelper.GetDpi(this);
        var borderX = Math.Max(6, (int)Math.Ceiling(7 * dpi.DpiScaleX));
        var borderY = Math.Max(6, (int)Math.Ceiling(7 * dpi.DpiScaleY));

        var left = x >= rect.Left && x < rect.Left + borderX;
        var right = x <= rect.Right && x > rect.Right - borderX;
        var top = y >= rect.Top && y < rect.Top + borderY;
        var bottom = y <= rect.Bottom && y > rect.Bottom - borderY;

        var hit = 0;
        if (top && left) hit = HtTopLeft;
        else if (top && right) hit = HtTopRight;
        else if (bottom && left) hit = HtBottomLeft;
        else if (bottom && right) hit = HtBottomRight;
        else if (left) hit = HtLeft;
        else if (right) hit = HtRight;
        else if (top) hit = HtTop;
        else if (bottom) hit = HtBottom;

        if (hit == 0) return IntPtr.Zero;
        handled = true;
        return new IntPtr(hit);
    }

    private void SingleTabButton_Click(object sender, RoutedEventArgs e) =>
        NavigateWorkspace("single");

    private void ShopsTabButton_Click(object sender, RoutedEventArgs e) =>
        NavigateWorkspace("shops");

    private void SelectionTabButton_Click(object sender, RoutedEventArgs e) =>
        NavigateWorkspace("selection");

    private void NavigateWorkspace(string view)
    {
        _workspaceView = view;
        UpdateWorkspaceTabs();
        var uri = new Uri($"http://127.0.0.1:17861/?view={Uri.EscapeDataString(view)}");
        if (Workspace.Source == uri) return;
        Workspace.Source = uri;
    }

    private void UpdateWorkspaceTabs()
    {
        var active = System.Windows.Media.Brushes.Black;
        var inactive = new System.Windows.Media.SolidColorBrush(System.Windows.Media.Color.FromRgb(0x59, 0x59, 0x59));

        SingleTabIndicator.Visibility = _workspaceView == "single" ? Visibility.Visible : Visibility.Collapsed;
        ShopsTabIndicator.Visibility = _workspaceView == "shops" ? Visibility.Visible : Visibility.Collapsed;
        SelectionTabIndicator.Visibility = _workspaceView == "selection" ? Visibility.Visible : Visibility.Collapsed;

        SingleTabText.Foreground = _workspaceView == "single" ? active : inactive;
        ShopsTabText.Foreground = _workspaceView == "shops" ? active : inactive;
        SelectionTabText.Foreground = _workspaceView == "selection" ? active : inactive;

        SingleTabText.FontWeight = _workspaceView == "single" ? FontWeights.SemiBold : FontWeights.Normal;
        ShopsTabText.FontWeight = _workspaceView == "shops" ? FontWeights.SemiBold : FontWeights.Normal;
        SelectionTabText.FontWeight = _workspaceView == "selection" ? FontWeights.SemiBold : FontWeights.Normal;
    }

    private void MinimizeButton_Click(object sender, RoutedEventArgs e) =>
        WindowState = WindowState.Minimized;

    private void MaximizeButton_Click(object sender, RoutedEventArgs e)
    {
        WindowState = WindowState == WindowState.Maximized
            ? WindowState.Normal
            : WindowState.Maximized;
    }

    private void CloseButton_Click(object sender, RoutedEventArgs e) => Close();

    private static readonly System.Windows.Media.Geometry MaximizeGeometry =
        System.Windows.Media.Geometry.Parse("M 0.5,0.5 H 9.5 V 9.5 H 0.5 Z");
    private static readonly System.Windows.Media.Geometry RestoreGeometry =
        System.Windows.Media.Geometry.Parse("M 2.5,0.5 H 9.5 V 7.5 H 7.5 M 0.5,2.5 H 7.5 V 9.5 H 0.5 Z");

    private void UpdateWindowStateButton()
    {
        if (MaximizeButton is null || MaximizeIcon is null) return;
        var isMax = WindowState == WindowState.Maximized;
        MaximizeIcon.Data = isMax ? RestoreGeometry : MaximizeGeometry;
        MaximizeButton.ToolTip = isMax ? "向下还原" : "最大化";
    }

    private async Task RefreshPageStateAsync()
    {
        if (!_workspaceReady || _monitorBusy || _xhsToggleBusy || _pageStateRefreshInProgress) return;

        _pageStateRefreshInProgress = true;
        try
        {
            if (DateTime.UtcNow - _lastCollectorStatusRefreshUtc >= TimeSpan.FromSeconds(5))
            {
                await RefreshCollectorStatusAsync();
                _lastCollectorStatusRefreshUtc = DateTime.UtcNow;
            }

            if (_mumuControlBusy || _runtime.IsManualMuMuControl || !_androidReady) return;

            var recovered = await _runtime.EnsureHealthyAsync(_phoneVisible && _xhsLiveSurfaceReady);
            if (recovered)
            {
                FitPhoneSurface();
                AndroidStatus.Text = "Android · 已连接";
                AndroidStatusDot.Fill = new System.Windows.Media.SolidColorBrush(System.Windows.Media.Color.FromRgb(0x00, 0xB4, 0x2A));
            }

            await RefreshXhsAppStateAsync();
            if (!_xhsRunning)
            {
                SetProductActionsVisible(false);
                _currentProductSummary = null;
                _lastProductSummaryRefreshUtc = DateTime.MinValue;
                if (DateTime.UtcNow >= _pageMessageHoldUntilUtc)
                {
                    BridgeTitle.Text = _xhsInstalled ? "小红书已关闭" : "请先安装小红书";
                    BridgeStatus.Text = _xhsInstalled
                        ? "需要选品时点击左上角“启动小红书”"
                        : "点击“打开模拟器”完成安装和登录，再返回工作台";
                }
                return;
            }

            if (!_xhsLiveSurfaceReady)
            {
                SetProductActionsVisible(false);
                _currentProductSummary = null;
                _lastProductSummaryRefreshUtc = DateTime.MinValue;
                if (DateTime.UtcNow >= _pageMessageHoldUntilUtc)
                {
                    BridgeTitle.Text = "小红书正在启动";
                    BridgeStatus.Text = "等待 scrcpy 窗口信息稳定后自动切换到实时画面";
                }
                return;
            }

            var isProductDetail = await _runtime.IsProductDetailAsync();
            SetProductActionsVisible(isProductDetail);
            if (DateTime.UtcNow < _pageMessageHoldUntilUtc) return;

            if (isProductDetail)
            {
                if (DateTime.UtcNow - _lastProductSummaryRefreshUtc >= TimeSpan.FromSeconds(3))
                {
                    _currentProductSummary = await _runtime.GetCurrentProductSummaryAsync();
                    _lastProductSummaryRefreshUtc = DateTime.UtcNow;
                }

                BridgeTitle.Text = "已识别商品详情页";
                BridgeStatus.Text = FormatProductSummary(_currentProductSummary);
            }
            else
            {
                _currentProductSummary = null;
                _lastProductSummaryRefreshUtc = DateTime.MinValue;
                BridgeTitle.Text = "请在小红书中打开商品详情";
                BridgeStatus.Text = "进入商品详情后可一键加入监控或店铺监控";
            }
        }
        catch (Exception ex)
        {
            AppLogger.Warning("MainWindow", $"Android page state refresh failed; workspace remains available: {ex.Message}");
            AndroidStatus.Text = "Android · 连接异常";
            AndroidStatusDot.Fill = System.Windows.Media.Brushes.IndianRed;
            SetProductActionsVisible(false);
            BridgeTitle.Text = "正在识别小红书页面";
            BridgeStatus.Text = "页面状态暂不可用，请稍后重试";
        }
        finally
        {
            _pageStateRefreshInProgress = false;
        }
    }

    private static string FormatProductSummary(AndroidProductSummary? summary)
    {
        if (summary is null) return "可直接加入监控或店铺监控";
        if (!string.IsNullOrWhiteSpace(summary.Title) && !string.IsNullOrWhiteSpace(summary.PriceText))
            return $"{summary.Title} · {summary.PriceText}";
        if (!string.IsNullOrWhiteSpace(summary.Title)) return summary.Title;
        if (!string.IsNullOrWhiteSpace(summary.PriceText)) return $"当前商品 · {summary.PriceText}";
        return "可直接加入监控或店铺监控";
    }

    private void SetProductActionsVisible(bool visible)
    {
        MonitorButton.Visibility = Visibility.Visible;
        ShopMonitorButton.Visibility = Visibility.Visible;
        MonitorButton.IsEnabled = visible && !_monitorBusy;
        ShopMonitorButton.IsEnabled = visible && !_monitorBusy;
    }

    private async void MonitorButton_Click(object sender, RoutedEventArgs e) =>
        await ExecuteCurrentProductActionAsync(addToShopMonitor: false);

    private async void ShopMonitorButton_Click(object sender, RoutedEventArgs e) =>
        await ExecuteCurrentProductActionAsync(addToShopMonitor: true);

    private async Task ExecuteCurrentProductActionAsync(bool addToShopMonitor)
    {
        if (_monitorBusy) return;

        _monitorBusy = true;
        MonitorButton.IsEnabled = false;
        ShopMonitorButton.IsEnabled = false;
        BridgeTitle.Text = addToShopMonitor ? "正在加入店铺监控" : "正在加入监控";
        BridgeStatus.Text = "正在读取当前商品，请勿切换页面";

        try
        {
            if (!await _runtime.IsProductDetailAsync())
                throw new InvalidOperationException("当前不是商品详情页，请先打开需要操作的商品");

            var url = await _runtime.GetCurrentProductUrlAsync();
            if (url is null)
            {
                AppLogger.Warning("MainWindow", "Current product URL unavailable; using share fallback");
                BridgeStatus.Text = "正在通过分享页取得商品链接，请勿切换页面";
                var clipboardSequence = NativeMethods.GetClipboardSequenceNumber();
                await _runtime.CopyCurrentProductLinkAsync();
                url = await WaitForFreshShareUrlAsync(clipboardSequence);
            }
            else
            {
                AppLogger.Info("MainWindow", "Current product URL read from Android activity");
            }

            var scope = addToShopMonitor ? "shop" : "single";
            BridgeTitle.Text = "正在提交后台采集";
            BridgeStatus.Text = "取得链接成功，即将返回商品浏览";
            using var importResponse = await Http.PostAsJsonAsync(
                "/api/products/import",
                new { text = url, scope });
            var result = await importResponse.Content.ReadFromJsonAsync<ImportResponse>();
            if (!importResponse.IsSuccessStatusCode || result?.ok != true || !result.queued)
                throw new InvalidOperationException(result?.error ?? "采集失败");

            BridgeTitle.Text = addToShopMonitor ? "店铺监控任务已提交" : "监控任务已提交";
            BridgeStatus.Text = $"后台任务 #{result.job_id} 正在采集，可以继续浏览下一个商品";
            _pageMessageHoldUntilUtc = DateTime.UtcNow.AddSeconds(3);
            await Workspace.ExecuteScriptAsync(
                $"window.dispatchEvent(new CustomEvent('xhs-import-queued', {{ detail: {{ jobId: {result.job_id} }} }}))");
        }
        catch (Exception ex)
        {
            AppLogger.Error(
                "MainWindow",
                addToShopMonitor ? "Add-to-shop-monitor action failed" : "Add-to-monitor action failed",
                ex);
            BridgeTitle.Text = addToShopMonitor ? "加入店铺监控失败" : "加入监控失败";
            BridgeStatus.Text = ex.Message;
            _pageMessageHoldUntilUtc = DateTime.UtcNow.AddSeconds(3);
        }
        finally
        {
            _monitorBusy = false;
            await RefreshPageStateAsync();
        }
    }

    private static async Task<string> WaitForFreshShareUrlAsync(uint initialClipboardSequence)
    {
        for (var i = 0; i < 24; i++)
        {
            if (NativeMethods.GetClipboardSequenceNumber() != initialClipboardSequence)
            {
                var text = System.Windows.Clipboard.ContainsText() ? System.Windows.Clipboard.GetText() : "";
                if (TryExtractShareUrl(text, out var url))
                    return url;
            }
            await Task.Delay(250);
        }

        throw new InvalidOperationException("未取得本次复制产生的小红书分享链接，请确认 MuMu 剪贴板同步已开启后重试");
    }

    internal static bool TryExtractShareUrl(string text, out string url)
    {
        url = "";
        foreach (Match match in Regex.Matches(text ?? "", @"https?://[^\s]+", RegexOptions.IgnoreCase))
        {
            var candidate = match.Value.TrimEnd('，', '。', ',', '.', '；', ';', '！', '!', '）', ')');
            if (!Uri.TryCreate(candidate, UriKind.Absolute, out var uri)) continue;
            if (!IsXhsHost(uri.Host)) continue;
            url = uri.AbsoluteUri;
            return true;
        }
        return false;
    }

    private static bool IsXhsHost(string host) =>
        host.Equals("xhslink.com", StringComparison.OrdinalIgnoreCase) ||
        host.EndsWith(".xhslink.com", StringComparison.OrdinalIgnoreCase) ||
        host.Equals("xiaohongshu.com", StringComparison.OrdinalIgnoreCase) ||
        host.EndsWith(".xiaohongshu.com", StringComparison.OrdinalIgnoreCase);

    private sealed record WorkspaceMessage(string? type, string? module, string? format, JsonElement rows, string? detail_period);
    private sealed record ImportResponse(bool ok, int job_id, bool queued, int count, string? error);
    private sealed record ActionResponse(bool ok, string? error);
    private sealed record ScheduledJobResponse(string id, string? next_run_time);
    private sealed record LatestJobResponse(int id, string status);
    private sealed record RuntimeStatusResponse(
        bool ok,
        bool auto_enabled,
        int auto_interval_minutes,
        bool midnight_enabled,
        bool worker_alive,
        bool scheduler_running,
        List<ScheduledJobResponse>? scheduled,
        LatestJobResponse? latest_job);
}
