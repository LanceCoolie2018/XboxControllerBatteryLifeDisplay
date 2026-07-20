using System.Diagnostics;
using System.Runtime.InteropServices;
using BatteryHUD.Models;

namespace BatteryHUD.Services;

/// <summary>
/// macOS provider — best-effort via system_profiler / ioreg for Bluetooth peripherals.
/// Coverage varies by device and macOS version.
/// </summary>
public sealed class MacBatteryProvider : IBatteryDeviceProvider
{
    public string PlatformName => "macOS";

    public IReadOnlyList<BatteryDevice> GetDevices()
    {
        if (!RuntimeInformation.IsOSPlatform(OSPlatform.OSX))
            return Array.Empty<BatteryDevice>();

        var devices = new List<BatteryDevice>();

        // Bluetooth devices with battery from system_profiler
        try
        {
            var output = Run("system_profiler", "SPBluetoothDataType -json");
            // JSON parse without hard dependency: light string scrape for Battery Percent
            // Prefer ioreg path below if profiler is empty
            if (!string.IsNullOrWhiteSpace(output) && output.Contains("battery", StringComparison.OrdinalIgnoreCase))
            {
                // Fall through to ioreg which is more reliable for percent
            }
        }
        catch
        {
            // ignore
        }

        try
        {
            // ioreg lists AppleBluetoothHID and many HID devices with BatteryPercent
            var output = Run("ioreg", "-c AppleDeviceManagementHIDEventService -r -l");
            if (string.IsNullOrWhiteSpace(output))
                output = Run("ioreg", "-l -w 0");

            devices.AddRange(ParseIoreg(output));
        }
        catch
        {
            // ignore
        }

        return devices
            .GroupBy(d => d.Id)
            .Select(g => g.First())
            .OrderBy(d => d.Name, StringComparer.OrdinalIgnoreCase)
            .ToList();
    }

    private static IEnumerable<BatteryDevice> ParseIoreg(string output)
    {
        if (string.IsNullOrWhiteSpace(output))
            yield break;

        // Split into blocks roughly by "+-o " device nodes
        var blocks = output.Split(new[] { "+-o " }, StringSplitOptions.RemoveEmptyEntries);
        foreach (var block in blocks)
        {
            int? percent = null;
            string? product = null;
            string? name = null;

            foreach (var rawLine in block.Split('\n'))
            {
                var line = rawLine.Trim();
                if (line.Contains("\"BatteryPercent\"", StringComparison.Ordinal) ||
                    line.Contains("\"BatteryPercentRemaining\"", StringComparison.Ordinal))
                {
                    var eq = line.LastIndexOf('=');
                    if (eq >= 0 && int.TryParse(line[(eq + 1)..].Trim().TrimEnd(','), out var p) && p is >= 0 and <= 100)
                        percent = p;
                }
                else if (line.Contains("\"Product\"", StringComparison.Ordinal) ||
                         line.Contains("\"DeviceAddress\"", StringComparison.Ordinal) is false &&
                         line.Contains("\"ProductID\"", StringComparison.Ordinal) is false)
                {
                    if (line.Contains("\"Product\" =", StringComparison.Ordinal))
                        product = ExtractQuoted(line);
                }
                else if (line.Contains("\"DeviceName\"", StringComparison.Ordinal) ||
                         line.Contains("\"Bluetooth Product Name\"", StringComparison.Ordinal))
                {
                    name = ExtractQuoted(line);
                }
            }

            if (percent is null)
                continue;

            var display = product ?? name;
            if (string.IsNullOrWhiteSpace(display))
                continue;

            yield return new BatteryDevice
            {
                Id = $"mac:{display}:{percent}",
                Name = display!,
                Kind = InferKind(display!),
                Percent = percent,
                IsPresent = true
            };
        }
    }

    private static string? ExtractQuoted(string line)
    {
        var first = line.IndexOf('"');
        if (first < 0) return null;
        // value after = "..."
        var eq = line.IndexOf('=');
        if (eq < 0) return null;
        var rest = line[(eq + 1)..].Trim();
        if (rest.StartsWith('"'))
        {
            var end = rest.IndexOf('"', 1);
            if (end > 1) return rest[1..end];
        }
        return rest.Trim().Trim('"');
    }

    private static string? InferKind(string name)
    {
        var n = name.ToLowerInvariant();
        if (n.Contains("mouse") || n.Contains("trackpad")) return "Mouse";
        if (n.Contains("keyboard")) return "Keyboard";
        if (n.Contains("controller") || n.Contains("gamepad") || n.Contains("dualsense") || n.Contains("xbox"))
            return "Controller";
        if (n.Contains("airpods") || n.Contains("headset") || n.Contains("headphone")) return "Audio";
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
            p.WaitForExit(8000);
            return stdout;
        }
        catch
        {
            return "";
        }
    }
}
