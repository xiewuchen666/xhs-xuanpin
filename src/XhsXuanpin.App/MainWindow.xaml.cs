using System.Net.Http;
using System.Net.Http.Json;
using System.Text.RegularExpressions;
using System.Windows;
using System.Windows.Controls.Primitives;
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

    public MainWindow()
    {
        InitializeComponent();
        PhoneHost.Child = _phonePanel;
        _phonePanel.Resize += (_, _) => _runtime.ResizePhone(_phonePanel.ClientSize);
        PhoneViewport.SizeChanged += (_, _) => FitPhoneSurface();
        SizeChanged += (_, _) => FitPhoneSurface();
        _pageStateTimer.Tick += async (_, _) => await RefreshPageStateAsync();
        Loaded += MainWindow_Loaded;
        Closed += (_, _) =>
        {
            _pageStateTimer.Stop();
            _runtime.Dispose();
        };
    }

    private async void MainWindow_Loaded(object sender, RoutedEventArgs e)
    {
        try
        {
            await _runtime.StartAsync(_phonePanel.Handle);
            _runtime.ResizePhone(_phonePanel.ClientSize);
            AndroidStatus.Text = "Android · 已连接";
            Workspace.Source = new Uri("http://127.0.0.1:17861/");
            FitPhoneSurface();
            _runtimeReady = true;
            _pageStateTimer.Start();
            await RefreshPageStateAsync();
        }
        catch (Exception ex)
        {
            AndroidStatus.Text = "Android · 启动失败";
            BridgeStatus.Text = ex.Message;
            SetProductActionsVisible(false);
        }
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
        }
        else
        {
            _phoneVisible = true;
            PhoneColumn.MinWidth = 400;
            PhoneColumn.MaxWidth = 680;
            PhoneColumn.Width = _expandedPhoneWidth;
            PhoneHost.Visibility = Visibility.Visible;
            PhoneSplitter.IsEnabled = true;
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
                AndroidStatus.Text = "Android · 已连接";
            }

            var isProductDetail = await _runtime.IsProductDetailAsync();
            SetProductActionsVisible(isProductDetail);
            if (DateTime.UtcNow < _pageMessageHoldUntilUtc) return;

            if (isProductDetail)
            {
                BridgeTitle.Text = "当前为商品详情";
                BridgeStatus.Text = "可直接加入监控";
            }
            else
            {
                BridgeTitle.Text = "请在小红书中打开商品详情";
                BridgeStatus.Text = "进入商品详情后可一键采集";
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

    private void SetProductActionsVisible(bool visible)
    {
        var visibility = visible ? Visibility.Visible : Visibility.Collapsed;
        MonitorButton.Visibility = visibility;
        SelectionButton.Visibility = visibility;
        MonitorButton.IsEnabled = visible && !_monitorBusy;
    }

    private async void MonitorButton_Click(object sender, RoutedEventArgs e)
    {
        if (_monitorBusy) return;

        _monitorBusy = true;
        MonitorButton.IsEnabled = false;
        BridgeTitle.Text = "正在取得商品分享链接";
        BridgeStatus.Text = "请勿切换小红书页面";
        try
        {
            if (!await _runtime.IsProductDetailAsync())
                throw new InvalidOperationException("当前不是商品详情页，请先打开需要监控的商品");

            var clipboardSequence = NativeMethods.GetClipboardSequenceNumber();
            await _runtime.CopyCurrentProductLinkAsync();
            var url = await WaitForFreshShareUrlAsync(clipboardSequence);

            BridgeTitle.Text = "正在执行首次真实采集";
            BridgeStatus.Text = url;
            using var response = await Http.PostAsJsonAsync("/api/products/collect", new { url });
            var result = await response.Content.ReadFromJsonAsync<CollectResponse>();
            if (!response.IsSuccessStatusCode || result?.ok != true)
                throw new InvalidOperationException(result?.error ?? "采集失败");

            BridgeTitle.Text = "已加入监控";
            BridgeStatus.Text = "真实商品已写入独立数据库";
            _pageMessageHoldUntilUtc = DateTime.UtcNow.AddSeconds(3);
            await Workspace.ExecuteScriptAsync("window.dispatchEvent(new Event('xhs-product-collected'))");
        }
        catch (Exception ex)
        {
            BridgeTitle.Text = "加入失败";
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

    private sealed record CollectResponse(bool ok, string? error);
}
