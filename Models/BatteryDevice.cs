namespace BatteryHUD.Models;

/// <summary>
/// A peripheral (or system) device that may report a battery level.
/// Controllers, mice, keyboards, headsets — anything the OS exposes.
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

    public string StatusText
    {
        get
        {
            if (!IsPresent)
                return Percent is int p ? $"Last {p}% · offline" : "Disconnected";
            if (Percent is null)
                return "Connected · battery unknown";
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
