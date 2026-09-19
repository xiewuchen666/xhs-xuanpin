using System.Threading;
using System.Windows;

namespace XhsXuanpin.App;

public partial class App : System.Windows.Application
{
    private Mutex? _singleInstanceMutex;
    private bool _ownsSingleInstanceMutex;

    protected override void OnStartup(StartupEventArgs e)
    {
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

        _singleInstanceMutex = new Mutex(initiallyOwned: true, @"Local\XhsXuanpin.App", out var createdNew);
        _ownsSingleInstanceMutex = createdNew;
        if (!createdNew)
        {
            AppLogger.Warning("App", "Second workbench instance was blocked");
            System.Windows.MessageBox.Show("小红书选品工作台已在运行。", "小红书选品工作台", MessageBoxButton.OK, MessageBoxImage.Information);
            Shutdown();
            return;
        }

        base.OnStartup(e);
    }

    protected override void OnExit(ExitEventArgs e)
    {
        AppLogger.Info("App", $"Workbench exiting; code={e.ApplicationExitCode}");
        if (_ownsSingleInstanceMutex && _singleInstanceMutex is not null)
        {
            _singleInstanceMutex.ReleaseMutex();
        }
        _singleInstanceMutex?.Dispose();
        base.OnExit(e);
    }
}
