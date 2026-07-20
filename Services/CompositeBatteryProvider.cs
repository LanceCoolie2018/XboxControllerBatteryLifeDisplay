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
            .GroupBy(d => d.StableKey, StringComparer.OrdinalIgnoreCase)
            .Select(MergeGroup)
            .OrderBy(d => d.Name, StringComparer.OrdinalIgnoreCase)
            .ToList();
    }

    private static BatteryDevice MergeGroup(IGrouping<string, BatteryDevice> group)
    {
        // Prefer: has percent > is present > first
        var best = group
            .OrderByDescending(d => d.Percent.HasValue)
            .ThenByDescending(d => d.IsPresent)
            .ThenByDescending(d => d.IsCharging)
            .First();

        // Fill gaps from siblings
        var anyPresent = group.Any(d => d.IsPresent);
        var percent = group.Select(d => d.Percent).FirstOrDefault(p => p.HasValue);
        var charging = group.Any(d => d.IsCharging);
        var address = group.Select(d => d.Address).FirstOrDefault(a => !string.IsNullOrEmpty(a));
        var kind = group.Select(d => d.Kind).FirstOrDefault(k => !string.IsNullOrEmpty(k));

        return best with
        {
            Percent = percent ?? best.Percent,
            IsPresent = anyPresent,
            IsCharging = charging,
            Address = address ?? best.Address,
            Kind = kind ?? best.Kind
        };
    }
}
