using System.Net.Http;
using System.Net.Http.Json;
using System.Text.RegularExpressions;
using System.Windows;
using System.Windows.Controls.Primitives;
using System.Windows.Interop;
using System.Windows.Threading;

namespace XhsXuanpin.App;

public partial class MainWindow : Window
{
    private static readonly HttpClient Http = new() { BaseAddress = new Uri("http://127.0.0.1:17861") };
    private readonly RuntimeCoordinator _runtime = new();
    private readonly System.Windows.Forms.Panel _phonePanel = new() { BackColor = System.Drawing.Color.FromArgb(36, 36, 36) };
    private readonly DispatcherTimer _pageStateTimer = new() { Interval = TimeSpan.FromSeconds(1) };
    private bool _phoneVisible = true;
    private GridLength _expandedPhoneWidth = new(34, GridUnitType.Star);
    private bool _runtimeReady;
    private bool _monitorBusy;
    private bool _pageStateRefreshInProgress;
    private DateTime _pageMessageHoldUntilUtc;
    private DateTime _lastProductSummaryRefreshUtc = DateTime.MinValue;
    private AndroidProductSummary? _currentProductSummary;
    private bool _windowSizing;

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
        UpdateWindowStateButton();
        Closed += (_, _) =>
        {
            _pageStateTimer.Stop();
            _runtime.Dispose();
        };
    }

    private async void MainWindow_Loaded(object sender, RoutedEventArgs e)
    {
        CurrentTimeText.Text = DateTime.Now.ToString("HH:mm");
        try
        {
            await _runtime.StartAsync(_phonePanel.Handle);
            _runtime.ResizePhone(_phonePanel.ClientSize);
            SetRuntimeHealthy();
            Workspace.Source = new Uri("http://127.0.0.1:17861/");
            FitPhoneSurface();
            _runtimeReady = true;
            _pageStateTimer.Start();
            await RefreshPageStateAsync();
        }
        catch (Exception ex)
        {
            AndroidStatus.Text = "Android · 启动失败";
            GlobalServiceStatus.Text = "采集服务异常";
            GlobalServiceDot.Fill = System.Windows.Media.Brushes.IndianRed;
            BridgeStatus.Text = ex.Message;
            SetProductActionsVisible(false);
        }
    }

    private void SetRuntimeHealthy()
    {
        AndroidStatus.Text = "Android · 已连接";
        GlobalServiceStatus.Text = "采集服务正常";
        GlobalServiceDot.Fill = new System.Windows.Media.SolidColorBrush(System.Windows.Media.Color.FromRgb(0x1F, 0xA6, 0x63));
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
    }

    private void PhoneToggle_Click(object sender, RoutedEventArgs e)
    {
        if (_phoneVisible)
        {
            _expandedPhoneWidth = PhoneColumn.Width;
            _phoneVisible = false;
            PhoneColumn.MinWidth = 0;
            PhoneColumn.Width = new GridLength(0);
            PhoneHost.Visibility = Visibility.Hidden;
            PhoneSplitter.IsEnabled = false;
            GlobalTabsHost.Margin = new Thickness(300, 0, 0, 0);
        }
        else
        {
            _phoneVisible = true;
            PhoneColumn.MinWidth = 400;
            PhoneColumn.MaxWidth = 680;
            PhoneColumn.Width = _expandedPhoneWidth;
            PhoneHost.Visibility = Visibility.Visible;
            PhoneSplitter.IsEnabled = true;
            GlobalTabsHost.Margin = new Thickness(0);
        }

        PhoneToggleLabel.Text = _phoneVisible ? "‹" : "›";
        PhoneToggle.ToolTip = _phoneVisible ? "收起手机预览" : "展开手机预览";
        Dispatcher.InvokeAsync(() =>
        {
            if (_phoneVisible) FitPhoneSurface();
            _runtime.SetPhoneVisible(_phoneVisible);
        }, DispatcherPriority.Loaded);
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

    private void MinimizeButton_Click(object sender, RoutedEventArgs e) =>
        WindowState = WindowState.Minimized;

    private void MaximizeButton_Click(object sender, RoutedEventArgs e)
    {
        WindowState = WindowState == WindowState.Maximized
            ? WindowState.Normal
            : WindowState.Maximized;
    }

    private void CloseButton_Click(object sender, RoutedEventArgs e) => Close();

    private void UpdateWindowStateButton()
    {
        if (MaximizeButton is null) return;
        MaximizeButton.Content = WindowState == WindowState.Maximized ? "❐" : "□";
        MaximizeButton.ToolTip = WindowState == WindowState.Maximized ? "还原" : "最大化";
    }

    private async Task RefreshPageStateAsync()
    {
        if (!_runtimeReady || _monitorBusy || _pageStateRefreshInProgress) return;

        _pageStateRefreshInProgress = true;
        try
        {
            var recovered = await _runtime.EnsureHealthyAsync(_phoneVisible);
            if (recovered)
            {
                FitPhoneSurface();
                SetRuntimeHealthy();
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
                BridgeStatus.Text = "进入商品详情后可一键加入监控或选品中心";
            }
        }
        catch
        {
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
        if (summary is null) return "可直接加入监控或选品中心";
        if (!string.IsNullOrWhiteSpace(summary.Title) && !string.IsNullOrWhiteSpace(summary.PriceText))
            return $"{summary.Title} · {summary.PriceText}";
        if (!string.IsNullOrWhiteSpace(summary.Title)) return summary.Title;
        if (!string.IsNullOrWhiteSpace(summary.PriceText)) return $"当前商品 · {summary.PriceText}";
        return "可直接加入监控或选品中心";
    }

    private void SetProductActionsVisible(bool visible)
    {
        MonitorButton.Visibility = Visibility.Visible;
        SelectionButton.Visibility = Visibility.Visible;
        MonitorButton.IsEnabled = visible && !_monitorBusy;
        SelectionButton.IsEnabled = visible && !_monitorBusy;
    }

    private async void MonitorButton_Click(object sender, RoutedEventArgs e) =>
        await ExecuteCurrentProductActionAsync(addToSelection: false);

    private async void SelectionButton_Click(object sender, RoutedEventArgs e) =>
        await ExecuteCurrentProductActionAsync(addToSelection: true);

    private async Task ExecuteCurrentProductActionAsync(bool addToSelection)
    {
        if (_monitorBusy) return;

        _monitorBusy = true;
        MonitorButton.IsEnabled = false;
        SelectionButton.IsEnabled = false;
        BridgeTitle.Text = addToSelection ? "正在加入选品中心" : "正在加入监控";
        BridgeStatus.Text = "正在取得当前商品分享链接，请勿切换页面";

        try
        {
            if (!await _runtime.IsProductDetailAsync())
                throw new InvalidOperationException("当前不是商品详情页，请先打开需要操作的商品");

            var clipboardSequence = NativeMethods.GetClipboardSequenceNumber();
            await _runtime.CopyCurrentProductLinkAsync();
            var url = await WaitForFreshShareUrlAsync(clipboardSequence);

            BridgeTitle.Text = "正在执行首次真实采集";
            BridgeStatus.Text = url;
            using var collectResponse = await Http.PostAsJsonAsync("/api/products/collect", new { url });
            var result = await collectResponse.Content.ReadFromJsonAsync<CollectResponse>();
            if (!collectResponse.IsSuccessStatusCode || result?.ok != true)
                throw new InvalidOperationException(result?.error ?? "采集失败");

            if (addToSelection)
            {
                using var selectionResponse = await Http.PostAsJsonAsync(
                    $"/api/products/{result.product_id}/selection",
                    new { });
                var selectionResult = await selectionResponse.Content.ReadFromJsonAsync<ActionResponse>();
                if (!selectionResponse.IsSuccessStatusCode || selectionResult?.ok != true)
                    throw new InvalidOperationException(selectionResult?.error ?? "加入选品中心失败");
            }

            BridgeTitle.Text = addToSelection ? "已加入选品中心" : "已加入监控";
            BridgeStatus.Text = addToSelection
                ? "商品已进入持续监控，并加入选品中心"
                : "真实商品已写入独立数据库";
            _pageMessageHoldUntilUtc = DateTime.UtcNow.AddSeconds(3);
            await Workspace.ExecuteScriptAsync("window.dispatchEvent(new Event('xhs-product-collected'))");
        }
        catch (Exception ex)
        {
            BridgeTitle.Text = addToSelection ? "加入选品中心失败" : "加入监控失败";
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

    private sealed record CollectResponse(bool ok, int product_id, string? error);
    private sealed record ActionResponse(bool ok, string? error);
}
