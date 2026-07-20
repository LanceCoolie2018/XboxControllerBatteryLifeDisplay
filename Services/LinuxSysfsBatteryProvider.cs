using BatteryHUD.Models;

namespace BatteryHUD.Services;

/// <summary>
/// Reads /sys/class/power_supply for HID/BT batteries the kernel exposes.
/// </summary>
public sealed class LinuxSysfsBatteryProvider : IBatteryDeviceProvider
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

                // Skip pure system battery-less nodes with no capacity
                if (percent is null && !string.Equals(type, "Battery", StringComparison.OrdinalIgnoreCase) &&
                    !string.Equals(type, "UPS", StringComparison.OrdinalIgnoreCase))
                {
                    // Still include hid devices named like hid-... if present
                    if (!name.Contains("hid", StringComparison.OrdinalIgnoreCase) &&
                        !name.Contains("ps-controller", StringComparison.OrdinalIgnoreCase))
                        continue;
                }

                var model = Read(dir, "model_name")?.Trim()
                            ?? Read(dir, "manufacturer")?.Trim()
                            ?? name;
                var status = Read(dir, "status")?.Trim();
                var present = Read(dir, "present")?.Trim();
                var isPresent = present is null or "1";
                var charging = status is not null &&
                               status.Contains("Charging", StringComparison.OrdinalIgnoreCase);

                results.Add(new BatteryDevice
                {
                    Id = $"sysfs:{name}",
                    Name = model,
                    Kind = InferKind(name, type, model),
                    Percent = percent,
                    IsPresent = isPresent,
                    IsCharging = charging
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
}
