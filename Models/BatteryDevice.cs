namespace BatteryHUD.Models;

/// <summary>
/// A peripheral (or system) device that may report a battery level.
/// Controllers, mice, keyboards, headsets — including paired Bluetooth
/// devices that never expose a charge percentage to Windows.
/// </summary>
public sealed record BatteryDevice
{
    public required string Id { get; init; }
    public required string Name { get; init; }
    public string? Kind { get; init; }
    public int? Percent { get; init; }
    public bool IsPresent { get; init; } = true;
    public bool IsCharging { get; init; }
    public string? VendorHint { get; init; }

    /// <summary>Bluetooth MAC or other durable address when known.</summary>
    public string? Address { get; init; }

    /// <summary>
    /// Cross-poll identity that should survive OS id churn
    /// (prefer address, else normalized name).
    /// </summary>
    public string StableKey =>
        !string.IsNullOrWhiteSpace(Address)
            ? $"addr:{Address.Replace(":", "", StringComparison.Ordinal).ToUpperInvariant()}"
            : $"name:{Name.Trim().ToLowerInvariant()}";

    public string DisplayName =>
        string.IsNullOrWhiteSpace(Kind) ? Name : $"{Name} ({Kind})";

    /// <summary>Short percent column for the device picker.</summary>
    public string PercentDisplay =>
        Percent is int p ? $"{p}%" : "N/A";

    public string StatusText
    {
        get
        {
            if (!IsPresent)
                return Percent is int p ? $"Disconnected · last {p}%" : "Disconnected";
            if (Percent is null)
                return "Connected · Battery not reported";
            var suffix = IsCharging ? " · charging" : "";
            return $"Connected · {Percent}%{suffix}";
        }
    }

    public string Subtitle
    {
        get
        {
            var kind = string.IsNullOrWhiteSpace(Kind) ? "Device" : Kind!;
            if (!IsPresent)
                return $"{kind} · disconnected";
            if (Percent is null)
                return $"{kind} · no battery data from Windows";
            return $"{kind} · {StatusText}";
        }
    }

    public override string ToString() => $"{DisplayName}: {StatusText}";
}
