using Avalonia.Media;
using BatteryHUD.Models;

namespace BatteryHUD.Services;

public static class BatteryColors
{
    /// <param name="lowThreshold">Reserved for call-site compatibility; low battery uses opacity pulse.</param>
    public static IBrush ForPercent(int? percent, int lowThreshold, bool disconnected)
    {
        if (disconnected || percent is null)
            return Brush("#FF5252"); // red

        // Blue reads more clearly than green/yellow on the dark overlay.
        return Brush("#42A5F5");
    }

    public static string LabelFor(BatteryDevice? device, int lowThreshold)
    {
        if (device is null)
            return "No device";
        if (!device.IsPresent)
            return "Disconnected";
        if (device.Percent is null)
            return "Battery ?";
        if (device.Percent <= lowThreshold)
            return $"LOW {device.Percent}%";
        return device.StatusText;
    }

    private static IBrush Brush(string hex) =>
        new SolidColorBrush(Color.Parse(hex));
}
