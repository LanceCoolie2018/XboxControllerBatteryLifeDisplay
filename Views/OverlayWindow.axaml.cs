using Avalonia;
using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Interactivity;
using Avalonia.Threading;
using Avalonia.VisualTree;
using BatteryHUD.Models;
using BatteryHUD.Services;

namespace BatteryHUD.Views;

public partial class OverlayWindow : Window
{
    private readonly BatteryMonitorService _monitor;
    private readonly AppSettings _settings;
    private readonly SettingsService _settingsService;
    private bool _dragging;
    private Point _dragStart;
    private bool _pulseOn;
    private readonly DispatcherTimer _pulseTimer;

    // Avalonia design-time / resource loader
    public OverlayWindow() : this(
        new BatteryMonitorService(BatteryProviderFactory.Create(), new AppSettings()),
        new AppSettings(),
        new SettingsService())
    {
    }

    public OverlayWindow(
        BatteryMonitorService monitor,
        AppSettings settings,
        SettingsService settingsService)
    {
        _monitor = monitor;
        _settings = settings;
        _settingsService = settingsService;

        InitializeComponent();

        _monitor.Updated += (_, _) => Dispatcher.UIThread.Post(Render);

        _pulseTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(600) };
        _pulseTimer.Tick += (_, _) =>
        {
            _pulseOn = !_pulseOn;
            var selected = _monitor.Selected;
            if (selected?.Percent is int p && p <= _settings.LowBatteryThreshold && selected.IsPresent)
                PercentText.Opacity = _pulseOn ? 1.0 : 0.35;
            else
                PercentText.Opacity = 1.0;
        };
        _pulseTimer.Start();

        Opened += (_, _) => PlaceWindow();
        Closing += (_, _) => PersistSettings();

        Render();
    }

    private void PlaceWindow()
    {
        var w = (int)(double.IsNaN(Width) || Width <= 0 ? 280 : Width);
        var h = (int)(double.IsNaN(Height) || Height <= 0 ? 88 : Height);

        // Restore saved position only if it still lands on a connected screen.
        // Multi-monitor setups (laptop docked vs undocked) often leave coords
        // completely off-screen so the app looks like it "won't start".
        if (_settings.WindowX is double sx && _settings.WindowY is double sy)
        {
            var candidate = new PixelPoint((int)sx, (int)sy);
            if (IsMostlyOnAnyScreen(candidate, w, h))
            {
                Position = candidate;
                return;
            }
        }

        PlaceDefaultBottomRight(w, h);
    }

    private void PlaceDefaultBottomRight(int w, int h)
    {
        var screen = Screens.Primary ?? Screens.All.FirstOrDefault();
        if (screen is null) return;

        var wa = screen.WorkingArea;
        var pad = _settings.EdgePadding;
        Position = new PixelPoint(
            wa.X + wa.Width - w - pad,
            wa.Y + wa.Height - h - pad);
    }

    /// <summary>
    /// True when at least a decent chunk of the window overlaps some screen working area.
    /// </summary>
    private bool IsMostlyOnAnyScreen(PixelPoint topLeft, int w, int h)
    {
        // Require a useful overlap so a 1px clip on the edge of a disconnected display fails.
        const int minOverlap = 40;
        var win = new PixelRect(topLeft.X, topLeft.Y, Math.Max(w, minOverlap), Math.Max(h, minOverlap));

        foreach (var screen in Screens.All)
        {
            var area = screen.WorkingArea;
            var ox = Math.Max(0, Math.Min(win.X + win.Width, area.X + area.Width) - Math.Max(win.X, area.X));
            var oy = Math.Max(0, Math.Min(win.Y + win.Height, area.Y + area.Height) - Math.Max(win.Y, area.Y));
            if (ox >= minOverlap && oy >= minOverlap)
                return true;
        }

        return false;
    }

    private void Render()
    {
        var device = _monitor.Selected;
        var low = _settings.LowBatteryThreshold;

        if (device is null)
        {
            PercentText.Text = "--";
            PercentText.Foreground = BatteryColors.ForPercent(null, low, true);
            DeviceText.Text = _monitor.Devices.Count == 0
                ? $"No devices ({_monitor.PlatformName})"
                : "Click Switch to choose a device";
            HintText.Text = "Connect a controller, mouse, or BT peripheral";
            return;
        }

        PercentText.Text = device.Percent is int p ? $"{p}%" : "??%";
        PercentText.Foreground = BatteryColors.ForPercent(device.Percent, low, !device.IsPresent);

        var kind = device.Kind is null ? "" : $" · {device.Kind}";
        var charge = device.IsCharging ? " · charging" : "";
        var offline = device.IsPresent ? "" : " · offline";
        DeviceText.Text = $"{device.Name}{kind}{charge}{offline}";

        if (!device.IsPresent)
            HintText.Text = "Link lost — keeping last reading; will refresh on reconnect";
        else if (device.Percent is null)
            HintText.Text = "Connected, but OS isn't reporting battery % for this device";
        else if (device.Percent is int pct && pct <= low)
            HintText.Text = "Low battery — good time to swap before a fight";
        else
            HintText.Text = "Drag to move · Switch anytime";
    }

    private async void OnSwitchClick(object? sender, RoutedEventArgs e)
    {
        _monitor.Refresh();

        var picker = new DevicePickerWindow(
            _monitor.Devices,
            _monitor.SelectedDeviceId ?? _monitor.Selected?.Id,
            () =>
            {
                _monitor.Refresh();
                return _monitor.Devices;
            })
        {
            WindowStartupLocation = WindowStartupLocation.CenterOwner
        };

        var result = await picker.ShowDialog<string?>(this);
        if (result is null)
            return;

        if (result == DevicePickerWindow.ClearSelectionId)
        {
            _monitor.SelectedDeviceId = null;
            _settings.SelectedDeviceId = null;
        }
        else
        {
            // Prefer durable stable key when available so Windows id churn doesn't drop selection
            var picked = _monitor.Devices.FirstOrDefault(d => d.Id == result);
            var storeId = picked?.StableKey ?? result;
            _monitor.SelectedDeviceId = storeId;
            _settings.SelectedDeviceId = storeId;
        }

        _settingsService.Save(_settings);
        Render();
    }

    private void OnPointerPressed(object? sender, PointerPressedEventArgs e)
    {
        if (e.Source is Visual v && (v == SwitchButton || SwitchButton.IsVisualAncestorOf(v)))
            return;

        if (!e.GetCurrentPoint(this).Properties.IsLeftButtonPressed)
            return;

        _dragging = true;
        _dragStart = e.GetPosition(this);
        e.Pointer.Capture(RootBorder);
    }

    private void OnPointerMoved(object? sender, PointerEventArgs e)
    {
        if (!_dragging) return;

        var p = e.GetPosition(this);
        var dx = (int)(p.X - _dragStart.X);
        var dy = (int)(p.Y - _dragStart.Y);
        if (dx == 0 && dy == 0) return;
        Position = new PixelPoint(Position.X + dx, Position.Y + dy);
    }

    private void OnPointerReleased(object? sender, PointerReleasedEventArgs e)
    {
        if (!_dragging) return;
        _dragging = false;
        e.Pointer.Capture(null);
        PersistSettings();
    }

    private void PersistSettings()
    {
        _settings.WindowX = Position.X;
        _settings.WindowY = Position.Y;
        _settings.SelectedDeviceId = _monitor.SelectedDeviceId;
        _settingsService.Save(_settings);
    }
}
