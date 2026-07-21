using System.Runtime.InteropServices;

namespace BatteryHUD.Services;

public static class BatteryProviderFactory
{
    public static IBatteryDeviceProvider Create()
    {
        if (RuntimeInformation.IsOSPlatform(OSPlatform.Windows))
            return new WindowsWmiBatteryProvider();

        if (RuntimeInformation.IsOSPlatform(OSPlatform.Linux))
        {
            return new CompositeBatteryProvider(
                new LinuxUpowerBatteryProvider(),
                new LinuxBluezBatteryProvider(),
                new LinuxSysfsBatteryProvider());
        }

        if (RuntimeInformation.IsOSPlatform(OSPlatform.OSX))
            return new MacBatteryProvider();

        return new CompositeBatteryProvider(
            new LinuxUpowerBatteryProvider(),
            new LinuxBluezBatteryProvider(),
            new LinuxSysfsBatteryProvider());
    }
}
