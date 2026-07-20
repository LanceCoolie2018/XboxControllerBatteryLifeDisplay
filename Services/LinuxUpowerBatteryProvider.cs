using System.Diagnostics;
using BatteryHUD.Models;

namespace BatteryHUD.Services;

/// <summary>
/// Linux provider using UPower (controllers, BT mice, keyboards, etc.).
/// </summary>
public sealed partial class LinuxUpowerBatteryProvider : IBatteryDeviceProvider
{
    public string PlatformName => "Linux (UPower)";

    public IReadOnlyList<BatteryDevice> GetDevices()
    {
        var devices = new List<BatteryDevice>();

        if (!IsUpowerAvailable())
            return devices;

        foreach (var path in ListDevicePaths())
        {
            // Skip aggregate display / AC adapters
            if (path.EndsWith("/DisplayDevice", StringComparison.Ordinal) ||
                path.Contains("line_power", StringComparison.OrdinalIgnoreCase))
                continue;

            var device = ReadDevice(path);
            if (device is not null)
                devices.Add(device);
        }

        return devices
            .OrderBy(d => d.Name, StringComparer.OrdinalIgnoreCase)
            .ToList();
    }

    private static bool IsUpowerAvailable()
    {
        try
        {
            var psi = new ProcessStartInfo
            {
                FileName = "upower",
                Arguments = "--version",
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                UseShellExecute = false,
                CreateNoWindow = true
            };
            using var p = Process.Start(psi);
            if (p is null) return false;
            p.WaitForExit(2000);
            return p.ExitCode == 0;
        }
        catch
        {
            return false;
        }
    }

    private static IEnumerable<string> ListDevicePaths()
    {
        var output = Run("upower", "-e");
        if (string.IsNullOrWhiteSpace(output))
            yield break;

        foreach (var line in output.Split('\n', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries))
        {
            if (line.StartsWith("/org/freedesktop/UPower/devices/", StringComparison.Ordinal))
                yield return line;
        }
    }

    private static BatteryDevice? ReadDevice(string path)
    {
        var output = Run("upower", $"-i {Quote(path)}");
        if (string.IsNullOrWhiteSpace(output))
            return null;

        string? model = null;
        string? nativePath = null;
        string? type = null;
        string? vendor = null;
        double? percentage = null;
        bool isPresent = true;
        bool isCharging = false;
        bool hasBattery = false;

        foreach (var raw in output.Split('\n'))
        {
            var line = raw.Trim();
            if (line.StartsWith("model:", StringComparison.OrdinalIgnoreCase))
                model = ValueAfterColon(line);
            else if (line.StartsWith("native-path:", StringComparison.OrdinalIgnoreCase))
                nativePath = ValueAfterColon(line);
            else if (line.StartsWith("serial:", StringComparison.OrdinalIgnoreCase) && model is null)
                model = ValueAfterColon(line);
            else if (line.StartsWith("vendor:", StringComparison.OrdinalIgnoreCase))
                vendor = ValueAfterColon(line);
            else if (line.StartsWith("type:", StringComparison.OrdinalIgnoreCase))
                type = ValueAfterColon(line);
            else if (line.StartsWith("percentage:", StringComparison.OrdinalIgnoreCase))
            {
                var v = ValueAfterColon(line)?.Replace("%", "", StringComparison.Ordinal).Trim();
                if (double.TryParse(v, out var pct))
                {
                    percentage = pct;
                    hasBattery = true;
                }
            }
            else if (line.StartsWith("percentage", StringComparison.OrdinalIgnoreCase) && line.Contains(':'))
            {
                // some versions format differently
            }
            else if (line.StartsWith("state:", StringComparison.OrdinalIgnoreCase))
            {
                var state = ValueAfterColon(line)?.ToLowerInvariant() ?? "";
                isCharging = state is "charging" or "fully-charged" or "pending-charge";
                if (state is "empty" or "unknown")
                { /* still may have percentage */ }
            }
            else if (line.StartsWith("is-present:", StringComparison.OrdinalIgnoreCase))
            {
                var v = ValueAfterColon(line)?.ToLowerInvariant();
                isPresent = v is not ("no" or "false");
            }
            else if (line.StartsWith("power supply:", StringComparison.OrdinalIgnoreCase))
            {
                // power supply devices (laptops) are fine to include; user can pick
            }
        }

        // Only expose devices that actually report a battery percentage
        // (or battery type with is-present). UPower battery/keyboard/mouse/gaming-input.
        var kind = NormalizeKind(type, model, nativePath);
        if (!hasBattery && kind is null)
            return null;
        if (!hasBattery && percentage is null)
        {
            // Some devices report capacity only when present
            if (!isPresent)
                return null;
            // Still list if type is a known battery-bearing peripheral without % yet
            if (kind is null)
                return null;
        }

        // Filter pure AC line power already done; also skip if no useful identity
        var name = !string.IsNullOrWhiteSpace(model)
            ? model!
            : !string.IsNullOrWhiteSpace(nativePath)
                ? nativePath!
                : path.Split('/').Last();

        // Skip devices that are clearly not batteries and have no %
        if (percentage is null && type is not null &&
            type.Equals("line-power", StringComparison.OrdinalIgnoreCase))
            return null;

        if (percentage is null && !hasBattery)
            return null;

        return new BatteryDevice
        {
            Id = path,
            Name = name.Trim(),
            Kind = kind,
            Percent = percentage is null ? null : (int)Math.Round(percentage.Value),
            IsPresent = isPresent,
            IsCharging = isCharging,
            VendorHint = vendor
        };
    }

    private static string? NormalizeKind(string? type, string? model, string? nativePath)
    {
        var blob = $"{type} {model} {nativePath}".ToLowerInvariant();

        if (blob.Contains("gaming") || blob.Contains("gamepad") || blob.Contains("controller") ||
            blob.Contains("joystick") || blob.Contains("xbox") || blob.Contains("dualshock") ||
            blob.Contains("dualsense") || blob.Contains("playstation") || blob.Contains("ps4") ||
            blob.Contains("ps5") || blob.Contains("switch"))
            return "Controller";

        if (blob.Contains("mouse"))
            return "Mouse";
        if (blob.Contains("keyboard"))
            return "Keyboard";
        if (blob.Contains("headset") || blob.Contains("headphone") || blob.Contains("earbuds") ||
            blob.Contains("airpods") || blob.Contains("speaker"))
            return "Audio";
        if (blob.Contains("tablet") || blob.Contains("pen") || blob.Contains("stylus"))
            return "Tablet";
        if (type?.Equals("battery", StringComparison.OrdinalIgnoreCase) == true)
            return "Battery";
        if (!string.IsNullOrWhiteSpace(type))
            return Capitalize(type);

        return null;
    }

    private static string Capitalize(string s) =>
        string.IsNullOrEmpty(s) ? s : char.ToUpperInvariant(s[0]) + s[1..];

    private static string? ValueAfterColon(string line)
    {
        var idx = line.IndexOf(':');
        if (idx < 0) return null;
        return line[(idx + 1)..].Trim();
    }

    private static string Quote(string path) =>
        path.Contains(' ') ? $"\"{path}\"" : path;

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
            p.WaitForExit(5000);
            return stdout;
        }
        catch
        {
            return "";
        }
    }
}
