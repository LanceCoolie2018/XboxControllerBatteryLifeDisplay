using Avalonia;
using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Interactivity;
using Avalonia.Threading;
using Avalonia.VisualTree;

namespace BatteryHUD.Views;

/// <summary>
/// Secondary always-on-top overlay: live clock styled as a cyan hologram plate with bright red digits and gold labels.
/// Drag to any screen; position is persisted via the host callback.
/// </summary>
public partial class HologramClockWindow : Window
{
    private readonly Action? _onPersist;
    private readonly Action? _onClosedByUser;
    private readonly int _edgePadding;
    private readonly double? _initialX;
    private readonly double? _initialY;
    private readonly DispatcherTimer _clockTimer;
    private readonly DispatcherTimer _scanTimer;
    private bool _dragging;
    private Point _dragStart;
    private double _scanOffset;

    // Avalonia design-time / resource loader
    public HologramClockWindow() : this(null, null, 12, null, null)
    {
    }

    public HologramClockWindow(
        double? windowX,
        double? windowY,
        int edgePadding,
        Action? onPersist,
        Action? onClosedByUser)
    {
        _initialX = windowX;
        _initialY = windowY;
        _edgePadding = edgePadding;
        _onPersist = onPersist;
        _onClosedByUser = onClosedByUser;

        InitializeComponent();

        _clockTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(250) };
        _clockTimer.Tick += (_, _) => TickClock();
        _clockTimer.Start();

        // Soft scan-line drift for a hologram projector feel
        _scanTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(40) };
        _scanTimer.Tick += (_, _) => TickScan();
        _scanTimer.Start();

        Opened += (_, _) => PlaceWindow();
        Closing += OnClosing;

        TickClock();
    }

    public double WindowX => Position.X;
    public double WindowY => Position.Y;

    private void TickClock()
    {
        var now = DateTime.Now;
        // 12h with AM/PM keeps the digit block readable; 24h would be denser
        var time = now.ToString("h:mm:ss");
        var ampm = now.ToString("tt");
        var display = $"{time} {ampm}";
        TimeText.Text = display;
        TimeGhostMagenta.Text = display;
        TimeGhostCyan.Text = display;
        DateText.Text = now.ToString("ddd · MMM d · yyyy").ToUpperInvariant();
    }

    private void TickScan()
    {
        // Bounce the scan band slowly down the plate
        _scanOffset += 0.8;
        var max = Math.Max(20, Bounds.Height - 16);
        if (_scanOffset > max)
            _scanOffset = 0;
        ScanBand.Margin = new Thickness(2, 4 + _scanOffset, 2, 0);

        // Subtle opacity pulse on main digits (hologram flicker)
        var t = Environment.TickCount64 / 1000.0;
        var flicker = 0.88 + 0.12 * Math.Sin(t * 3.1);
        TimeText.Opacity = flicker;
    }

    private void PlaceWindow()
    {
        var w = (int)(double.IsNaN(Width) || Width <= 0 ? 280 : Width);
        var h = (int)(double.IsNaN(Height) || Height <= 0 ? 100 : Height);

        if (_initialX is double sx && _initialY is double sy)
        {
            var candidate = new PixelPoint((int)sx, (int)sy);
            if (IsMostlyOnAnyScreen(candidate, w, h))
            {
                Position = candidate;
                return;
            }
        }

        // Default: top-right of primary (keeps clear of battery HUD bottom-right)
        var screen = Screens.Primary ?? Screens.All.FirstOrDefault();
        if (screen is null) return;
        var wa = screen.WorkingArea;
        Position = new PixelPoint(
            wa.X + wa.Width - w - _edgePadding,
            wa.Y + _edgePadding);
    }

    private bool IsMostlyOnAnyScreen(PixelPoint topLeft, int w, int h)
    {
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

    private void OnCloseClick(object? sender, RoutedEventArgs e) => Close();

    private void OnClosing(object? sender, WindowClosingEventArgs e)
    {
        _clockTimer.Stop();
        _scanTimer.Stop();
        _onPersist?.Invoke();
        _onClosedByUser?.Invoke();
    }

    private static bool IsOverButton(Visual? source, Button button) =>
        source is not null && (source == button || button.IsVisualAncestorOf(source));

    private void OnPointerPressed(object? sender, PointerPressedEventArgs e)
    {
        if (e.Source is Visual v && IsOverButton(v, CloseButton))
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
        _onPersist?.Invoke();
    }
}
