using System.Threading;
using System.IO;
using System.Windows;

namespace XhsXuanpin.App;

public partial class App : System.Windows.Application
{
    private const string SingleInstanceMutexName = @"Local\XhsXuanpin.App";
    private const string ActivationEventName = @"Local\XhsXuanpin.App.Activate";
    private Mutex? _singleInstanceMutex;
    private EventWaitHandle? _activationEvent;
    private Thread? _activationThread;
    private bool _ownsSingleInstanceMutex;
    private volatile bool _isExiting;

    internal bool IsExiting => _isExiting;

    protected override void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);
        if (File.Exists(Path.Combine(AppContext.BaseDirectory, "installed.marker")))
            Environment.SetEnvironmentVariable(
                "XHS_XUANPIN_DATA_DIR",
                Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "XhsXuanpin", "data"));
        DispatcherUnhandledException += (_, args) =>
        {
            AppLogger.Error("App", "Dispatcher unhandled exception", args.Exception);
        };
        AppDomain.CurrentDomain.UnhandledException += (_, args) =>
        {
            var exception = args.ExceptionObject as Exception;
            AppLogger.Error(
                "AppDomain",
                $"Unhandled exception; terminating={args.IsTerminating}",
                exception);
        };
        TaskScheduler.UnobservedTaskException += (_, args) =>
        {
            AppLogger.Error("TaskScheduler", "Unobserved task exception", args.Exception);
        };

        AppLogger.Info("App", $"Workbench starting; log={AppLogger.CurrentLogPath}");

        _singleInstanceMutex = new Mutex(initiallyOwned: true, SingleInstanceMutexName, out var createdNew);
        _ownsSingleInstanceMutex = createdNew;
        if (!createdNew)
        {
            AppLogger.Info("App", "Second workbench instance requested main-window activation");
            try
            {
                using var activationEvent = EventWaitHandle.OpenExisting(ActivationEventName);
                activationEvent.Set();
            }
            catch (WaitHandleCannotBeOpenedException)
            {
                AppLogger.Warning("App", "Running workbench has no activation channel");
            }
            Shutdown();
            return;
        }

        _activationEvent = new EventWaitHandle(
            initialState: false,
            EventResetMode.AutoReset,
            ActivationEventName);
        _activationThread = new Thread(ListenForActivation)
        {
            IsBackground = true,
            Name = "xhs-xuanpin-activation"
        };
        _activationThread.Start();

        AppLogger.MarkSessionStarted();
        var mainWindow = new MainWindow();
        MainWindow = mainWindow;
        mainWindow.Show();
    }

    private void ListenForActivation()
    {
        while (!_isExiting)
        {
            _activationEvent?.WaitOne();
            if (_isExiting) return;
            Dispatcher.BeginInvoke(RestoreMainWindow);
        }
    }

    private void RestoreMainWindow()
    {
        if (MainWindow is XhsXuanpin.App.MainWindow window)
            window.RestoreFromTray();
    }

    internal async void ExitApplication()
    {
        if (_isExiting) return;
        _isExiting = true;
        try
        {
            if (MainWindow is XhsXuanpin.App.MainWindow window)
                await window.PrepareForExitAsync();
        }
        catch (Exception ex)
        {
            AppLogger.Error("App", "Workbench exit cleanup failed", ex);
            System.Windows.MessageBox.Show($"退出时未能完全关闭模拟器：{ex.Message}", "小红书选品工作台", MessageBoxButton.OK, MessageBoxImage.Warning);
        }
        Shutdown();
    }

    protected override void OnSessionEnding(SessionEndingCancelEventArgs e)
    {
        _isExiting = true;
        base.OnSessionEnding(e);
    }

    protected override void OnExit(ExitEventArgs e)
    {
        _isExiting = true;
        _activationEvent?.Set();
        _activationThread?.Join(TimeSpan.FromMilliseconds(500));
        _activationEvent?.Dispose();
        AppLogger.Info("App", $"Workbench exiting; code={e.ApplicationExitCode}");
        if (_ownsSingleInstanceMutex && _singleInstanceMutex is not null)
        {
            AppLogger.MarkSessionEnded();
            _singleInstanceMutex.ReleaseMutex();
        }
        _singleInstanceMutex?.Dispose();
        base.OnExit(e);
    }
}
