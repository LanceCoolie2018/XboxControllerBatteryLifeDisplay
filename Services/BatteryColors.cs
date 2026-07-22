using Avalonia.Media;
using BatteryHUD.Models;

namespace BatteryHUD.Services;

public static class BatteryColors
{
    public static IBrush ForPercent(int? percent, int lowThreshold, bool disconnected)
    {
        if (disconnected || percent is null)
            return Brush("#FF5252"); // red

        // Green/yellow/orange traffic-light palette (preferred over solid blue).
        return percent.Value switch
        {
            var p when p <= lowThreshold => Brush("#FF1744"),
            var p when p <= 30 => Brush("#FF9100"),
            var p when p <= 70 => Brush("#FFD600"),
            _ => Brush("#00E676")
        };
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
