using Avalonia.Controls;
using Avalonia.Controls.ApplicationLifetimes;
using BatteryHUD.Models;
using BatteryHUD.Views;

namespace BatteryHUD.Services;

/// <summary>
/// Owns one or more overlay widgets that share a single battery poller,
/// plus an optional secondary hologram clock overlay.
/// Each battery widget can watch a different device at the same time.
/// </summary>
public sealed class WidgetHost
{
    private readonly BatteryMonitorService _monitor;
    private readonly AppSettings _settings;
    private readonly SettingsService _settingsService;
    private readonly IClassicDesktopStyleApplicationLifetime _desktop;
    private readonly List<OverlayWindow> _windows = new();
    private HologramClockWindow? _clock;

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

        if (_settings.ShowHologramClock)
            EnsureClock(show: false);

        _desktop.MainWindow = _windows[0];
        foreach (var w in _windows)
            w.Show();
        _clock?.Show();

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

    /// <summary>Open (or focus) the secondary hologram clock overlay.</summary>
    public void ShowHologramClock()
    {
        EnsureClock(show: true);
        _settings.ShowHologramClock = true;
        PersistAll();
    }

    public void PersistAll()
    {
        var slots = _windows.Select(w => w.ToSlot()).ToList();
        _settings.ApplyWidgets(slots);

        if (_clock is not null)
        {
            _settings.ShowHologramClock = true;
            _settings.ClockWindowX = _clock.WindowX;
            _settings.ClockWindowY = _clock.WindowY;
            _settings.HologramClockStyle = _clock.StyleName;
        }
        // When clock is closed, ShowHologramClock is cleared in OnClockClosed.

        _settingsService.Save(_settings);
    }

    private void EnsureClock(bool show)
    {
        if (_clock is not null)
        {
            if (show)
            {
                _clock.Activate();
                _clock.Topmost = true;
            }
            return;
        }

        _clock = new HologramClockWindow(
            _settings.ClockWindowX,
            _settings.ClockWindowY,
            _settings.EdgePadding,
            _settings.HologramClockStyle,
            onPersist: PersistAll,
            onClosedByUser: OnClockClosed);

        if (_desktop.MainWindow is null)
            _desktop.MainWindow = _clock;

        if (show)
            _clock.Show();
    }

    private void OnClockClosed()
    {
        if (_clock is null)
            return;

        // Capture position + style one last time before dropping the reference.
        _settings.ClockWindowX = _clock.WindowX;
        _settings.ClockWindowY = _clock.WindowY;
        _settings.HologramClockStyle = _clock.StyleName;
        _settings.ShowHologramClock = false;
        _clock = null;
        _settingsService.Save(_settings);

        // Keep MainWindow pointing at a live window if the clock was it.
        if (_desktop.MainWindow is HologramClockWindow && _windows.Count > 0)
            _desktop.MainWindow = _windows[0];
    }

    private void Spawn(WidgetSlot slot, bool autoSelectWhenEmpty, bool show)
    {
        var win = new OverlayWindow(
            _monitor,
            _settings,
            slot,
            autoSelectWhenEmpty,
            onDuplicate: Duplicate,
            onPersist: PersistAll,
            onShowClock: ShowHologramClock);

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
            // Last battery widget — close clock too so OnLastWindowClose can exit cleanly.
            if (_clock is not null)
            {
                var c = _clock;
                _clock = null;
                _settings.ShowHologramClock = false;
                try { c.Close(); } catch { /* shutting down */ }
            }

            PersistAll();
            return;
        }

        if (ReferenceEquals(_desktop.MainWindow, win))
            _desktop.MainWindow = _windows[0];

        PersistAll();
    }
}
