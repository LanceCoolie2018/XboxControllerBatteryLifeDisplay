using System.Diagnostics.CodeAnalysis;
using System.Runtime.InteropServices;
using System.Runtime.Versioning;
using System.Text.RegularExpressions;
using BatteryHUD.Models;

namespace BatteryHUD.Services;

/// <summary>
/// Windows provider with a light query path.
/// Full PnP + GetDeviceProperties on every device every poll is expensive,
/// throws ManagementException ("Generic failure") on unsupported devices
/// (first-chance noise in VS), and can make Bluetooth stacks look flaky —
/// we narrow the WMI set, only re-probe known battery devices on light polls,
/// and blacklist devices whose property probe fails or has no battery key.
/// </summary>
public sealed class WindowsWmiBatteryProvider : IBatteryDeviceProvider
{
    private const string BluetoothBatteryLevelKey = "{104EA319-6EE2-4701-BD47-8DDBF425BBE5} 2";

    /// <summary>How often (in deep scans) to retry devices that previously failed property probe.</summary>
    private const int SkipListRetryDeepScans = 12;

    private readonly object _gate = new();
    private readonly HashSet<string> _knownBatteryIds = new(StringComparer.OrdinalIgnoreCase);
    /// <summary>
    /// Peripheral device IDs we list even without a battery % (re-listed on light polls).
    /// </summary>
    private readonly HashSet<string> _listedPeripheralIds = new(StringComparer.OrdinalIgnoreCase);
    /// <summary>
    /// Device IDs where GetDeviceProperties threw or returned no battery property.
    /// Avoid re-invoking WMI on them every poll (ManagementException spam).
    /// </summary>
    private readonly HashSet<string> _skipProbeIds = new(StringComparer.OrdinalIgnoreCase);
    private int _pollCount;
    private int _deepScanCount;
    private bool _loggedWmiQueryFailure;

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
        HashSet<string> skip;
        HashSet<string> listedPeripherals;
        bool deepScan;
        lock (_gate)
        {
            poll = ++_pollCount;
            // Every 5th poll (~15s at 3s interval): broader discovery.
            // Other polls: re-check known battery devices + re-list known peripherals.
            deepScan = poll == 1 || poll % 5 == 0;
            if (deepScan)
            {
                _deepScanCount++;
                // Periodically allow re-probe of previously unsupported devices
                // (driver updates / reconnect can start exposing battery keys).
                if (_deepScanCount > 1 && _deepScanCount % SkipListRetryDeepScans == 0)
                    _skipProbeIds.Clear();
            }

            known = new HashSet<string>(_knownBatteryIds, StringComparer.OrdinalIgnoreCase);
            skip = new HashSet<string>(_skipProbeIds, StringComparer.OrdinalIgnoreCase);
            listedPeripherals = new HashSet<string>(_listedPeripheralIds, StringComparer.OrdinalIgnoreCase);
        }

        try
        {
            var query = deepScan
                ? @"SELECT Name, DeviceID, PNPDeviceID, Status, PNPClass, ConfigManagerErrorCode, Present FROM Win32_PnPEntity
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
                : @"SELECT Name, DeviceID, PNPDeviceID, Status, PNPClass, ConfigManagerErrorCode, Present FROM Win32_PnPEntity
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

                    // Status=OK alone is not enough: paired BT shells often stay OK with
                    // a cached battery % after the controller is powered off.
                    var statusOk = string.Equals(status, "OK", StringComparison.OrdinalIgnoreCase);
                    var cmError = 0u;
                    try
                    {
                        if (obj["ConfigManagerErrorCode"] is not null)
                            cmError = Convert.ToUInt32(obj["ConfigManagerErrorCode"]);
                    }
                    catch { /* ignore bad field */ }

                    var pnpPresent = true;
                    try
                    {
                        if (obj["Present"] is not null)
                            pnpPresent = Convert.ToBoolean(obj["Present"]);
                    }
                    catch { /* ignore */ }

                    // Light poll: re-read known battery devices; re-list known peripherals.
                    // Deep scan: probe new candidates (skip list avoids GetDeviceProperties spam).
                    var isKnownBattery = known.Contains(deviceId);
                    var isListedPeripheral = listedPeripherals.Contains(deviceId);
                    var looksPeripheral =
                        pnpClass is "Bluetooth" or "HIDClass" or "Mouse" or "Keyboard" ||
                        LooksLikePeripheral(name);

                    bool shouldProbe;
                    if (isKnownBattery)
                        shouldProbe = true;
                    else if (!deepScan)
                        shouldProbe = false;
                    else if (skip.Contains(deviceId))
                        shouldProbe = false;
                    else
                        shouldProbe = looksPeripheral;

                    int? percent = null;
                    bool? devNodeConnected = null;
                    if (shouldProbe)
                    {
                        (percent, devNodeConnected) = TryReadBatteryAndConnection(obj);
                        if (percent is not null)
                        {
                            lock (_gate)
                            {
                                _knownBatteryIds.Add(deviceId!);
                                _listedPeripheralIds.Add(deviceId!);
                                _skipProbeIds.Remove(deviceId!);
                            }
                        }
                        else if (!isKnownBattery)
                        {
                            // No battery key or InvokeMethod failed — do not call again every poll.
                            lock (_gate)
                                _skipProbeIds.Add(deviceId!);
                        }
                    }

                    // List Bluetooth/HID peripherals even when Windows never reports %.
                    // (Tester report: paired BT device missing from Switch list entirely.)
                    var includeWithoutBattery = looksPeripheral || isListedPeripheral || isKnownBattery;
                    if (percent is null && !includeWithoutBattery)
                        continue;

                    if (includeWithoutBattery)
                    {
                        lock (_gate)
                            _listedPeripheralIds.Add(deviceId!);
                    }

                    // Presence: PnP working + no CM error + Present flag, and when
                    // DEVPKEY_Device_IsConnected is available it must not be false.
                    var isPresent = statusOk && cmError == 0 && pnpPresent;
                    if (devNodeConnected == false)
                        isPresent = false;

                    var address = TryExtractBtAddress(deviceId!);

                    results.Add(new BatteryDevice
                    {
                        Id = deviceId!,
                        Name = name!.Trim(),
                        Kind = InferKind(name!, pnpClass),
                        Percent = percent,
                        IsPresent = isPresent,
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
        catch (System.Management.ManagementException ex)
        {
            // Whole-query WMI glitch — rethrow so the monitor keeps sticky presence
            // instead of treating an empty list as a real disconnect (UR-disconnect).
            // Per-device GetDeviceProperties failures are already skip-listed above.
            if (!_loggedWmiQueryFailure)
            {
                _loggedWmiQueryFailure = true;
                FileLog.Warn($"WMI PnP query failed (further failures suppressed): {ex.Message}");
            }

            throw;
        }
        catch (Exception ex)
        {
            if (!_loggedWmiQueryFailure)
            {
                _loggedWmiQueryFailure = true;
                FileLog.Warn($"WMI enumerate failed (further failures suppressed): {ex.Message}");
            }

            // Same sticky-presence path as ManagementException
            throw;
        }

        return results
            .GroupBy(d => d.StableKey, StringComparer.OrdinalIgnoreCase)
            .Select(g => g
                .OrderByDescending(d => d.Percent.HasValue)
                .ThenByDescending(d => d.IsPresent)
                .First())
            .OrderBy(d => d.Name, StringComparer.OrdinalIgnoreCase)
            .ToList();
    }

    /// <summary>
    /// DEVPKEY_Device_IsConnected — false when the BT/HID link is down even if a
    /// cached battery level property is still readable.
    /// </summary>
    private const string DeviceIsConnectedKey = "{83DA6326-97A6-4088-9453-A1923F573B29} 15";

    [SupportedOSPlatform("windows")]
    private static (int? Percent, bool? IsConnected) TryReadBatteryAndConnection(
        System.Management.ManagementObject obj)
    {
        try
        {
            var outParams = obj.InvokeMethod("GetDeviceProperties", null, null);
            if (outParams?["deviceProperties"] is not System.Management.ManagementBaseObject[] properties)
                return (null, null);

            int? percent = null;
            bool? isConnected = null;

            foreach (var prop in properties)
            {
                var keyName = prop["KeyName"]?.ToString();
                if (keyName is null) continue;

                if (keyName.Equals(DeviceIsConnectedKey, StringComparison.OrdinalIgnoreCase) ||
                    (keyName.Contains("IsConnected", StringComparison.OrdinalIgnoreCase) &&
                     !keyName.Contains("Battery", StringComparison.OrdinalIgnoreCase)))
                {
                    try
                    {
                        var data = prop["Data"];
                        if (data is bool b)
                            isConnected = b;
                        else if (data is not null)
                            isConnected = Convert.ToBoolean(data);
                    }
                    catch { /* ignore */ }

                    continue;
                }

                var isBatteryKey =
                    keyName.Equals(BluetoothBatteryLevelKey, StringComparison.OrdinalIgnoreCase) ||
                    (keyName.Contains("Battery", StringComparison.OrdinalIgnoreCase) &&
                     (keyName.Contains("Level", StringComparison.OrdinalIgnoreCase) ||
                      keyName.Contains("Percent", StringComparison.OrdinalIgnoreCase)));

                if (!isBatteryKey || percent is not null) continue;

                var batteryData = prop["Data"];
                if (batteryData is null) continue;

                try
                {
                    var value = Convert.ToInt32(batteryData);
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
                    // ignore bad property data
                }
            }

            // Invoke succeeded; null percent → caller will skip future probes.
            return (percent, isConnected);
        }
        catch (System.Management.ManagementException)
        {
            // Common: device does not support GetDeviceProperties → "Generic failure".
            // Caller blacklists the id so we do not re-throw every poll (VS first-chance spam).
            return (null, null);
        }
        catch
        {
            return (null, null);
        }
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
