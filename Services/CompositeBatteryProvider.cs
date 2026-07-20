using BatteryHUD.Models;

namespace BatteryHUD.Services;

/// <summary>
/// Merges several providers and de-dupes by StableKey (address/name).
/// Prefers entries that have a battery percentage.
/// </summary>
public sealed class CompositeBatteryProvider : IBatteryDeviceProvider
{
    private readonly IBatteryDeviceProvider[] _providers;

    public CompositeBatteryProvider(params IBatteryDeviceProvider[] providers)
    {
        _providers = providers;
        PlatformName = string.Join(" + ", providers.Select(p => p.PlatformName));
    }

    public string PlatformName { get; }

    public IReadOnlyList<BatteryDevice> GetDevices()
    {
        var all = new List<BatteryDevice>();
        foreach (var provider in _providers)
        {
            try
            {
                all.AddRange(provider.GetDevices());
            }
            catch
            {
                // one provider failing must not kill the rest
            }
        }

        return all
            .Where(d => d.Percent is not null)
            .GroupBy(d => d.StableKey, StringComparer.OrdinalIgnoreCase)
            .Select(MergeGroup)
            .Where(d => d.Percent is not null)
            .OrderBy(d => d.Name, StringComparer.OrdinalIgnoreCase)
            .ToList();
    }

    private static BatteryDevice MergeGroup(IGrouping<string, BatteryDevice> group)
    {
        // Prefer: present + freshest percent
        var best = group
            .OrderByDescending(d => d.IsPresent)
            .ThenByDescending(d => d.IsCharging)
            .ThenByDescending(d => d.Percent ?? -1)
            .First();

        var anyPresent = group.Any(d => d.IsPresent);
        var percent = group.Select(d => d.Percent).FirstOrDefault(p => p.HasValue) ?? best.Percent;
        var charging = group.Any(d => d.IsCharging);
        var address = group.Select(d => d.Address).FirstOrDefault(a => !string.IsNullOrEmpty(a));
        var kind = group.Select(d => d.Kind).FirstOrDefault(k => !string.IsNullOrEmpty(k));

        return best with
        {
            Percent = percent,
            IsPresent = anyPresent,
            IsCharging = charging,
            Address = address ?? best.Address,
            Kind = kind ?? best.Kind
        };
    }
}
