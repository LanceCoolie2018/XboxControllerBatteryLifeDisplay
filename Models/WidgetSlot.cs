namespace BatteryHUD.Models;

/// <summary>
/// One always-on-top overlay instance: which device it watches and where it sits.
/// </summary>
public sealed class WidgetSlot
{
    /// <summary>Selected device id or stable key (null = none / auto for first widget).</summary>
    public string? SelectedDeviceId { get; set; }

    /// <summary>Saved overlay position (null = default placement).</summary>
    public double? WindowX { get; set; }
    public double? WindowY { get; set; }
}
