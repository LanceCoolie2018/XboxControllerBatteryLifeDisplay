using BatteryHUD.Models;

namespace BatteryHUD.Services;

/// <summary>
/// Platform-specific source of battery-reporting devices.
/// </summary>
public interface IBatteryDeviceProvider
{
    string PlatformName { get; }

    /// <summary>
    /// Enumerate devices that currently report battery information.
    /// Safe to call frequently; should not throw for empty results.
    /// </summary>
    IReadOnlyList<BatteryDevice> GetDevices();
}
