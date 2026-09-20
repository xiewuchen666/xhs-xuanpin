using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Net.Http;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.RegularExpressions;

namespace XhsXuanpin.App;

internal sealed class RuntimeCoordinator : IDisposable
{
    private const string Serial = "emulator-5554";
    private const string WindowTitle = "XhsXuanpinPhone";
    private const int TargetAndroidDensity = 480;
    private readonly string _root = FindProjectRoot();
    private readonly string _adb = @"D:\Program Files\Netease\MuMu\nx_main\adb.exe";
    private Process? _python;
    private Process? _scrcpy;
    private IntPtr _scrcpyWindow;
    private IntPtr _phoneHost;
    private AndroidUi? _androidUi;
    private bool _started;
    private bool _ownsPython;
    private bool _ownsScrcpy;
    private bool _scrcpySuspended;
    private IntPtr _scrcpyJob;
    private readonly SemaphoreSlim _scrcpyLifecycleLock = new(1, 1);
    private readonly SemaphoreSlim _androidInputLock = new(1, 1);
    private DateTime _lastScrcpyRecoveryAttemptUtc;

    public async Task StartAsync(IntPtr phoneHost)
    {
        AppLogger.Info("Runtime", "Runtime startup requested");
        if (phoneHost == IntPtr.Zero) throw new InvalidOperationException("手机宿主窗口尚未创建");
        _phoneHost = phoneHost;

        if (_started)
        {
            AttachScrcpyWindow();
            return;
        }

        await EnsurePythonServiceAsync();
        await EnsureAndroidAsync();
        _androidUi = new AndroidUi(_adb, Serial);
        await EnsureScrcpyAsync();
        HideMuMuWindows();
        _started = true;
        AppLogger.Info("Runtime", "Runtime startup completed");
    }

    public Task<bool> IsProductDetailAsync() =>
        _androidUi?.IsProductDetailAsync() ?? Task.FromResult(false);

    public Task<AndroidProductSummary?> GetCurrentProductSummaryAsync() =>
        _androidUi?.GetCurrentProductSummaryAsync() ?? Task.FromResult<AndroidProductSummary?>(null);

    public Task CopyCurrentProductLinkAsync() =>
        _androidUi?.CopyCurrentProductLinkAsync() ?? throw new InvalidOperationException("Android 尚未连接");

    public async Task InjectTextAsync(string text)
    {
        if (string.IsNullOrEmpty(text)) return;
        await _androidInputLock.WaitAsync();
        try
        {
            await RunAsync(_adb, "-s", Serial, "shell", "input", "text", text.Replace(" ", "%s"));
        }
        finally
        {
            _androidInputLock.Release();
        }
    }

    public async Task InjectKeyEventAsync(string keyCode)
    {
        if (string.IsNullOrWhiteSpace(keyCode)) return;
        await _androidInputLock.WaitAsync();
        try
        {
            await RunAsync(_adb, "-s", Serial, "shell", "input", "keyevent", keyCode);
        }
        finally
        {
            _androidInputLock.Release();
        }
    }

    public async Task<bool> EnsureHealthyAsync(bool phoneVisible)
    {
        if (!_started || _scrcpySuspended || IsScrcpyHealthy()) return false;
        if (!await _scrcpyLifecycleLock.WaitAsync(0)) return false;

        try
        {
            if (_scrcpySuspended || IsScrcpyHealthy()) return false;
            if (DateTime.UtcNow - _lastScrcpyRecoveryAttemptUtc < TimeSpan.FromSeconds(3)) return false;
            _lastScrcpyRecoveryAttemptUtc = DateTime.UtcNow;

            AppLogger.Warning("Runtime", "scrcpy health check failed; starting recovery");
            ResetScrcpyState(terminateRunningProcess: true);
            if (!await AdbReadyAsync()) throw new InvalidOperationException("Android 连接已断开");

            await RunAsync(_adb, "-s", Serial, "shell", "input", "keyevent", "KEYCODE_WAKEUP");
            await EnsureScrcpyAsync();
            SetPhoneVisible(phoneVisible);
            AppLogger.Info("Runtime", "scrcpy recovery completed");
            return true;
        }
        finally
        {
            _scrcpyLifecycleLock.Release();
        }
    }

    public void ResizePhone(Size size)
    {
        if (_scrcpyWindow == IntPtr.Zero || size.Width <= 0 || size.Height <= 0) return;
        NativeMethods.MoveWindow(_scrcpyWindow, 0, 0, size.Width, size.Height, true);
    }

    public void SetPhoneVisible(bool visible)
    {
        if (_scrcpyWindow == IntPtr.Zero) return;
        if (visible) ResizePhoneToHost(throwOnFailure: false);
        NativeMethods.ShowWindow(_scrcpyWindow, visible ? NativeMethods.SwShow : NativeMethods.SwHide);
    }

    public bool ContainsPhoneScreenPoint(int x, int y)
    {
        if (_scrcpyWindow == IntPtr.Zero || !NativeMethods.IsWindow(_scrcpyWindow))
            return false;
        return NativeMethods.GetWindowRect(_scrcpyWindow, out var rect) &&
               x >= rect.Left && x < rect.Right &&
               y >= rect.Top && y < rect.Bottom;
    }

    private async Task EnsurePythonServiceAsync()
    {
        if (await IsServiceReadyAsync())
        {
            AppLogger.Info("Runtime", "Backend service already healthy");
            return;
        }

        var python = Path.Combine(_root, ".venv", "Scripts", "python.exe");
        var server = Path.Combine(_root, "backend", "server.py");
        if (!File.Exists(python)) throw new InvalidOperationException("未找到项目 Python 3.12 虚拟环境");

        var startInfo = new ProcessStartInfo(python)
        {
            WorkingDirectory = Path.Combine(_root, "backend"),
            UseShellExecute = false,
            CreateNoWindow = true
        };
        startInfo.ArgumentList.Add(server);
        startInfo.ArgumentList.Add("--port");
        startInfo.ArgumentList.Add("17861");
        _python = Process.Start(startInfo) ?? throw new InvalidOperationException("Python 本地服务启动失败");
        _ownsPython = true;
        AppLogger.Info("Runtime", $"Backend service process started; pid={_python.Id}");

        await WaitForServiceAsync();
        AppLogger.Info("Runtime", "Backend service health check passed");
    }

    private static async Task<bool> IsServiceReadyAsync()
    {
        using var client = new HttpClient { Timeout = TimeSpan.FromMilliseconds(800) };
        try
        {
            using var response = await client.GetAsync("http://127.0.0.1:17861/health");
            return response.IsSuccessStatusCode;
        }
        catch (HttpRequestException)
        {
            return false;
        }
        catch (TaskCanceledException)
        {
            return false;
        }
    }

    private async Task WaitForServiceAsync()
    {
        for (var i = 0; i < 40; i++)
        {
            if (await IsServiceReadyAsync()) return;
            if (_python is { HasExited: true })
                throw new InvalidOperationException($"Python 本地服务启动失败，退出码 {_python.ExitCode}");
            await Task.Delay(250);
        }
        throw new InvalidOperationException("Python 本地服务未能启动");
    }

    private async Task EnsureAndroidAsync()
    {
        if (!File.Exists(_adb)) throw new InvalidOperationException("未找到 MuMu ADB");
        if (!await AdbReadyAsync())
        {
            AppLogger.Warning("Runtime", "Android ADB is not ready; launching MuMu player");
            var manager = @"D:\Program Files\Netease\MuMu\nx_main\MuMuManager.exe";
            Process.Start(new ProcessStartInfo(manager, "api launch_player 0") { UseShellExecute = false, CreateNoWindow = true });
            for (var i = 0; i < 120 && !await AdbReadyAsync(); i++) await Task.Delay(1000);
        }
        if (!await AdbReadyAsync()) throw new InvalidOperationException("MuMu Android 未在 120 秒内连接");
        await RunAsync(_adb, "-s", Serial, "shell", "input", "keyevent", "KEYCODE_WAKEUP");
        await EnsureReadableDensityAsync();
    }

    public async Task<bool> IsXhsRunningAsync()
    {
        if (!await AdbReadyAsync()) return false;
        try
        {
            var output = await RunAsync(_adb, "-s", Serial, "shell", "pidof", "com.xingin.xhs");
            return !string.IsNullOrWhiteSpace(output);
        }
        catch (InvalidOperationException)
        {
            return false;
        }
    }

    public async Task<bool> IsXhsForegroundAsync()
    {
        if (!await AdbReadyAsync()) return false;
        try
        {
            var output = await RunAsync(_adb, "-s", Serial, "shell", "dumpsys", "activity", "activities");
            return output
                .Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries)
                .Any(line =>
                    line.Contains("topResumedActivity=", StringComparison.Ordinal) &&
                    line.Contains("com.xingin.xhs/", StringComparison.Ordinal));
        }
        catch (InvalidOperationException)
        {
            return false;
        }
    }

    public async Task<bool> WaitForXhsLiveSurfaceStableAsync(
        int requiredStableChecks = 3,
        int checkIntervalMilliseconds = 300,
        int maxChecks = 30)
    {
        var stableChecks = 0;
        var lastWidth = -1;
        var lastHeight = -1;
        var lastHostWidth = -1;
        var lastHostHeight = -1;

        for (var i = 0; i < maxChecks; i++)
        {
            var foregroundReady = await IsXhsForegroundAsync();
            var surfaceReady = TryGetScrcpySurfaceSnapshot(
                out var width,
                out var height,
                out var hostWidth,
                out var hostHeight);

            if (foregroundReady && surfaceReady)
            {
                var sameAsPrevious =
                    width == lastWidth &&
                    height == lastHeight &&
                    hostWidth == lastHostWidth &&
                    hostHeight == lastHostHeight;

                stableChecks = sameAsPrevious ? stableChecks + 1 : 1;
                lastWidth = width;
                lastHeight = height;
                lastHostWidth = hostWidth;
                lastHostHeight = hostHeight;

                if (stableChecks >= requiredStableChecks)
                    return true;
            }
            else
            {
                stableChecks = 0;
                lastWidth = lastHeight = lastHostWidth = lastHostHeight = -1;
            }

            await Task.Delay(checkIntervalMilliseconds);
        }

        return false;
    }

    private bool TryGetScrcpySurfaceSnapshot(
        out int width,
        out int height,
        out int hostWidth,
        out int hostHeight)
    {
        width = height = hostWidth = hostHeight = 0;

        try
        {
            if (_scrcpy is null || _scrcpy.HasExited ||
                _scrcpyWindow == IntPtr.Zero || !NativeMethods.IsWindow(_scrcpyWindow) ||
                _phoneHost == IntPtr.Zero || !NativeMethods.IsWindow(_phoneHost))
                return false;

            if (NativeMethods.GetParent(_scrcpyWindow) != _phoneHost)
                return false;

            if (!NativeMethods.GetClientRect(_scrcpyWindow, out var scrcpyRect) ||
                !NativeMethods.GetClientRect(_phoneHost, out var hostRect))
                return false;

            width = scrcpyRect.Width;
            height = scrcpyRect.Height;
            hostWidth = hostRect.Width;
            hostHeight = hostRect.Height;

            if (width <= 0 || height <= 0 || hostWidth <= 0 || hostHeight <= 0)
                return false;

            var widthTolerance = Math.Max(4, (int)Math.Ceiling(hostWidth * 0.01));
            var heightTolerance = Math.Max(4, (int)Math.Ceiling(hostHeight * 0.01));

            return Math.Abs(width - hostWidth) <= widthTolerance &&
                   Math.Abs(height - hostHeight) <= heightTolerance;
        }
        catch (InvalidOperationException)
        {
            return false;
        }
    }

    public async Task StopXhsAsync()
    {
        await _scrcpyLifecycleLock.WaitAsync();
        _scrcpySuspended = true;
        try
        {
            if (!await AdbReadyAsync()) throw new InvalidOperationException("Android 连接已断开");
            AppLogger.Info("Runtime", "Stopping Xiaohongshu app and suspending phone stream");
            await RunAsync(_adb, "-s", Serial, "shell", "am", "force-stop", "com.xingin.xhs");
            for (var i = 0; i < 20; i++)
            {
                if (!await IsXhsRunningAsync())
                {
                    AppLogger.Info("Runtime", "Xiaohongshu app stopped");
                    return;
                }
                await Task.Delay(100);
            }
            throw new InvalidOperationException("小红书未能在预期时间内停止");
        }
        finally
        {
            ResetScrcpyState(terminateRunningProcess: true);
            if (await AdbReadyAsync())
            {
                try
                {
                    await RunAsync(_adb, "-s", Serial, "shell", "input", "keyevent", "KEYCODE_SLEEP");
                }
                catch (Exception ex)
                {
                    AppLogger.Warning("Runtime", $"Android screen sleep failed: {ex.Message}");
                }
            }
            AppLogger.Info("Runtime", "Phone stream suspended; MuMu and ADB remain available");
            _scrcpyLifecycleLock.Release();
        }
    }

    public async Task StartXhsAsync()
    {
        await _scrcpyLifecycleLock.WaitAsync();
        try
        {
            if (!await AdbReadyAsync()) throw new InvalidOperationException("Android 连接已断开");
            AppLogger.Info("Runtime", "Starting phone stream and Xiaohongshu app");
            await RunAsync(_adb, "-s", Serial, "shell", "input", "keyevent", "KEYCODE_WAKEUP");
            await EnsureScrcpyAsync();
            await RunAsync(_adb, "-s", Serial, "shell", "monkey", "-p", "com.xingin.xhs", "1");
            for (var i = 0; i < 30; i++)
            {
                if (await IsXhsRunningAsync())
                {
                    _scrcpySuspended = false;
                    AppLogger.Info("Runtime", "Xiaohongshu app process and phone stream started");
                    return;
                }
                await Task.Delay(100);
            }
            throw new InvalidOperationException("小红书未能在预期时间内启动");
        }
        catch
        {
            _scrcpySuspended = true;
            ResetScrcpyState(terminateRunningProcess: true);
            if (await AdbReadyAsync())
            {
                try
                {
                    await RunAsync(_adb, "-s", Serial, "shell", "input", "keyevent", "KEYCODE_SLEEP");
                }
                catch (Exception ex)
                {
                    AppLogger.Warning("Runtime", $"Android screen sleep after failed start failed: {ex.Message}");
                }
            }
            throw;
        }
        finally
        {
            _scrcpyLifecycleLock.Release();
        }
    }

    private async Task EnsureReadableDensityAsync()
    {
        try
        {
            var density = await RunAsync(_adb, "-s", Serial, "shell", "wm", "density");
            var overrideMatch = Regex.Match(density, @"Override density:\s*(\d+)", RegexOptions.IgnoreCase);
            var physicalMatch = Regex.Match(density, @"Physical density:\s*(\d+)", RegexOptions.IgnoreCase);
            var effectiveDensity = overrideMatch.Success
                ? int.Parse(overrideMatch.Groups[1].Value)
                : physicalMatch.Success ? int.Parse(physicalMatch.Groups[1].Value) : TargetAndroidDensity;

            if (effectiveDensity < TargetAndroidDensity)
            {
                await RunAsync(_adb, "-s", Serial, "shell", "wm", "density", TargetAndroidDensity.ToString());
                await Task.Delay(800);
            }
        }
        catch
        {
            // Density tuning improves readability but must not prevent Android startup.
        }
    }

    private async Task<bool> AdbReadyAsync()
    {
        try
        {
            return (await RunAsync(_adb, "-s", Serial, "get-state")).Trim() == "device";
        }
        catch
        {
            return false;
        }
    }

    private async Task EnsureScrcpyAsync()
    {
        if (IsScrcpyHealthy())
        {
            AttachScrcpyWindow();
            AppLogger.Info("Runtime", "Existing scrcpy window is healthy and attached");
            return;
        }

        if (_scrcpy is not null || _scrcpyWindow != IntPtr.Zero)
            ResetScrcpyState(terminateRunningProcess: true);

        var path = @"D:\Programs\scrcpy\scrcpy.exe";
        if (!File.Exists(path)) throw new InvalidOperationException("未找到 scrcpy");

        var startInfo = new ProcessStartInfo(path)
        {
            UseShellExecute = false,
            CreateNoWindow = true
        };
        foreach (var argument in new[]
        {
            "--serial", Serial,
            "--window-title", WindowTitle,
            "--window-borderless",
            "--no-audio",
            "--keyboard=disabled",
            "--video-bit-rate", "20M",
            "--render-driver", "software",
            "--window-x", "-32000",
            "--window-y", "-32000"
        })
        {
            startInfo.ArgumentList.Add(argument);
        }

        _scrcpy = Process.Start(startInfo) ?? throw new InvalidOperationException("scrcpy 启动失败");
        _ownsScrcpy = true;
        try
        {
            EnsureScrcpyJob();
            if (!NativeMethods.AssignProcessToJobObject(_scrcpyJob, _scrcpy.Handle))
                throw new InvalidOperationException($"scrcpy 进程托管失败，Win32 错误 {Marshal.GetLastPInvokeError()}");
        }
        catch
        {
            ResetScrcpyState(terminateRunningProcess: true);
            throw;
        }
        AppLogger.Info("Runtime", $"scrcpy process started; pid={_scrcpy.Id}");
        for (var i = 0; i < 80 && _scrcpyWindow == IntPtr.Zero; i++)
        {
            if (_scrcpy.HasExited)
                throw new InvalidOperationException($"scrcpy 启动失败，退出码 {_scrcpy.ExitCode}");
            await Task.Delay(100);
            _scrcpyWindow = FindScrcpyWindow(_scrcpy.Id);
        }

        if (_scrcpyWindow == IntPtr.Zero)
            throw new InvalidOperationException($"未找到本次 scrcpy 进程({_scrcpy.Id})的窗口");

        AttachScrcpyWindow();
        AppLogger.Info("Runtime", $"scrcpy window attached; hwnd={_scrcpyWindow}");
    }

    private bool IsScrcpyHealthy()
    {
        if (_scrcpy is null || _scrcpyWindow == IntPtr.Zero || !NativeMethods.IsWindow(_scrcpyWindow))
            return false;

        try
        {
            if (_scrcpy.HasExited) return false;
        }
        catch (InvalidOperationException)
        {
            return false;
        }

        return _phoneHost != IntPtr.Zero &&
               NativeMethods.IsWindow(_phoneHost) &&
               NativeMethods.GetParent(_scrcpyWindow) == _phoneHost;
    }

    private void EnsureScrcpyJob()
    {
        if (_scrcpyJob != IntPtr.Zero) return;

        _scrcpyJob = NativeMethods.CreateJobObject(IntPtr.Zero, null);
        if (_scrcpyJob == IntPtr.Zero)
            throw new InvalidOperationException($"无法创建 scrcpy 进程托管，Win32 错误 {Marshal.GetLastPInvokeError()}");

        var limits = new NativeMethods.JobObjectExtendedLimitInformation
        {
            BasicLimitInformation = new NativeMethods.JobObjectBasicLimitInformation
            {
                LimitFlags = NativeMethods.JobObjectLimitKillOnJobClose
            }
        };
        if (!NativeMethods.SetInformationJobObject(
                _scrcpyJob,
                NativeMethods.JobObjectExtendedLimitInformationClass,
                ref limits,
                (uint)Marshal.SizeOf<NativeMethods.JobObjectExtendedLimitInformation>()))
        {
            var error = Marshal.GetLastPInvokeError();
            NativeMethods.CloseHandle(_scrcpyJob);
            _scrcpyJob = IntPtr.Zero;
            throw new InvalidOperationException($"无法配置 scrcpy 进程托管，Win32 错误 {error}");
        }
    }

    private void ResetScrcpyState(bool terminateRunningProcess)
    {
        var process = _scrcpy;
        var ownsProcess = _ownsScrcpy;
        _scrcpy = null;
        _scrcpyWindow = IntPtr.Zero;
        _ownsScrcpy = false;

        if (process is null) return;

        try
        {
            if (terminateRunningProcess && ownsProcess && !process.HasExited)
                process.Kill(true);
        }
        catch (InvalidOperationException)
        {
        }
        catch (System.ComponentModel.Win32Exception)
        {
        }
        finally
        {
            process.Dispose();
        }
    }

    private void AttachScrcpyWindow()
    {
        if (_scrcpyWindow == IntPtr.Zero || !NativeMethods.IsWindow(_scrcpyWindow))
            throw new InvalidOperationException("scrcpy 窗口句柄无效");
        if (_phoneHost == IntPtr.Zero || !NativeMethods.IsWindow(_phoneHost))
            throw new InvalidOperationException("手机宿主窗口句柄无效");

        var style = NativeMethods.GetWindowLongPtr(_scrcpyWindow, NativeMethods.GwlStyle).ToInt64();
        style = (style & ~NativeMethods.WsPopup & ~NativeMethods.WsCaption & ~NativeMethods.WsThickFrame) | NativeMethods.WsChild;
        NativeMethods.SetWindowLongPtr(_scrcpyWindow, NativeMethods.GwlStyle, new IntPtr(style));

        Marshal.SetLastPInvokeError(0);
        NativeMethods.SetParent(_scrcpyWindow, _phoneHost);
        var parentError = Marshal.GetLastPInvokeError();
        if (NativeMethods.GetParent(_scrcpyWindow) != _phoneHost)
            throw new InvalidOperationException($"scrcpy 嵌入失败，Win32 错误 {parentError}");

        ResizePhoneToHost(throwOnFailure: true);
        NativeMethods.ShowWindow(_scrcpyWindow, NativeMethods.SwShow);

        if (!NativeMethods.GetClientRect(_scrcpyWindow, out var rect) || rect.Width <= 0 || rect.Height <= 0)
            throw new InvalidOperationException("scrcpy 已嵌入但尺寸无效");
    }

    private void ResizePhoneToHost(bool throwOnFailure)
    {
        if (_scrcpyWindow == IntPtr.Zero || _phoneHost == IntPtr.Zero) return;
        if (!NativeMethods.GetClientRect(_phoneHost, out var hostRect) || hostRect.Width <= 0 || hostRect.Height <= 0)
        {
            if (throwOnFailure) throw new InvalidOperationException("手机宿主区域尺寸尚未就绪");
            return;
        }

        var moved = NativeMethods.MoveWindow(_scrcpyWindow, 0, 0, hostRect.Width, hostRect.Height, true);
        if (!moved && throwOnFailure)
            throw new InvalidOperationException($"无法调整 scrcpy 子窗口尺寸，Win32 错误 {Marshal.GetLastPInvokeError()}");
    }

    private static IntPtr FindScrcpyWindow(int processId)
    {
        IntPtr result = IntPtr.Zero;
        NativeMethods.EnumWindows((window, _) =>
        {
            NativeMethods.GetWindowThreadProcessId(window, out var pid);
            if (pid != processId) return true;

            var length = NativeMethods.GetWindowTextLength(window);
            if (length <= 0) return true;
            var title = new StringBuilder(length + 1);
            NativeMethods.GetWindowText(window, title, title.Capacity);
            if (!title.ToString().Equals(WindowTitle, StringComparison.Ordinal)) return true;

            result = window;
            return false;
        }, IntPtr.Zero);
        return result;
    }

    private static async Task<string> RunAsync(string file, params string[] arguments)
    {
        using var process = new Process
        {
            StartInfo = new ProcessStartInfo(file)
            {
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                UseShellExecute = false,
                CreateNoWindow = true
            }
        };
        foreach (var argument in arguments) process.StartInfo.ArgumentList.Add(argument);
        process.Start();
        var outputTask = process.StandardOutput.ReadToEndAsync();
        var errorTask = process.StandardError.ReadToEndAsync();
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        try
        {
            await process.WaitForExitAsync(timeout.Token);
        }
        catch (OperationCanceledException)
        {
            if (!process.HasExited)
                process.Kill(true);
            await Task.WhenAll(outputTask, errorTask);
            throw new TimeoutException("ADB 命令执行超时，请检查模拟器连接");
        }

        var output = await outputTask;
        var error = await errorTask;
        if (process.ExitCode != 0)
            throw new InvalidOperationException(string.IsNullOrWhiteSpace(error) ? output.Trim() : error.Trim());
        return output;
    }

    private static void HideMuMuWindows()
    {
        NativeMethods.EnumWindows((window, _) =>
        {
            NativeMethods.GetWindowThreadProcessId(window, out var pid);
            try
            {
                using var process = Process.GetProcessById((int)pid);
                if (process.ProcessName.StartsWith("MuMu", StringComparison.OrdinalIgnoreCase))
                    NativeMethods.ShowWindow(window, NativeMethods.SwHide);
            }
            catch (ArgumentException)
            {
            }
            return true;
        }, IntPtr.Zero);
    }

    private static string FindProjectRoot()
    {
        for (var directory = new DirectoryInfo(AppContext.BaseDirectory); directory is not null; directory = directory.Parent)
            if (File.Exists(Path.Combine(directory.FullName, "backend", "server.py")))
                return directory.FullName;
        throw new InvalidOperationException("未找到项目根目录");
    }

    public void Dispose()
    {
        AppLogger.Info("Runtime", "Runtime disposal started");
        ResetScrcpyState(terminateRunningProcess: true);
        if (_scrcpyJob != IntPtr.Zero)
        {
            NativeMethods.CloseHandle(_scrcpyJob);
            _scrcpyJob = IntPtr.Zero;
        }
        if (_ownsPython && _python is { HasExited: false }) _python.Kill(true);
        _python?.Dispose();
        AppLogger.Info("Runtime", "Runtime disposal completed");
    }
}

internal static class NativeMethods
{
    internal const uint JobObjectLimitKillOnJobClose = 0x00002000;
    internal const int JobObjectExtendedLimitInformationClass = 9;
    internal const int GwlStyle = -16, SwHide = 0, SwShow = 5;
    internal const int WhMouseLl = 14;
    internal const int WmLButtonDown = 0x0201, WmRButtonDown = 0x0204, WmMButtonDown = 0x0207;
    internal const long WsChild = 0x40000000, WsPopup = 0x80000000, WsCaption = 0x00C00000, WsThickFrame = 0x00040000;
    internal const long WsClipChildren = 0x02000000, WsClipSiblings = 0x04000000;
    internal delegate bool EnumWindowsProc(IntPtr window, IntPtr parameter);
    internal delegate IntPtr LowLevelMouseProc(int code, IntPtr message, IntPtr data);

    [StructLayout(LayoutKind.Sequential)]
    internal struct Point
    {
        internal int X;
        internal int Y;
    }

    [StructLayout(LayoutKind.Sequential)]
    internal struct MsllHookStruct
    {
        internal Point Point;
        internal uint MouseData;
        internal uint Flags;
        internal uint Time;
        internal UIntPtr ExtraInfo;
    }

    [StructLayout(LayoutKind.Sequential)]
    internal struct Rect
    {
        internal int Left;
        internal int Top;
        internal int Right;
        internal int Bottom;
        internal int Width => Right - Left;
        internal int Height => Bottom - Top;
    }

    [StructLayout(LayoutKind.Sequential)]
    internal struct JobObjectBasicLimitInformation
    {
        internal long PerProcessUserTimeLimit;
        internal long PerJobUserTimeLimit;
        internal uint LimitFlags;
        internal UIntPtr MinimumWorkingSetSize;
        internal UIntPtr MaximumWorkingSetSize;
        internal uint ActiveProcessLimit;
        internal UIntPtr Affinity;
        internal uint PriorityClass;
        internal uint SchedulingClass;
    }

    [StructLayout(LayoutKind.Sequential)]
    internal struct IoCounters
    {
        internal ulong ReadOperationCount;
        internal ulong WriteOperationCount;
        internal ulong OtherOperationCount;
        internal ulong ReadTransferCount;
        internal ulong WriteTransferCount;
        internal ulong OtherTransferCount;
    }

    [StructLayout(LayoutKind.Sequential)]
    internal struct JobObjectExtendedLimitInformation
    {
        internal JobObjectBasicLimitInformation BasicLimitInformation;
        internal IoCounters IoInfo;
        internal UIntPtr ProcessMemoryLimit;
        internal UIntPtr JobMemoryLimit;
        internal UIntPtr PeakProcessMemoryUsed;
        internal UIntPtr PeakJobMemoryUsed;
    }

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    internal static extern IntPtr CreateJobObject(IntPtr securityAttributes, string? name);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    internal static extern bool SetInformationJobObject(
        IntPtr job,
        int informationClass,
        ref JobObjectExtendedLimitInformation information,
        uint informationLength);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    internal static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    internal static extern bool CloseHandle(IntPtr handle);

    [DllImport("user32.dll", SetLastError = true)]
    internal static extern IntPtr SetWindowsHookEx(int hookId, LowLevelMouseProc callback, IntPtr module, uint threadId);

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    internal static extern bool UnhookWindowsHookEx(IntPtr hook);

    [DllImport("user32.dll")]
    internal static extern IntPtr CallNextHookEx(IntPtr hook, int code, IntPtr message, IntPtr data);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode)]
    internal static extern IntPtr GetModuleHandle(string? moduleName);

    [DllImport("user32.dll", SetLastError = true)]
    internal static extern IntPtr SetParent(IntPtr child, IntPtr parent);

    [DllImport("user32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    internal static extern bool MoveWindow(IntPtr window, int x, int y, int width, int height, [MarshalAs(UnmanagedType.Bool)] bool repaint);

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    internal static extern bool ShowWindow(IntPtr window, int command);

    [DllImport("user32.dll", EntryPoint = "GetWindowLongPtrW")]
    internal static extern IntPtr GetWindowLongPtr(IntPtr window, int index);

    [DllImport("user32.dll", EntryPoint = "SetWindowLongPtrW")]
    internal static extern IntPtr SetWindowLongPtr(IntPtr window, int index, IntPtr value);

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    internal static extern bool EnumWindows(EnumWindowsProc callback, IntPtr parameter);

    [DllImport("user32.dll")]
    internal static extern uint GetWindowThreadProcessId(IntPtr window, out uint processId);

    [DllImport("user32.dll")]
    internal static extern int GetWindowTextLength(IntPtr window);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    internal static extern int GetWindowText(IntPtr window, StringBuilder text, int maxCount);

    [DllImport("user32.dll")]
    internal static extern IntPtr GetParent(IntPtr window);

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    internal static extern bool GetClientRect(IntPtr window, out Rect rect);

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    internal static extern bool GetWindowRect(IntPtr window, out Rect rect);

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    internal static extern bool IsWindow(IntPtr window);

    [DllImport("user32.dll")]
    internal static extern uint GetClipboardSequenceNumber();
}
