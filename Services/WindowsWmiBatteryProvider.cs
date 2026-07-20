using System.Diagnostics.CodeAnalysis;
using System.Runtime.InteropServices;
using System.Runtime.Versioning;
using System.Text.RegularExpressions;
using BatteryHUD.Models;

namespace BatteryHUD.Services;

/// <summary>
/// Windows provider with a light query path.
/// Full PnP + GetDeviceProperties on every device every poll is expensive and
/// can make Bluetooth stacks look flaky — we narrow the WMI set and cache
/// which devices have ever reported a battery.
/// </summary>
public sealed class WindowsWmiBatteryProvider : IBatteryDeviceProvider
{
    private const string BluetoothBatteryLevelKey = "{104EA319-6EE2-4701-BD47-8DDBF425BBE5} 2";

    private readonly object _gate = new();
    private readonly HashSet<string> _knownBatteryIds = new(StringComparer.OrdinalIgnoreCase);
    private int _pollCount;

    public string PlatformName => "Windows (WMI/PnP)";

    public IReadOnlyList<BatteryDevice> GetDevices()
    {
        if (!RuntimeInformation.IsOSPlatform(OSPlatform.Windows))
            return Array.Empty<BatteryDevice>();

        return Enumerate();
    }

    [SupportedOSPlatform("windows")]
    [UnconditionalSuppressMessage("Interoperability", "CA1416", Justification = "Guarded by OSPlatform.Windows.")]
    private IReadOnlyList<BatteryDevice> Enumerate()
    {
        var results = new List<BatteryDevice>();
        int poll;
        HashSet<string> known;
        lock (_gate)
        {
            poll = ++_pollCount;
            known = new HashSet<string>(_knownBatteryIds, StringComparer.OrdinalIgnoreCase);
        }

        // Every 5th poll (~15s at 3s interval): broader discovery.
        // Other polls: only re-check known battery devices + obvious peripherals.
        var deepScan = poll == 1 || poll % 5 == 0;

        try
        {
            var query = deepScan
                ? @"SELECT Name, DeviceID, PNPDeviceID, Status, PNPClass FROM Win32_PnPEntity
                    WHERE Name IS NOT NULL AND (
                        PNPClass = 'Bluetooth' OR PNPClass = 'HIDClass' OR
                        PNPClass = 'Mouse' OR PNPClass = 'Keyboard' OR
                        PNPClass = 'Camera' OR PNPClass = 'AudioEndpoint' OR
                        Name LIKE '%Xbox%' OR Name LIKE '%Controller%' OR
                        Name LIKE '%DualShock%' OR Name LIKE '%DualSense%' OR
                        Name LIKE '%Wireless%' OR Name LIKE '%Gamepad%' OR
                        Name LIKE '%Headset%' OR Name LIKE '%Mouse%' OR
                        Name LIKE '%Keyboard%'
                    )"
                : @"SELECT Name, DeviceID, PNPDeviceID, Status, PNPClass FROM Win32_PnPEntity
                    WHERE Name IS NOT NULL AND (
                        PNPClass = 'Bluetooth' OR PNPClass = 'HIDClass' OR
                        PNPClass = 'Mouse' OR PNPClass = 'Keyboard' OR
                        Name LIKE '%Xbox%' OR Name LIKE '%Controller%' OR
                        Name LIKE '%DualSense%' OR Name LIKE '%DualShock%' OR
                        Name LIKE '%Gamepad%'
                    )";

            using var searcher = new System.Management.ManagementObjectSearcher(@"root\CIMV2", query);

            foreach (System.Management.ManagementObject obj in searcher.Get())
            {
                using (obj)
                {
                    var deviceId = obj["DeviceID"]?.ToString() ?? obj["PNPDeviceID"]?.ToString();
                    var name = obj["Name"]?.ToString();
                    var status = obj["Status"]?.ToString();
                    var pnpClass = obj["PNPClass"]?.ToString();

                    if (string.IsNullOrWhiteSpace(name) || string.IsNullOrWhiteSpace(deviceId))
                        continue;

                    var isOk = string.Equals(status, "OK", StringComparison.OrdinalIgnoreCase);

                    // On light polls, only probe properties for known battery devices
                    // or high-value classes (still skip property hammer on huge lists)
                    var shouldProbe =
                        deepScan ||
                        known.Contains(deviceId) ||
                        pnpClass is "Bluetooth" or "Mouse" or "Keyboard" ||
                        LooksLikePeripheral(name);

                    int? percent = null;
                    if (shouldProbe)
                        percent = TryReadBatteryPercent(obj);

                    // Only list devices that actually report a charge percentage.
                    // No percent → ghost / noise (paired HID shells, radios, dongles).
                    if (percent is null)
                        continue;

                    lock (_gate)
                        _knownBatteryIds.Add(deviceId!);

                    var address = TryExtractBtAddress(deviceId!);

                    results.Add(new BatteryDevice
                    {
                        Id = deviceId!,
                        Name = name!.Trim(),
                        Kind = InferKind(name!, pnpClass),
                        Percent = percent,
                        IsPresent = isOk,
                        Address = address,
                        VendorHint = InferVendor(name!)
                    });
                }
            }
        }
        catch (PlatformNotSupportedException)
        {
            return Array.Empty<BatteryDevice>();
        }
        catch
        {
            // WMI glitch — return empty so monitor keeps sticky cache
        }

        return results
            .GroupBy(d => d.StableKey, StringComparer.OrdinalIgnoreCase)
            .Select(g => g.OrderByDescending(d => d.Percent.HasValue).ThenByDescending(d => d.IsPresent).First())
            .OrderBy(d => d.Name, StringComparer.OrdinalIgnoreCase)
            .ToList();
    }

    [SupportedOSPlatform("windows")]
    private static int? TryReadBatteryPercent(System.Management.ManagementObject obj)
    {
        try
        {
            var outParams = obj.InvokeMethod("GetDeviceProperties", null, null);
            if (outParams?["deviceProperties"] is not System.Management.ManagementBaseObject[] properties)
                return null;

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
                        return value switch
                        {
                            0 => 5,
                            1 => 25,
                            2 => 55,
                            3 => 100,
                            _ => value
                        };
                    }

                    if (value is >= 0 and <= 100)
                        return value;
                }
                catch
                {
                    // ignore
                }
            }
        }
        catch
        {
            // GetDeviceProperties unsupported / transient failure
        }

        return null;
    }

    private static bool LooksLikePeripheral(string name)
    {
        var n = name.ToLowerInvariant();
        return n.Contains("controller") || n.Contains("gamepad") || n.Contains("xbox") ||
               n.Contains("dualshock") || n.Contains("dualsense") || n.Contains("joy-con") ||
               n.Contains("mouse") || n.Contains("keyboard") || n.Contains("headset") ||
               n.Contains("headphone") || n.Contains("earbuds") || n.Contains("protoarc") ||
               n.Contains("logitech") || n.Contains("razer") || n.Contains("wireless");
    }

    private static string? TryExtractBtAddress(string deviceId)
    {
        // Common forms: BTHENUM\..._DEV_VID...&ADDRESS_EB CFA9...
        var m = Regex.Match(deviceId, @"([0-9A-Fa-f]{2}[:_\-]?){5}[0-9A-Fa-f]{2}");
        if (!m.Success) return null;
        var raw = Regex.Replace(m.Value, @"[^0-9A-Fa-f]", "");
        if (raw.Length != 12) return null;
        return string.Join(":", Enumerable.Range(0, 6).Select(i => raw.Substring(i * 2, 2))).ToUpperInvariant();
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
        if (pnpClass is "Bluetooth") return "Bluetooth";
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
        if (n.Contains("protoarc")) return "ProtoArc";
        return null;
    }
}
