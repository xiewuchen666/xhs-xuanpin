using System.IO;
using System.Text;

namespace XhsXuanpin.App;

internal static class AppLogger
{
    private const long MaxBytes = 2 * 1024 * 1024;
    private const int BackupCount = 5;
    private static readonly object Sync = new();
    private static readonly string LogDirectory = FindLogDirectory();
    private static readonly string LogPath = Path.Combine(LogDirectory, "app.log");

    public static string CurrentLogPath => LogPath;

    public static void Info(string source, string message) =>
        Write("INFO", source, message, null);

    public static void Warning(string source, string message) =>
        Write("WARN", source, message, null);

    public static void Error(string source, string message, Exception? exception = null) =>
        Write("ERROR", source, message, exception);

    private static void Write(string level, string source, string message, Exception? exception)
    {
        try
        {
            lock (Sync)
            {
                Directory.CreateDirectory(LogDirectory);
                RotateIfNeeded();
                var line = $"{DateTime.Now:yyyy-MM-dd HH:mm:ss.fff} | {level} | {source} | {message}";
                if (exception is not null)
                    line += Environment.NewLine + exception;
                File.AppendAllText(LogPath, line + Environment.NewLine, new UTF8Encoding(false));
            }
        }
        catch
        {
            // Logging must never make the workbench fail.
        }
    }

    private static void RotateIfNeeded()
    {
        var file = new FileInfo(LogPath);
        if (!file.Exists || file.Length < MaxBytes)
            return;

        var oldest = LogPath + "." + BackupCount;
        if (File.Exists(oldest))
            File.Delete(oldest);

        for (var index = BackupCount - 1; index >= 1; index--)
        {
            var source = LogPath + "." + index;
            var destination = LogPath + "." + (index + 1);
            if (File.Exists(source))
                File.Move(source, destination, overwrite: true);
        }

        File.Move(LogPath, LogPath + ".1", overwrite: true);
    }

    private static string FindLogDirectory()
    {
        var envData = Environment.GetEnvironmentVariable("XHS_XUANPIN_DATA_DIR");
        if (!string.IsNullOrWhiteSpace(envData))
            return Path.Combine(envData, "logs");

        foreach (var start in new[] { Directory.GetCurrentDirectory(), AppContext.BaseDirectory })
        {
            var current = new DirectoryInfo(start);
            while (current is not null)
            {
                if (Directory.Exists(Path.Combine(current.FullName, "backend")) &&
                    Directory.Exists(Path.Combine(current.FullName, "src")))
                    return Path.Combine(current.FullName, "data", "logs");
                current = current.Parent;
            }
        }

        return Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "XhsXuanpin",
            "logs");
    }
}
