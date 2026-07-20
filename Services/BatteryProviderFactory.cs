using System.Runtime.InteropServices;

namespace BatteryHUD.Services;

public static class BatteryProviderFactory
{
    public static IBatteryDeviceProvider Create()
    {
        if (RuntimeInformation.IsOSPlatform(OSPlatform.Windows))
            return new WindowsWmiBatteryProvider();
        if (RuntimeInformation.IsOSPlatform(OSPlatform.Linux))
            return new LinuxUpowerBatteryProvider();
        if (RuntimeInformation.IsOSPlatform(OSPlatform.OSX))
            return new MacBatteryProvider();

        // Fallback: try Linux-style tools, else empty
        return new LinuxUpowerBatteryProvider();
    }
}
