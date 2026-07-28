using Avalonia;
using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Interactivity;
using Avalonia.Media;
using Avalonia.Threading;
using Avalonia.VisualTree;

namespace BatteryHUD.Views;

/// <summary>
/// Secondary always-on-top overlay: live clock as a cyan hologram plate.
/// Styles: Digital (compact red digits) or Grandfather (tall analog + pendulum).
/// Drag to any screen; position and style are persisted via the host callback.
/// </summary>
public partial class HologramClockWindow : Window
{
    public const string StyleDigital = "Digital";
    public const string StyleGrandfather = "Grandfather";

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
    private string _style;

    // Avalonia design-time / resource loader
    public HologramClockWindow() : this(null, null, 12, StyleDigital, null, null)
    {
    }

    public HologramClockWindow(
        double? windowX,
        double? windowY,
        int edgePadding,
        string? style,
        Action? onPersist,
        Action? onClosedByUser)
    {
        _initialX = windowX;
        _initialY = windowY;
        _edgePadding = edgePadding;
        _onPersist = onPersist;
        _onClosedByUser = onClosedByUser;
        _style = NormalizeStyle(style);

        InitializeComponent();

        _clockTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(250) };
        _clockTimer.Tick += (_, _) => TickClock();
        _clockTimer.Start();

        // Soft scan-line drift + pendulum swing for a hologram projector feel
        _scanTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(40) };
        _scanTimer.Tick += (_, _) => TickScan();
        _scanTimer.Start();

        Opened += (_, _) => PlaceWindow();
        Closing += OnClosing;

        ApplyStyleLayout(persist: false);
        TickClock();
    }

    public double WindowX => Position.X;
    public double WindowY => Position.Y;

    /// <summary>Persisted style name: Digital or Grandfather.</summary>
    public string StyleName => _style;

    private static string NormalizeStyle(string? style) =>
        string.Equals(style, StyleGrandfather, StringComparison.OrdinalIgnoreCase)
            ? StyleGrandfather
            : StyleDigital;

    private void ApplyStyleLayout(bool persist)
    {
        var grandfather = _style == StyleGrandfather;
        DigitalPanel.IsVisible = !grandfather;
        GrandfatherPanel.IsVisible = grandfather;
        TitleText.Text = grandfather ? "HOLO GRAND" : "HOLO TIME";
        ToolTip.SetTip(StyleButton,
            grandfather
                ? "Switch to Digital hologram style"
                : "Switch to Grandfather hologram style");

        // Compact plate vs tall case
        if (grandfather)
        {
            Width = 148;
            Height = 268;
            MinWidth = 130;
            MinHeight = 240;
            RootBorder.Padding = new Thickness(10, 8, 10, 10);
        }
        else
        {
            Width = 280;
            Height = 100;
            MinWidth = 220;
            MinHeight = 90;
            RootBorder.Padding = new Thickness(14, 10, 14, 12);
        }

        TickClock();
        if (persist)
            _onPersist?.Invoke();
    }

    private void OnStyleClick(object? sender, RoutedEventArgs e)
    {
        _style = _style == StyleGrandfather ? StyleDigital : StyleGrandfather;
        ApplyStyleLayout(persist: true);
    }

    private void TickClock()
    {
        var now = DateTime.Now;
        // 12h with AM/PM keeps the digit block readable
        var time = now.ToString("h:mm:ss");
        var ampm = now.ToString("tt");
        var display = $"{time} {ampm}";
        var date = now.ToString("ddd · MMM d · yyyy").ToUpperInvariant();

        if (_style == StyleDigital)
        {
            TimeText.Text = display;
            TimeGhostMagenta.Text = display;
            TimeGhostCyan.Text = display;
            DateText.Text = date;
        }
        else
        {
            GrandDigitalText.Text = display;
            GrandDateText.Text = date;
            UpdateAnalogHands(now);
        }
    }

    private void UpdateAnalogHands(DateTime now)
    {
        // Clock angles: 0° = 12 o'clock, clockwise positive (Avalonia RotateTransform).
        var sec = now.Second + now.Millisecond / 1000.0;
        var min = now.Minute + sec / 60.0;
        var hour = (now.Hour % 12) + min / 60.0;

        SetHandAngle(HourHand, hour * 30.0);   // 360/12
        SetHandAngle(MinuteHand, min * 6.0);   // 360/60
        SetHandAngle(SecondHand, sec * 6.0);
    }

    private static void SetHandAngle(Border hand, double degrees)
    {
        if (hand.RenderTransform is RotateTransform rot)
            rot.Angle = degrees;
        else
            hand.RenderTransform = new RotateTransform(degrees);
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
        if (_style == StyleDigital)
            TimeText.Opacity = flicker;
        else
        {
            GrandDigitalText.Opacity = flicker;
            // Pendulum swing (~0.55 Hz, small arc)
            var swing = 14.0 * Math.Sin(t * Math.PI * 1.1);
            if (PendulumAssembly.RenderTransform is RotateTransform pendRot)
                pendRot.Angle = swing;
            else
                PendulumAssembly.RenderTransform = new RotateTransform(swing);
        }
    }

    private void PlaceWindow()
    {
        // Position / WorkingArea are physical pixels; layout sizes are DIPs (UR-gh-24).
        GetPhysicalSize(out var wPx, out var hPx);

        if (_initialX is double sx && _initialY is double sy)
        {
            var candidate = new PixelPoint((int)sx, (int)sy);
            if (IsMostlyOnAnyScreen(candidate, wPx, hPx))
            {
                Position = candidate;
                return;
            }
        }

        // Default: top-right of primary (keeps clear of battery HUD bottom-right)
        var screen = Screens.Primary ?? Screens.All.FirstOrDefault();
        if (screen is null) return;
        var wa = screen.WorkingArea;
        var scale = screen.Scaling > 0 ? screen.Scaling : 1.0;
        var pad = (int)Math.Round(_edgePadding * scale);
        Position = new PixelPoint(
            wa.X + wa.Width - wPx - pad,
            wa.Y + pad);
    }

    private void GetPhysicalSize(out int wPx, out int hPx)
    {
        if (FrameSize is { } fs && fs.Width > 0 && fs.Height > 0)
        {
            wPx = Math.Max(1, (int)Math.Ceiling(fs.Width));
            hPx = Math.Max(1, (int)Math.Ceiling(fs.Height));
            return;
        }

        var screen = Screens.Primary ?? Screens.All.FirstOrDefault();
        var scale = screen?.Scaling ?? (DesktopScaling > 0 ? DesktopScaling : 1.0);
        if (scale <= 0) scale = 1.0;

        var wDip = Bounds.Width > 1 ? Bounds.Width
            : (!double.IsNaN(Width) && Width > 0 ? Width : 280);
        var hDip = Bounds.Height > 1 ? Bounds.Height
            : (!double.IsNaN(Height) && Height > 0 ? Height : 100);

        wPx = Math.Max(1, (int)Math.Ceiling(wDip * scale));
        hPx = Math.Max(1, (int)Math.Ceiling(hDip * scale));
    }

    private bool IsMostlyOnAnyScreen(PixelPoint topLeft, int wPx, int hPx)
    {
        const int minOverlap = 40;
        var win = new PixelRect(topLeft.X, topLeft.Y, Math.Max(wPx, minOverlap), Math.Max(hPx, minOverlap));

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
        if (e.Source is Visual v &&
            (IsOverButton(v, CloseButton) || IsOverButton(v, StyleButton)))
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
