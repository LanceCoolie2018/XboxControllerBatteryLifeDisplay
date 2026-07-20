using System.Diagnostics.CodeAnalysis;
using System.Runtime.InteropServices;
using System.Runtime.Versioning;
using BatteryHUD.Models;

namespace BatteryHUD.Services;

/// <summary>
/// Windows provider: scans PnP devices for battery percentage properties
/// (Xbox, DualSense, BT mice/keyboards, headsets, etc.).
/// </summary>
public sealed class WindowsWmiBatteryProvider : IBatteryDeviceProvider
{
    // Microsoft Bluetooth battery level DEVPKEY (percent 0-100)
    private const string BluetoothBatteryLevelKey = "{104EA319-6EE2-4701-BD47-8DDBF425BBE5} 2";

    public string PlatformName => "Windows (WMI/PnP)";

    public IReadOnlyList<BatteryDevice> GetDevices()
    {
        if (!RuntimeInformation.IsOSPlatform(OSPlatform.Windows))
            return Array.Empty<BatteryDevice>();

        return Enumerate();
    }

    [SupportedOSPlatform("windows")]
    [UnconditionalSuppressMessage("Interoperability", "CA1416", Justification = "Guarded by OSPlatform.Windows check in GetDevices.")]
    private static IReadOnlyList<BatteryDevice> Enumerate()
    {
        var results = new List<BatteryDevice>();

        try
        {
            // System.Management is Windows-only at runtime; guarded above.
            using var searcher = new System.Management.ManagementObjectSearcher(
                @"root\CIMV2",
                "SELECT Name, DeviceID, PNPDeviceID, Status, PNPClass FROM Win32_PnPEntity WHERE Name IS NOT NULL");

            foreach (System.Management.ManagementObject obj in searcher.Get())
            {
                using (obj)
                {
                    var device = TryRead(obj);
                    if (device is not null)
                        results.Add(device);
                }
            }
        }
        catch (PlatformNotSupportedException)
        {
            return Array.Empty<BatteryDevice>();
        }
        catch
        {
            // WMI unavailable
        }

        return results
            .GroupBy(d => d.Id)
            .Select(g => g.First())
            .OrderBy(d => d.Name, StringComparer.OrdinalIgnoreCase)
            .ToList();
    }

    private static BatteryDevice? TryRead(System.Management.ManagementObject obj)
    {
        try
        {
            var name = obj["Name"]?.ToString();
            var deviceId = obj["DeviceID"]?.ToString() ?? obj["PNPDeviceID"]?.ToString();
            var status = obj["Status"]?.ToString();
            var pnpClass = obj["PNPClass"]?.ToString();

            if (string.IsNullOrWhiteSpace(name) || string.IsNullOrWhiteSpace(deviceId))
                return null;

            var isOk = string.Equals(status, "OK", StringComparison.OrdinalIgnoreCase);
            int? percent = null;

            try
            {
                var outParams = obj.InvokeMethod("GetDeviceProperties", null, null);
                if (outParams?["deviceProperties"] is System.Management.ManagementBaseObject[] properties)
                {
                    foreach (var prop in properties)
                    {
                        var keyName = prop["KeyName"]?.ToString();
                        if (keyName is null) continue;

                        var isBatteryKey =
                            keyName.Equals(BluetoothBatteryLevelKey, StringComparison.OrdinalIgnoreCase) ||
                            (keyName.Contains("Battery", StringComparison.OrdinalIgnoreCase) &&
                             (keyName.Contains("Level", StringComparison.OrdinalIgnoreCase) ||
                              keyName.Contains("Percent", StringComparison.OrdinalIgnoreCase)));

                        if (!isBatteryKey) continue;

                        var data = prop["Data"];
                        if (data is null) continue;

                        try
                        {
                            var value = Convert.ToInt32(data);
                            if (value is >= 0 and <= 3 &&
                                keyName.Contains("Level", StringComparison.OrdinalIgnoreCase) &&
                                !keyName.Contains("Percent", StringComparison.OrdinalIgnoreCase))
                            {
                                percent = value switch
                                {
                                    0 => 5,
                                    1 => 25,
                                    2 => 55,
                                    3 => 100,
                                    _ => value
                                };
                            }
                            else if (value is >= 0 and <= 100)
                            {
                                percent = value;
                            }
                        }
                        catch
                        {
                            // ignore bad data
                        }

                        if (percent is not null)
                            break;
                    }
                }
            }
            catch
            {
                // GetDeviceProperties unsupported on this node
            }

            if (percent is null)
                return null;

            return new BatteryDevice
            {
                Id = deviceId!,
                Name = name!.Trim(),
                Kind = InferKind(name!, pnpClass),
                Percent = percent,
                IsPresent = isOk,
                IsCharging = false,
                VendorHint = InferVendor(name!)
            };
        }
        catch
        {
            return null;
        }
    }

    private static string? InferKind(string name, string? pnpClass)
    {
        var n = name.ToLowerInvariant();
        if (n.Contains("controller") || n.Contains("gamepad") || n.Contains("xbox") ||
            n.Contains("dualshock") || n.Contains("dualsense") || n.Contains("joy-con"))
            return "Controller";
        if (n.Contains("mouse") || pnpClass is "Mouse")
            return "Mouse";
        if (n.Contains("keyboard") || pnpClass is "Keyboard")
            return "Keyboard";
        if (n.Contains("headset") || n.Contains("headphone") || n.Contains("earbuds"))
            return "Audio";
        return pnpClass;
    }

    private static string? InferVendor(string name)
    {
        var n = name.ToLowerInvariant();
        if (n.Contains("xbox") || n.Contains("microsoft")) return "Microsoft";
        if (n.Contains("dualshock") || n.Contains("dualsense") || n.Contains("sony") || n.Contains("playstation"))
            return "Sony";
        if (n.Contains("logitech")) return "Logitech";
        if (n.Contains("razer")) return "Razer";
        if (n.Contains("steelseries")) return "SteelSeries";
        if (n.Contains("nintendo") || n.Contains("joy-con")) return "Nintendo";
        return null;
    }
}
