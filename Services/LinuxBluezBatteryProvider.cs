using System.Diagnostics;
using System.Text.RegularExpressions;
using BatteryHUD.Models;

namespace BatteryHUD.Services;

/// <summary>
/// Linux BlueZ provider: connected Bluetooth devices + Battery1 when present.
/// Many HID keyboards never expose a %, but still belong in the list so the
/// user can select them and see connection state.
/// </summary>
public sealed partial class LinuxBluezBatteryProvider : IBatteryDeviceProvider
{
    public string PlatformName => "Linux (BlueZ)";

    public IReadOnlyList<BatteryDevice> GetDevices()
    {
        var devices = new List<BatteryDevice>();

        // Preferred: busctl ObjectManager (Battery1 + Device1)
        devices.AddRange(FromBusctl());

        // Fallback: bluetoothctl devices + info
        if (devices.Count == 0)
            devices.AddRange(FromBluetoothctl());

        return devices
            .GroupBy(d => d.StableKey)
            .Select(g => g.OrderByDescending(d => d.Percent.HasValue).First())
            .OrderBy(d => d.Name, StringComparer.OrdinalIgnoreCase)
            .ToList();
    }

    private static IEnumerable<BatteryDevice> FromBusctl()
    {
        // Dump managed objects; parse paths and a few properties with busctl get-property
        var tree = Run("busctl", "tree org.bluez");
        if (string.IsNullOrWhiteSpace(tree))
            yield break;

        var devicePaths = DevicePathRegex().Matches(tree)
            .Select(m => m.Value)
            .Distinct(StringComparer.Ordinal)
            .ToList();

        foreach (var path in devicePaths)
        {
            // Skip characteristic/service children — only top-level device nodes
            if (path.Contains("/service", StringComparison.Ordinal))
                continue;

            var connected = GetBool(path, "org.bluez.Device1", "Connected");
            var paired = GetBool(path, "org.bluez.Device1", "Paired");
            if (connected != true && paired != true)
                continue;

            var name = GetString(path, "org.bluez.Device1", "Name")
                       ?? GetString(path, "org.bluez.Device1", "Alias")
                       ?? path.Split('/').Last();
            var address = GetString(path, "org.bluez.Device1", "Address");
            var icon = GetString(path, "org.bluez.Device1", "Icon");

            // Battery1 may live on the device path itself (BlueZ battery plugin)
            int? percent = GetByteAsInt(path, "org.bluez.Battery1", "Percentage");

            // Also scan child battery paths under this device
            if (percent is null)
            {
                foreach (Match m in BatteryChildRegex().Matches(tree))
                {
                    var child = m.Value;
                    if (!child.StartsWith(path + "/", StringComparison.Ordinal))
                        continue;
                    percent = GetByteAsInt(child, "org.bluez.Battery1", "Percentage");
                    if (percent is not null) break;
                }
            }

            yield return new BatteryDevice
            {
                Id = path,
                Name = name!.Trim(),
                Kind = InferKind(name, icon),
                Percent = percent,
                IsPresent = connected == true,
                Address = address,
                VendorHint = null
            };
        }
    }

    private static IEnumerable<BatteryDevice> FromBluetoothctl()
    {
        var listed = Run("bluetoothctl", "devices");
        if (string.IsNullOrWhiteSpace(listed))
            yield break;

        foreach (var line in listed.Split('\n', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries))
        {
            // Device AA:BB:CC:DD:EE:FF Name here
            var parts = line.Split(' ', 3, StringSplitOptions.RemoveEmptyEntries);
            if (parts.Length < 2 || !parts[0].Equals("Device", StringComparison.OrdinalIgnoreCase))
                continue;

            var address = parts[1];
            var name = parts.Length >= 3 ? parts[2] : address;
            var info = Run("bluetoothctl", $"info {address}");
            if (string.IsNullOrWhiteSpace(info))
                continue;

            bool connected = false, paired = false;
            string? icon = null;
            int? percent = null;

            foreach (var raw in info.Split('\n'))
            {
                var t = raw.Trim();
                if (t.StartsWith("Connected:", StringComparison.OrdinalIgnoreCase))
                    connected = t.Contains("yes", StringComparison.OrdinalIgnoreCase);
                else if (t.StartsWith("Paired:", StringComparison.OrdinalIgnoreCase))
                    paired = t.Contains("yes", StringComparison.OrdinalIgnoreCase);
                else if (t.StartsWith("Icon:", StringComparison.OrdinalIgnoreCase))
                    icon = t.Split(':', 2).Last().Trim();
                else if (t.StartsWith("Battery Percentage:", StringComparison.OrdinalIgnoreCase) ||
                         t.StartsWith("Battery:", StringComparison.OrdinalIgnoreCase))
                {
                    var m = PercentRegex().Match(t);
                    if (m.Success && int.TryParse(m.Groups[1].Value, out var p))
                        percent = p;
                }
            }

            if (!connected && !paired)
                continue;

            yield return new BatteryDevice
            {
                Id = $"bt:{address}",
                Name = name.Trim(),
                Kind = InferKind(name, icon),
                Percent = percent,
                IsPresent = connected,
                Address = address
            };
        }
    }

    private static string? InferKind(string? name, string? icon)
    {
        var blob = $"{name} {icon}".ToLowerInvariant();
        if (blob.Contains("input-gaming") || blob.Contains("gamepad") || blob.Contains("controller") ||
            blob.Contains("joystick") || blob.Contains("xbox") || blob.Contains("dualsense") ||
            blob.Contains("dualshock") || blob.Contains("playstation"))
            return "Controller";
        if (blob.Contains("mouse") || blob.Contains("input-mouse"))
            return "Mouse";
        if (blob.Contains("keyboard") || blob.Contains("input-keyboard"))
            return "Keyboard";
        if (blob.Contains("audio") || blob.Contains("headset") || blob.Contains("headphone") ||
            blob.Contains("earbuds"))
            return "Audio";
        return "Bluetooth";
    }

    private static string? GetString(string path, string iface, string prop)
    {
        // busctl get-property org.bluez PATH IFACE PROP → s "value"
        var output = Run("busctl", $"get-property org.bluez {path} {iface} {prop}");
        if (string.IsNullOrWhiteSpace(output)) return null;
        var m = StringPropRegex().Match(output);
        return m.Success ? m.Groups[1].Value : null;
    }

    private static bool? GetBool(string path, string iface, string prop)
    {
        var output = Run("busctl", $"get-property org.bluez {path} {iface} {prop}");
        if (string.IsNullOrWhiteSpace(output)) return null;
        if (output.Contains("true", StringComparison.OrdinalIgnoreCase)) return true;
        if (output.Contains("false", StringComparison.OrdinalIgnoreCase)) return false;
        return null;
    }

    private static int? GetByteAsInt(string path, string iface, string prop)
    {
        var output = Run("busctl", $"get-property org.bluez {path} {iface} {prop}");
        if (string.IsNullOrWhiteSpace(output)) return null;
        // Typical: "y 85" (byte) or "u 85" (uint32)
        foreach (var token in output.Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries))
        {
            if (int.TryParse(token, out var v) && v is >= 0 and <= 100)
                return v;
        }
        return null;
    }

    private static string Run(string fileName, string arguments)
    {
        try
        {
            var psi = new ProcessStartInfo
            {
                FileName = fileName,
                Arguments = arguments,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                UseShellExecute = false,
                CreateNoWindow = true
            };
            using var p = Process.Start(psi);
            if (p is null) return "";
            var stdout = p.StandardOutput.ReadToEnd();
            p.WaitForExit(4000);
            return stdout;
        }
        catch
        {
            return "";
        }
    }

    [GeneratedRegex(@"(/org/bluez/hci\d+/dev_[0-9A-F_]+)", RegexOptions.IgnoreCase)]
    private static partial Regex DevicePathRegex();

    [GeneratedRegex(@"(/org/bluez/hci\d+/dev_[0-9A-F_]+/\S*battery\S*)", RegexOptions.IgnoreCase)]
    private static partial Regex BatteryChildRegex();

    [GeneratedRegex(@"(\d{1,3})\s*%?")]
    private static partial Regex PercentRegex();

    [GeneratedRegex("s\\s+\"([^\"]*)\"")]
    private static partial Regex StringPropRegex();
}
