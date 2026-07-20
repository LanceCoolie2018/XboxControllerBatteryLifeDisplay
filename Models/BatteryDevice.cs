namespace BatteryHUD.Models;

/// <summary>
/// A peripheral (or system) device that reports a battery level.
/// Controllers, mice, keyboards, headsets — anything the OS exposes.
/// </summary>
public sealed class BatteryDevice
{
    public required string Id { get; init; }
    public required string Name { get; init; }
    public string? Kind { get; init; }
    public int? Percent { get; init; }
    public bool IsPresent { get; init; } = true;
    public bool IsCharging { get; init; }
    public string? VendorHint { get; init; }

    public string DisplayName =>
        string.IsNullOrWhiteSpace(Kind) ? Name : $"{Name} ({Kind})";

    public string StatusText
    {
        get
        {
            if (!IsPresent)
                return "Disconnected";
            if (Percent is null)
                return "Battery unknown";
            var suffix = IsCharging ? " charging" : "";
            return $"{Percent}%{suffix}";
        }
    }

    public string Subtitle
    {
        get
        {
            var kind = string.IsNullOrWhiteSpace(Kind) ? "Device" : Kind!;
            return $"{kind} · {StatusText}";
        }
    }

    public override string ToString() => $"{DisplayName}: {StatusText}";
}
