using BatteryHUD.Models;

namespace BatteryHUD.Services;

/// <summary>
/// Merges several providers and de-dupes by StableKey (address/name).
/// Prefers entries that have a battery percentage.
/// Presence is consensus (offline wins) so a BlueZ disconnect is not
/// masked by stale UPower/sysfs "present" + cached %.
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

        // Addresses / names BlueZ (etc.) reports as disconnected — used to veto
        // ghosts whose StableKey is name-based and would not merge with addr: keys
        // (sysfs often has % + is-present but no MAC).
        var offlineAddresses = new HashSet<string>(
            all.Where(d => !d.IsPresent && !string.IsNullOrWhiteSpace(d.Address))
               .Select(d => NormalizeAddress(d.Address!)),
            StringComparer.OrdinalIgnoreCase);

        var offlineNames = new HashSet<string>(
            all.Where(d => !d.IsPresent && !string.IsNullOrWhiteSpace(d.Name))
               .Select(d => NormalizeName(d.Name)),
            StringComparer.OrdinalIgnoreCase);

        // Keep null-% offline markers (BlueZ paired-but-disconnected) in the
        // group so they can veto stale UPower/sysfs "present" readings.
        return all
            .Where(d => d.Percent is not null || !d.IsPresent)
            .GroupBy(d => d.StableKey, StringComparer.OrdinalIgnoreCase)
            .Select(MergeGroup)
            .Where(d => d.Percent is not null)
            .Select(d =>
            {
                if (!d.IsPresent)
                    return d;

                if (IsVetoedOffline(d, offlineAddresses, offlineNames))
                    return d with { IsPresent = false, IsCharging = false };

                return d;
            })
            .OrderBy(d => d.Name, StringComparer.OrdinalIgnoreCase)
            .ToList();
    }

    private static bool IsVetoedOffline(
        BatteryDevice d,
        HashSet<string> offlineAddresses,
        HashSet<string> offlineNames)
    {
        if (!string.IsNullOrWhiteSpace(d.Address) &&
            offlineAddresses.Contains(NormalizeAddress(d.Address!)))
            return true;

        // Address embedded only in Id (legacy sysfs without Address filled)
        if (offlineAddresses.Count > 0 && !string.IsNullOrWhiteSpace(d.Id))
        {
            var idNorm = NormalizeAddress(d.Id);
            foreach (var addr in offlineAddresses)
            {
                if (addr.Length >= 12 && idNorm.Contains(addr, StringComparison.OrdinalIgnoreCase))
                    return true;
            }
        }

        if (offlineNames.Contains(NormalizeName(d.Name)))
            return true;

        // Fuzzy name: "Xbox Wireless Controller" vs "Wireless Controller" etc.
        // Require a long substring so short names ("mouse") cannot veto unrelated devices.
        var name = NormalizeName(d.Name);
        if (name.Length >= 8)
        {
            foreach (var offline in offlineNames)
            {
                if (offline.Length < 8)
                    continue;
                if (name.Contains(offline, StringComparison.Ordinal) ||
                    offline.Contains(name, StringComparison.Ordinal))
                    return true;
            }
        }

        return false;
    }

    private static string NormalizeAddress(string address) =>
        address.Replace(":", "", StringComparison.Ordinal)
               .Replace("-", "", StringComparison.Ordinal)
               .Replace("_", "", StringComparison.Ordinal)
               .ToUpperInvariant();

    private static string NormalizeName(string name) =>
        name.Trim().ToLowerInvariant();

    private static BatteryDevice MergeGroup(IGrouping<string, BatteryDevice> group)
    {
        // Prefer a row that has a real % for display identity; offline markers
        // only vote on presence.
        var best = group
            .OrderByDescending(d => d.Percent.HasValue)
            .ThenByDescending(d => d.IsPresent)
            .ThenByDescending(d => d.IsCharging)
            .ThenByDescending(d => d.Percent ?? -1)
            .First();

        // Offline wins: BlueZ Connected=false (including null-% markers) must not
        // be overridden by stale UPower/sysfs is-present + cached %.
        var isPresent = group.All(d => d.IsPresent);
        var percent = group.Select(d => d.Percent).FirstOrDefault(p => p.HasValue) ?? best.Percent;
        var charging = isPresent && group.Any(d => d.IsCharging);
        var address = group.Select(d => d.Address).FirstOrDefault(a => !string.IsNullOrEmpty(a));
        var kind = group.Select(d => d.Kind).FirstOrDefault(k => !string.IsNullOrEmpty(k));
        var name = group
            .Where(d => d.Percent is not null)
            .Select(d => d.Name)
            .FirstOrDefault(n => !string.IsNullOrWhiteSpace(n)) ?? best.Name;

        return best with
        {
            Name = name,
            Percent = percent,
            IsPresent = isPresent,
            IsCharging = charging,
            Address = address ?? best.Address,
            Kind = kind ?? best.Kind
        };
    }
}
