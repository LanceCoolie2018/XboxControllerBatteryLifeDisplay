using Avalonia;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Markup.Xaml;
using BatteryHUD.Services;

namespace BatteryHUD;

public partial class App : Application
{
    public override void Initialize() => AvaloniaXamlLoader.Load(this);

    public override void OnFrameworkInitializationCompleted()
    {
        if (ApplicationLifetime is IClassicDesktopStyleApplicationLifetime desktop)
        {
            var settingsService = new SettingsService();
            var settings = settingsService.Load();
            var provider = BatteryProviderFactory.Create();
            var monitor = new BatteryMonitorService(provider, settings);

            var host = new WidgetHost(monitor, settings, settingsService, desktop);
            host.Start();

            desktop.Exit += (_, _) => monitor.Dispose();
        }

        base.OnFrameworkInitializationCompleted();
    }
}
