using System.Text.RegularExpressions;
using BatteryHUD.Models;

namespace BatteryHUD.Services;

/// <summary>
/// Reads /sys/class/power_supply for HID/BT batteries the kernel exposes.
/// Extracts BT MACs from node names so Composite can apply BlueZ offline vetoes
/// (sysfs often keeps capacity + present=1 after the radio link is gone).
/// </summary>
public sealed partial class LinuxSysfsBatteryProvider : IBatteryDeviceProvider
{
    public string PlatformName => "Linux (sysfs)";

    public IReadOnlyList<BatteryDevice> GetDevices()
    {
        var results = new List<BatteryDevice>();
        const string root = "/sys/class/power_supply";
        if (!Directory.Exists(root))
            return results;

        foreach (var dir in Directory.EnumerateDirectories(root))
        {
            try
            {
                var name = Path.GetFileName(dir);
                var type = Read(dir, "type")?.Trim();
                if (string.Equals(type, "Mains", StringComparison.OrdinalIgnoreCase))
                    continue;

                var capacity = Read(dir, "capacity");
                int? percent = null;
                if (int.TryParse(capacity?.Trim(), out var p) && p is >= 0 and <= 100)
                    percent = p;

                // Only nodes with a real capacity % belong in the picker
                if (percent is null)
                    continue;

                var model = Read(dir, "model_name")?.Trim()
                            ?? Read(dir, "manufacturer")?.Trim()
                            ?? name;
                var status = Read(dir, "status")?.Trim();
                var present = Read(dir, "present")?.Trim();
                // Missing "present" is not proof of connection (many HID nodes omit it).
                // Only treat explicit "1" / "yes" as present; explicit "0"/"no" as offline.
                var isPresent = present switch
                {
                    null => true, // unknown — Composite/BlueZ veto decides
                    "1" => true,
                    "yes" => true,
                    "Y" => true,
                    "0" => false,
                    "no" => false,
                    "N" => false,
                    _ => !present.Equals("0", StringComparison.OrdinalIgnoreCase)
                };
                var charging = status is not null &&
                               status.Contains("Charging", StringComparison.OrdinalIgnoreCase);

                var address = TryExtractBtAddress(name)
                              ?? TryExtractBtAddress(model)
                              ?? TryExtractBtAddress(Read(dir, "serial_number")?.Trim());

                results.Add(new BatteryDevice
                {
                    Id = $"sysfs:{name}",
                    Name = model,
                    Kind = InferKind(name, type, model),
                    Percent = percent,
                    IsPresent = isPresent,
                    IsCharging = charging,
                    Address = address
                });
            }
            catch
            {
                // skip node
            }
        }

        return results;
    }

    private static string? Read(string dir, string file)
    {
        var path = Path.Combine(dir, file);
        try
        {
            return File.Exists(path) ? File.ReadAllText(path) : null;
        }
        catch
        {
            return null;
        }
    }

    /// <summary>
    /// Kernel HID/BT power_supply nodes often embed the MAC:
    /// hid-aa:bb:cc:dd:ee:ff-battery, hid-aabbccddeeff-battery,
    /// ps-controller-battery-aa:bb:cc:dd:ee:ff, etc.
    /// </summary>
    private static string? TryExtractBtAddress(string? blob)
    {
        if (string.IsNullOrWhiteSpace(blob))
            return null;

        var colon = ColonMacRegex().Match(blob);
        if (colon.Success)
            return colon.Value.ToUpperInvariant();

        var bare = BareMacRegex().Match(blob);
        if (bare.Success)
        {
            var raw = bare.Groups[1].Value.ToUpperInvariant();
            return string.Join(":", Enumerable.Range(0, 6).Select(i => raw.Substring(i * 2, 2)));
        }

        return null;
    }

    private static string? InferKind(string sysName, string? type, string model)
    {
        var blob = $"{sysName} {type} {model}".ToLowerInvariant();
        if (blob.Contains("controller") || blob.Contains("gamepad") || blob.Contains("sony") ||
            blob.Contains("xbox") || blob.Contains("dualsense") || blob.Contains("dualshock"))
            return "Controller";
        if (blob.Contains("mouse")) return "Mouse";
        if (blob.Contains("keyboard") || blob.Contains("kbd")) return "Keyboard";
        if (string.Equals(type, "Battery", StringComparison.OrdinalIgnoreCase) &&
            (blob.Contains("bat") || blob.Contains("macsmc") || blob.Contains("pmu")))
            return "System";
        return type;
    }

    [GeneratedRegex(@"\b([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}\b")]
    private static partial Regex ColonMacRegex();

    // 12 hex digits bordered by non-hex (or string ends) — avoid matching random ids
    [GeneratedRegex(@"(?:^|[^0-9A-Fa-f])([0-9A-Fa-f]{12})(?:[^0-9A-Fa-f]|$)")]
    private static partial Regex BareMacRegex();
}
