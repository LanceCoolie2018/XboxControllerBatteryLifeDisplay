using System;
using Avalonia;
using BatteryHUD.Services;

namespace BatteryHUD;

internal static class Program
{
    [STAThread]
    public static void Main(string[] args)
    {
        // File logging for Maintenance Monkey (logs/batteryhud.log)
        FileLog.Initialize();
        try
        {
            BuildAvaloniaApp().StartWithClassicDesktopLifetime(args);
        }
        catch (Exception ex)
        {
            FileLog.Error("Fatal startup exception", ex);
            throw;
        }
    }

    public static AppBuilder BuildAvaloniaApp() =>
        AppBuilder.Configure<App>()
            .UsePlatformDetect()
            .WithInterFont()
            .LogToTrace();
}
