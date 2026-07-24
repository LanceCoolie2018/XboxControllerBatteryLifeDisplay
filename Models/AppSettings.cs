namespace BatteryHUD.Models;

public sealed class AppSettings
{
    /// <summary>
    /// Legacy single-widget selection (kept for migration; mirrored from Widgets[0]).
    /// </summary>
    public string? SelectedDeviceId { get; set; }

    /// <summary>How often to poll battery %, in milliseconds.</summary>
    public int PollIntervalMs { get; set; } = 3000;

    /// <summary>
    /// How long to keep a device in the list after a failed/missing poll (seconds).
    /// Prevents Bluetooth/WMI blips from wiping the picker mid-game.
    /// </summary>
    public int DeviceGraceSeconds { get; set; } = 45;

    /// <summary>Corner padding from screen edges.</summary>
    public int EdgePadding { get; set; } = 12;

    /// <summary>Legacy single-widget position (mirrored from Widgets[0]).</summary>
    public double? WindowX { get; set; }
    public double? WindowY { get; set; }

    /// <summary>Warn (pulse) when battery is at or below this %.</summary>
    public int LowBatteryThreshold { get; set; } = 15;

    /// <summary>
    /// Keep battery widgets (and the clock) above other windows.
    /// Off by default — standard Avalonia <c>Window.Topmost</c> only; no elevated privileges.
    /// </summary>
    public bool AlwaysOnTop { get; set; }

    /// <summary>
    /// One entry per overlay widget so multiple devices can be watched at once.
    /// Empty list means migrate from <see cref="SelectedDeviceId"/> / WindowX/Y.
    /// </summary>
    public List<WidgetSlot> Widgets { get; set; } = new();

    /// <summary>Whether the secondary hologram clock overlay is open.</summary>
    public bool ShowHologramClock { get; set; }

    /// <summary>Saved hologram clock position (null = default top-right).</summary>
    public double? ClockWindowX { get; set; }
    public double? ClockWindowY { get; set; }

    /// <summary>
    /// Hologram clock appearance: "Digital" (default plate) or "Grandfather" (tall analog).
    /// Unknown values fall back to Digital.
    /// </summary>
    public string HologramClockStyle { get; set; } = "Digital";

    /// <summary>
    /// Widgets to open on startup: multi-slot list, or a single slot from legacy fields.
    /// </summary>
    public List<WidgetSlot> GetEffectiveWidgets()
    {
        if (Widgets is { Count: > 0 })
            return Widgets.Select(CloneSlot).ToList();

        return
        [
            new WidgetSlot
            {
                SelectedDeviceId = SelectedDeviceId,
                WindowX = WindowX,
                WindowY = WindowY
            }
        ];
    }

    /// <summary>Write multi-widget state and keep legacy fields in sync with the first slot.</summary>
    public void ApplyWidgets(IReadOnlyList<WidgetSlot> slots)
    {
        Widgets = slots.Select(CloneSlot).ToList();
        if (Widgets.Count > 0)
        {
            SelectedDeviceId = Widgets[0].SelectedDeviceId;
            WindowX = Widgets[0].WindowX;
            WindowY = Widgets[0].WindowY;
        }
        else
        {
            SelectedDeviceId = null;
            WindowX = null;
            WindowY = null;
        }
    }

    private static WidgetSlot CloneSlot(WidgetSlot s) => new()
    {
        SelectedDeviceId = s.SelectedDeviceId,
        WindowX = s.WindowX,
        WindowY = s.WindowY
    };
}
