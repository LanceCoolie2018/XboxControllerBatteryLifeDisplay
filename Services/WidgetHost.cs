using Avalonia.Controls;
using Avalonia.Controls.ApplicationLifetimes;
using BatteryHUD.Models;
using BatteryHUD.Views;

namespace BatteryHUD.Services;

/// <summary>
/// Owns one or more overlay widgets that share a single battery poller.
/// Each widget can watch a different device at the same time.
/// </summary>
public sealed class WidgetHost
{
    private readonly BatteryMonitorService _monitor;
    private readonly AppSettings _settings;
    private readonly SettingsService _settingsService;
    private readonly IClassicDesktopStyleApplicationLifetime _desktop;
    private readonly List<OverlayWindow> _windows = new();

    public WidgetHost(
        BatteryMonitorService monitor,
        AppSettings settings,
        SettingsService settingsService,
        IClassicDesktopStyleApplicationLifetime desktop)
    {
        _monitor = monitor;
        _settings = settings;
        _settingsService = settingsService;
        _desktop = desktop;
    }

    public void Start()
    {
        // Closing one of several widgets must not quit the process.
        _desktop.ShutdownMode = ShutdownMode.OnLastWindowClose;

        var slots = _settings.GetEffectiveWidgets();
        for (var i = 0; i < slots.Count; i++)
        {
            // Only the first (or only) slot auto-picks a controller when empty.
            var autoSelect = i == 0;
            Spawn(slots[i], autoSelectWhenEmpty: autoSelect, show: false);
        }

        if (_windows.Count == 0)
            Spawn(new WidgetSlot(), autoSelectWhenEmpty: true, show: false);

        _desktop.MainWindow = _windows[0];
        foreach (var w in _windows)
            w.Show();

        _monitor.Start();
    }

    /// <summary>
    /// Open another overlay (offset from the source) so the user can Switch to a second device.
    /// </summary>
    public void Duplicate(OverlayWindow source)
    {
        var slot = new WidgetSlot
        {
            WindowX = source.Position.X + 24,
            WindowY = source.Position.Y + 48
        };
        Spawn(slot, autoSelectWhenEmpty: false, show: true);
        PersistAll();
    }

    public void PersistAll()
    {
        var slots = _windows.Select(w => w.ToSlot()).ToList();
        _settings.ApplyWidgets(slots);
        _settingsService.Save(_settings);
    }

    private void Spawn(WidgetSlot slot, bool autoSelectWhenEmpty, bool show)
    {
        var win = new OverlayWindow(
            _monitor,
            _settings,
            slot,
            autoSelectWhenEmpty,
            onDuplicate: Duplicate,
            onPersist: PersistAll);

        win.Closed += OnWindowClosed;
        _windows.Add(win);

        if (_desktop.MainWindow is null)
            _desktop.MainWindow = win;

        if (show)
            win.Show();
    }

    private void OnWindowClosed(object? sender, EventArgs e)
    {
        if (sender is not OverlayWindow win)
            return;

        win.Closed -= OnWindowClosed;
        _windows.Remove(win);

        if (_windows.Count == 0)
        {
            // Last window — still persist empty/single-clear so relaunch is clean.
            PersistAll();
            return;
        }

        if (ReferenceEquals(_desktop.MainWindow, win))
            _desktop.MainWindow = _windows[0];

        PersistAll();
    }
}
