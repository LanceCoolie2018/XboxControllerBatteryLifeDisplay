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
    private readonly Action<OverlayWindow>? _onDuplicate;
    private readonly Action? _onPersist;
    private readonly Action? _onShowClock;
    private string? _selectedDeviceId;
    private bool _autoSelectWhenEmpty;
    private bool _dragging;
    private Point _dragStart;
    private bool _pulseOn;
    private readonly DispatcherTimer _pulseTimer;
    private readonly double? _initialX;
    private readonly double? _initialY;

    // Avalonia design-time / resource loader
    public OverlayWindow() : this(
        new BatteryMonitorService(BatteryProviderFactory.Create(), new AppSettings()),
        new AppSettings(),
        new WidgetSlot(),
        autoSelectWhenEmpty: true)
    {
    }

    public OverlayWindow(
        BatteryMonitorService monitor,
        AppSettings settings,
        WidgetSlot slot,
        bool autoSelectWhenEmpty,
        Action<OverlayWindow>? onDuplicate = null,
        Action? onPersist = null,
        Action? onShowClock = null)
    {
        _monitor = monitor;
        _settings = settings;
        _selectedDeviceId = slot.SelectedDeviceId;
        _autoSelectWhenEmpty = autoSelectWhenEmpty;
        _onDuplicate = onDuplicate;
        _onPersist = onPersist;
        _onShowClock = onShowClock;
        _initialX = slot.WindowX;
        _initialY = slot.WindowY;

        InitializeComponent();
        ApplyAlwaysOnTop();

        _monitor.Updated += (_, _) => Dispatcher.UIThread.Post(Render);

        _pulseTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(600) };
        _pulseTimer.Tick += (_, _) =>
        {
            _pulseOn = !_pulseOn;
            var selected = ResolveDevice();
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

    /// <summary>Apply shared always-on-top preference (standard Avalonia Window.Topmost).</summary>
    public void ApplyAlwaysOnTop()
    {
        Topmost = _settings.AlwaysOnTop;
        if (PinButton is not null)
            PinButton.Content = _settings.AlwaysOnTop ? "Unpin" : "Pin";
    }

    /// <summary>Snapshot of this widget for multi-slot settings persistence.</summary>
    public WidgetSlot ToSlot() => new()
    {
        SelectedDeviceId = _selectedDeviceId,
        WindowX = Position.X,
        WindowY = Position.Y
    };

    private BatteryDevice? ResolveDevice()
    {
        if (!string.IsNullOrEmpty(_selectedDeviceId))
            return _monitor.FindDevice(_selectedDeviceId);

        if (_autoSelectWhenEmpty)
            return _monitor.Selected;

        return null;
    }

    private void PlaceWindow()
    {
        var w = (int)(double.IsNaN(Width) || Width <= 0 ? 292 : Width);
        var h = (int)(double.IsNaN(Height) || Height <= 0 ? 58 : Height);

        // Restore saved position only if it still lands on a connected screen.
        // Multi-monitor setups (laptop docked vs undocked) often leave coords
        // completely off-screen so the app looks like it "won't start".
        if (_initialX is double sx && _initialY is double sy)
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
        var device = ResolveDevice();
        var low = _settings.LowBatteryThreshold;

        // If auto-select found a device, remember its stable key so Switch/Dup stay consistent.
        if (device is not null && string.IsNullOrEmpty(_selectedDeviceId) && _autoSelectWhenEmpty)
            _selectedDeviceId = device.StableKey;

        if (device is null)
        {
            PercentText.Text = "--";
            PercentText.Foreground = BatteryColors.ForPercent(null, low, true);
            DeviceText.Text = _monitor.Devices.Count == 0
                ? "No devices — pair Bluetooth in Windows Settings"
                : "No device selected";
            return;
        }

        if (!device.IsPresent)
        {
            PercentText.Text = device.Percent is int last ? $"{last}%" : "—";
            PercentText.Foreground = BatteryColors.ForPercent(device.Percent, low, true);
            DeviceText.Text = $"{device.Name} · disconnected";
            return;
        }

        if (device.Percent is int p)
        {
            PercentText.Text = $"{p}%";
            PercentText.Foreground = BatteryColors.ForPercent(p, low, false);
            DeviceText.Text = $"{device.Name} · connected";
        }
        else
        {
            PercentText.Text = "N/A";
            PercentText.Foreground = BatteryColors.ForPercent(null, low, false);
            DeviceText.Text = $"{device.Name} · Battery not reported";
        }
    }

    private void OnPinClick(object? sender, RoutedEventArgs e)
    {
        _settings.AlwaysOnTop = !_settings.AlwaysOnTop;
        ApplyAlwaysOnTop();
        PersistSettings();
        // Host re-applies to all widgets + clock when PersistAll runs.
    }

    private async void OnSwitchClick(object? sender, RoutedEventArgs e)
    {
        _monitor.Refresh();

        var currentId = _selectedDeviceId ?? ResolveDevice()?.Id;
        var picker = new DevicePickerWindow(
            _monitor.Devices,
            currentId,
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
            _selectedDeviceId = null;
            _autoSelectWhenEmpty = false;
        }
        else
        {
            // Prefer durable stable key when available so Windows id churn doesn't drop selection
            var picked = _monitor.Devices.FirstOrDefault(d => d.Id == result);
            _selectedDeviceId = picked?.StableKey ?? result;
            _autoSelectWhenEmpty = false;
        }

        PersistSettings();
        Render();
    }

    private void OnDupClick(object? sender, RoutedEventArgs e)
    {
        // New widget shares the poller; user picks another device via Switch on the copy.
        _onDuplicate?.Invoke(this);
    }

    private void OnTimeClick(object? sender, RoutedEventArgs e)
    {
        // Secondary hologram clock — independent of battery device selection.
        _onShowClock?.Invoke();
    }

    private void OnExitClick(object? sender, RoutedEventArgs e)
    {
        // Overlay has no system chrome; Exit closes this widget only.
        // Last remaining widget triggers app shutdown (OnLastWindowClose).
        Close();
    }

    private async void OnBugClick(object? sender, RoutedEventArgs e)
    {
        var dlg = new BugReportWindow
        {
            WindowStartupLocation = WindowStartupLocation.CenterOwner
        };
        await dlg.ShowDialog<bool?>(this);
    }

    private static bool IsOverButton(Visual? source, Button button) =>
        source is not null && (source == button || button.IsVisualAncestorOf(source));

    private void OnPointerPressed(object? sender, PointerPressedEventArgs e)
    {
        if (e.Source is Visual v &&
            (IsOverButton(v, PinButton) ||
             IsOverButton(v, SwitchButton) ||
             IsOverButton(v, DupButton) ||
             IsOverButton(v, TimeButton) ||
             IsOverButton(v, BugButton) ||
             IsOverButton(v, ExitButton)))
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
        if (_onPersist is not null)
        {
            _onPersist();
            return;
        }

        // Design-time / standalone: no host — nothing shared to save.
    }
}
