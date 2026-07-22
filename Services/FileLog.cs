using System;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Threading.Tasks;

namespace BatteryHUD.Services;

/// <summary>
/// Simple rolling-friendly file logger for Maintenance Monkey (and you).
/// Writes to logs/batteryhud.log under the app base directory.
/// </summary>
public static class FileLog
{
    private static readonly object Gate = new();
    private static string? _logPath;
    private static StreamWriter? _writer;

    public static string LogPath =>
        _logPath ?? Path.Combine(ResolveLogDirectory(), "batteryhud.log");

    public static void Initialize()
    {
        try
        {
            var dir = ResolveLogDirectory();
            Directory.CreateDirectory(dir);
            _logPath = Path.Combine(dir, "batteryhud.log");

            var stream = new FileStream(
                _logPath,
                FileMode.Append,
                FileAccess.Write,
                FileShare.ReadWrite);
            _writer = new StreamWriter(stream, Encoding.UTF8) { AutoFlush = true };

            Trace.Listeners.Add(new TextWriterTraceListener(_writer) { Name = "BatteryHUD.FileLog" });
            Trace.AutoFlush = true;

            AppDomain.CurrentDomain.UnhandledException += OnUnhandledException;
            TaskScheduler.UnobservedTaskException += OnUnobservedTaskException;

            Info($"FileLog started → {_logPath}");
        }
        catch (Exception ex)
        {
            Debug.WriteLine($"FileLog init failed: {ex}");
        }
    }

    public static void Info(string message) => Write("INFO", message);

    public static void Warn(string message) => Write("WARN", message);

    public static void Error(string message, Exception? ex = null)
    {
        if (ex is null)
        {
            Write("ERROR", message);
            return;
        }

        Write("ERROR", $"{message}: {ex}");
        Write("ERROR", ex.ToString());
    }

    /// <summary>
    /// Last N lines of the log file for bug reports (best-effort).
    /// </summary>
    public static string ReadTail(int maxLines = 50)
    {
        try
        {
            var path = LogPath;
            if (!File.Exists(path))
                return "(no log file yet)";

            // Share with the live writer
            using var stream = new FileStream(
                path,
                FileMode.Open,
                FileAccess.Read,
                FileShare.ReadWrite);
            using var reader = new StreamReader(stream, Encoding.UTF8);
            var lines = new List<string>();
            while (reader.ReadLine() is { } line)
            {
                lines.Add(line);
                if (lines.Count > maxLines)
                    lines.RemoveAt(0);
            }

            return lines.Count == 0 ? "(log empty)" : string.Join(Environment.NewLine, lines);
        }
        catch (Exception ex)
        {
            return $"(could not read log: {ex.Message})";
        }
    }

    private static void Write(string level, string message)
    {
        var line = $"{DateTime.Now:yyyy-MM-dd HH:mm:ss.fff} [{level}] {message}";
        try
        {
            lock (Gate)
            {
                _writer?.WriteLine(line);
            }
        }
        catch
        {
            // ignore logging failures
        }

        Trace.WriteLine(line);
    }

    private static string ResolveLogDirectory()
    {
        // Prefer repo-root/logs when running from bin/.../netX.0
        var baseDir = AppContext.BaseDirectory;
        var probe = new DirectoryInfo(baseDir);
        for (var i = 0; i < 6 && probe is not null; i++)
        {
            var csproj = Path.Combine(probe.FullName, "BatteryHUD.csproj");
            if (File.Exists(csproj))
                return Path.Combine(probe.FullName, "logs");
            probe = probe.Parent;
        }

        return Path.Combine(baseDir, "logs");
    }

    private static void OnUnhandledException(object sender, UnhandledExceptionEventArgs e)
    {
        if (e.ExceptionObject is Exception ex)
            Error("Unhandled exception", ex);
        else
            Error($"Unhandled exception: {e.ExceptionObject}");
    }

    private static void OnUnobservedTaskException(object? sender, UnobservedTaskExceptionEventArgs e)
    {
        Error("Unobserved task exception", e.Exception);
        e.SetObserved();
    }
}
