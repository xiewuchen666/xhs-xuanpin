using System.Diagnostics;
using System.Text;
using System.Text.RegularExpressions;

namespace XhsXuanpin.App;

internal sealed class AndroidUi(string adbPath, string serial)
{
    public async Task<bool> IsProductDetailAsync()
    {
        var activities = await RunAsync("shell", "dumpsys", "activity", "activities");
        return IsProductDetailActivity(activities);
    }

    public async Task CopyCurrentProductLinkAsync()
    {
        var page = await DumpAsync();
        if (!page.Contains("package=\"com.xingin.xhs\"", StringComparison.Ordinal))
            throw new InvalidOperationException("当前前台不是小红书");

        var isDetail = await IsProductDetailAsync();
        if (!isDetail && !LooksLikeProductDetail(page))
            throw new InvalidOperationException("当前不是商品详情页，请先打开需要监控的商品");

        var share = FindCenter(page, "分享商品") ?? FindCenter(page, "分享")
            ?? throw new InvalidOperationException("当前商品详情页未识别到分享入口，请重新进入商品详情后重试");
        await TapAsync(share.X, share.Y);
        await Task.Delay(800);

        var sheet = await DumpAsync();
        var copy = FindCenter(sheet, "复制链接")
            ?? throw new InvalidOperationException("分享面板中未识别到“复制链接”，未执行坐标猜测");
        await TapAsync(copy.X, copy.Y);
    }

    internal static bool IsProductDetailActivity(string activities)
    {
        foreach (var line in (activities ?? "").Split('\n'))
        {
            if (!line.Contains("topResumedActivity", StringComparison.OrdinalIgnoreCase) &&
                !line.Contains("mFocusedApp", StringComparison.OrdinalIgnoreCase))
                continue;
            if (!line.Contains("com.xingin.xhs/", StringComparison.OrdinalIgnoreCase))
                return false;
            return line.Contains("goodsdetail", StringComparison.OrdinalIgnoreCase);
        }
        return false;
    }

    internal static bool LooksLikeProductDetail(string document)
    {
        if (string.IsNullOrWhiteSpace(document) ||
            !document.Contains("package=\"com.xingin.xhs\"", StringComparison.Ordinal))
            return false;

        var hasShare = document.Contains("分享商品", StringComparison.Ordinal);
        var hasPurchaseAction = document.Contains("立即购买", StringComparison.Ordinal) ||
                                document.Contains("加入购物车", StringComparison.Ordinal);
        return hasShare && hasPurchaseAction;
    }

    internal static (int X, int Y)? FindCenter(string document, string label)
    {
        foreach (Match node in Regex.Matches(document, @"<node\s+[^>]*>"))
        {
            if (!node.Value.Contains(label, StringComparison.OrdinalIgnoreCase)) continue;
            var bounds = Regex.Match(node.Value, "bounds=\"\\[(\\d+),(\\d+)\\]\\[(\\d+),(\\d+)\\]\"");
            if (bounds.Success)
                return ((int.Parse(bounds.Groups[1].Value) + int.Parse(bounds.Groups[3].Value)) / 2,
                        (int.Parse(bounds.Groups[2].Value) + int.Parse(bounds.Groups[4].Value)) / 2);
        }
        return null;
    }

    private async Task<string> DumpAsync()
    {
        Exception? lastError = null;
        for (var attempt = 0; attempt < 3; attempt++)
        {
            try
            {
                try
                {
                    await RunAsync("shell", "uiautomator", "dump", "/sdcard/xhs-xuanpin.xml");
                }
                catch (InvalidOperationException ex) when (ex.Message.Contains("dumped to: /sdcard/xhs-xuanpin.xml", StringComparison.OrdinalIgnoreCase))
                {
                    // MuMu's uiautomator may return non-zero after confirming the dump was written.
                }
                return await RunAsync("exec-out", "cat", "/sdcard/xhs-xuanpin.xml");
            }
            catch (Exception ex)
            {
                lastError = ex;
                await Task.Delay(500);
            }
        }
        throw new InvalidOperationException("无法读取当前小红书页面：" + lastError?.Message, lastError);
    }

    private async Task TapAsync(int x, int y) => await RunAsync("shell", "input", "tap", x.ToString(), y.ToString());

    private async Task<string> RunAsync(params string[] arguments)
    {
        using var process = new Process
        {
            StartInfo = new ProcessStartInfo(adbPath)
            {
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                StandardOutputEncoding = Encoding.UTF8,
                StandardErrorEncoding = Encoding.UTF8,
                UseShellExecute = false,
                CreateNoWindow = true
            }
        };
        process.StartInfo.ArgumentList.Add("-s");
        process.StartInfo.ArgumentList.Add(serial);
        foreach (var argument in arguments) process.StartInfo.ArgumentList.Add(argument);
        process.Start();
        var output = await process.StandardOutput.ReadToEndAsync();
        var error = await process.StandardError.ReadToEndAsync();
        await process.WaitForExitAsync();
        if (process.ExitCode != 0)
            throw new InvalidOperationException((string.IsNullOrWhiteSpace(error) ? output : error).Trim() is { Length: > 0 } message ? message : "ADB 操作失败");
        return output;
    }
}
