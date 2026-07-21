namespace BatteryHUD.Models;

public sealed class AppSettings
{
    /// <summary>Last selected device id (platform-specific or stable key).</summary>
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

    /// <summary>Saved overlay position (null = default bottom-right).</summary>
    public double? WindowX { get; set; }
    public double? WindowY { get; set; }

    /// <summary>Warn (pulse) when battery is at or below this %.</summary>
    public int LowBatteryThreshold { get; set; } = 15;
}
