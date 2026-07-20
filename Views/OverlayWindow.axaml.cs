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
        if (_settings.WindowX is double x && _settings.WindowY is double y)
        {
            Position = new PixelPoint((int)x, (int)y);
            return;
        }

        var screen = Screens.Primary ?? Screens.All.FirstOrDefault();
        if (screen is null) return;

        var wa = screen.WorkingArea;
        var pad = _settings.EdgePadding;
        var w = double.IsNaN(Width) || Width <= 0 ? 280 : Width;
        var h = double.IsNaN(Height) || Height <= 0 ? 88 : Height;
        Position = new PixelPoint(
            wa.X + wa.Width - (int)w - pad,
            wa.Y + wa.Height - (int)h - pad);
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
                ? $"No battery devices ({_monitor.PlatformName})"
                : "Click Switch to choose a device";
            HintText.Text = "Connect a controller, mouse, or BT device with battery";
            return;
        }

        PercentText.Text = device.Percent is int p ? $"{p}%" : "??%";
        PercentText.Foreground = BatteryColors.ForPercent(device.Percent, low, !device.IsPresent);

        var kind = device.Kind is null ? "" : $" · {device.Kind}";
        var charge = device.IsCharging ? " · charging" : "";
        DeviceText.Text = $"{device.Name}{kind}{charge}";

        if (!device.IsPresent)
            HintText.Text = "Device disconnected — switch or wait for reconnect";
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
            _monitor.SelectedDeviceId = result;
            _settings.SelectedDeviceId = result;
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
