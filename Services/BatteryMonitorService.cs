using BatteryHUD.Models;

namespace BatteryHUD.Services;

/// <summary>
/// Polls the platform provider and tracks the user-selected device.
/// Lists paired/connected peripherals even when Windows never reports a
/// battery percentage (shown as "Battery not reported" in the UI).
/// Disconnects on the first successful miss / IsPresent=false; (re)connects
/// only after consecutive present polls — including first sightings.
/// Provider hard-failures leave presence unchanged within the grace window.
/// </summary>
public sealed class BatteryMonitorService : IDisposable
{
    /// <summary>
    /// How many consecutive polls must report the device present before we
    /// flip offline → online (including first sightings).
    /// </summary>
    private const int ReconnectConfirmPolls = 2;

    private readonly IBatteryDeviceProvider _provider;
    private readonly object _gate = new();
    private readonly Dictionary<string, TrackedDevice> _tracked = new(StringComparer.Ordinal);
    private string? _selectedId;
    private Timer? _timer;
    private readonly int _pollMs;
    private readonly TimeSpan _grace;

    public event EventHandler? Updated;

    public BatteryMonitorService(IBatteryDeviceProvider provider, AppSettings settings)
    {
        _provider = provider;
        _selectedId = settings.SelectedDeviceId;
        _pollMs = Math.Clamp(settings.PollIntervalMs, 500, 60_000);
        _grace = TimeSpan.FromSeconds(Math.Clamp(settings.DeviceGraceSeconds, 5, 300));
    }

    public string PlatformName => _provider.PlatformName;

    /// <summary>All tracked peripherals (with or without a battery %).</summary>
    public IReadOnlyList<BatteryDevice> Devices
    {
        get
        {
            lock (_gate)
                return _tracked.Values
                    .Select(t => t.Device)
                    .OrderBy(d => d.Name, StringComparer.OrdinalIgnoreCase)
                    .ToList();
        }
    }

    public BatteryDevice? Selected
    {
        get
        {
            lock (_gate)
            {
                var match = FindDeviceLocked(_selectedId);
                if (match is not null)
                    return match;

                var all = _tracked.Values.Select(t => t.Device).ToList();
                if (all.Count == 0) return null;

                // Prefer a present controller that reports %, then any present device.
                return all.FirstOrDefault(d => d.Kind == "Controller" && d.IsPresent && d.Percent is not null)
                       ?? all.FirstOrDefault(d => d.IsPresent && d.Percent is not null)
                       ?? all.FirstOrDefault(d => d.Kind == "Controller" && d.IsPresent)
                       ?? all.FirstOrDefault(d => d.IsPresent)
                       ?? all.FirstOrDefault();
            }
        }
    }

    /// <summary>
    /// Resolve a stored id/stable key to a tracked device.
    /// Does not auto-pick — used by multi-widget overlays.
    /// </summary>
    public BatteryDevice? FindDevice(string? id)
    {
        lock (_gate)
            return FindDeviceLocked(id);
    }

    private BatteryDevice? FindDeviceLocked(string? id)
    {
        if (string.IsNullOrEmpty(id))
            return null;

        if (_tracked.TryGetValue(id, out var exact))
            return exact.Device;

        var all = _tracked.Values.Select(t => t.Device).ToList();
        return all.FirstOrDefault(d =>
            string.Equals(d.StableKey, id, StringComparison.OrdinalIgnoreCase) ||
            string.Equals(d.Id, id, StringComparison.OrdinalIgnoreCase) ||
            (!string.IsNullOrEmpty(d.Address) &&
             id.Contains(d.Address, StringComparison.OrdinalIgnoreCase)));
    }

    public string? SelectedDeviceId
    {
        get { lock (_gate) return _selectedId; }
        set
        {
            lock (_gate) _selectedId = value;
            Refresh();
        }
    }

    public void Start()
    {
        Refresh();
        _timer = new Timer(_ =>
        {
            try { Refresh(); }
            catch { /* never crash the timer */ }
        }, null, _pollMs, _pollMs);
    }

    public void Refresh()
    {
        List<BatteryDevice> snapshot;
        bool providerHardFail;
        try
        {
            snapshot = _provider.GetDevices().ToList();
            providerHardFail = false;
        }
        catch
        {
            providerHardFail = true;
            snapshot = [];
        }

        var now = DateTimeOffset.UtcNow;

        lock (_gate)
        {
            if (providerHardFail)
            {
                foreach (var t in _tracked.Values)
                {
                    if (t.Device.IsPresent && now - t.LastSeen > _grace)
                        MarkAbsent(t);
                }

                PruneExpired(now);
            }
            else if (snapshot.Count == 0 && _tracked.Count > 0)
            {
                foreach (var t in _tracked.Values)
                    MarkAbsent(t);
                PruneExpired(now);
            }
            else
            {
                var seenIds = new HashSet<string>(StringComparer.Ordinal);

                foreach (var device in snapshot)
                {
                    var key = device.Id;
                    seenIds.Add(key);

                    if (_tracked.TryGetValue(key, out var existing))
                    {
                        // Prefer fresh percent; keep last known when this poll has none
                        var percent = device.Percent ?? existing.Device.Percent;
                        ApplyObservation(existing, device with { Percent = percent }, now);
                    }
                    else
                    {
                        var byStable = _tracked.Values
                            .FirstOrDefault(t =>
                                !string.IsNullOrEmpty(device.StableKey) &&
                                string.Equals(t.Device.StableKey, device.StableKey, StringComparison.OrdinalIgnoreCase));

                        if (byStable is not null)
                        {
                            _tracked.Remove(byStable.Device.Id);
                            var percent = device.Percent ?? byStable.Device.Percent;
                            byStable.Device = byStable.Device with { Id = key };
                            ApplyObservation(byStable, device with { Percent = percent }, now);
                            _tracked[key] = byStable;
                        }
                        else
                        {
                            // First sighting: require confirm polls before "connected"
                            var tracked = new TrackedDevice
                            {
                                Device = device with { IsPresent = false, IsCharging = false },
                                LastSeen = now - _grace,
                                PresentStreak = 0
                            };
                            if (device.IsPresent)
                                ApplyObservation(tracked, device, now);
                            _tracked[key] = tracked;
                        }
                    }
                }

                foreach (var kv in _tracked.ToList())
                {
                    if (seenIds.Contains(kv.Key))
                        continue;

                    MarkAbsent(kv.Value);
                    if (now - kv.Value.LastSeen > _grace)
                        _tracked.Remove(kv.Key);
                }
            }
        }

        Updated?.Invoke(this, EventArgs.Empty);
    }

    private static void ApplyObservation(TrackedDevice tracked, BatteryDevice observed, DateTimeOffset now)
    {
        // Preserve last known % when this observation has none (still listed)
        var percent = observed.Percent ?? tracked.Device.Percent;
        // But if provider explicitly listed the device without ever having %, keep null
        if (observed.Percent is null && tracked.Device.Percent is null)
            percent = null;
        // If we had a % and this poll doesn't, keep last for battery devices
        if (observed.Percent is null && tracked.Device.Percent is not null)
            percent = tracked.Device.Percent;

        if (!observed.IsPresent)
        {
            MarkAbsent(tracked, percent, observed);
            return;
        }

        if (tracked.Device.IsPresent)
        {
            tracked.PresentStreak = Math.Min(tracked.PresentStreak + 1, ReconnectConfirmPolls);
            tracked.LastSeen = now;
            tracked.Device = observed with
            {
                Percent = observed.Percent ?? percent,
                IsPresent = true
            };
            return;
        }

        tracked.PresentStreak++;
        if (tracked.PresentStreak >= ReconnectConfirmPolls)
        {
            tracked.LastSeen = now;
            tracked.Device = observed with
            {
                Percent = observed.Percent ?? percent,
                IsPresent = true
            };
        }
        else
        {
            tracked.Device = tracked.Device with
            {
                Percent = observed.Percent ?? percent,
                IsPresent = false,
                Name = observed.Name,
                Kind = observed.Kind ?? tracked.Device.Kind,
                Address = observed.Address ?? tracked.Device.Address,
                IsCharging = false
            };
        }
    }

    private static void MarkAbsent(TrackedDevice tracked, int? percent = null, BatteryDevice? observed = null)
    {
        tracked.PresentStreak = 0;
        tracked.Device = tracked.Device with
        {
            Percent = percent ?? tracked.Device.Percent,
            IsPresent = false,
            IsCharging = false,
            Name = observed?.Name ?? tracked.Device.Name,
            Kind = observed?.Kind ?? tracked.Device.Kind,
            Address = observed?.Address ?? tracked.Device.Address
        };
    }

    private void PruneExpired(DateTimeOffset now)
    {
        foreach (var kv in _tracked.ToList())
        {
            if (now - kv.Value.LastSeen > _grace)
                _tracked.Remove(kv.Key);
        }
    }

    public void Dispose()
    {
        _timer?.Dispose();
        _timer = null;
    }

    private sealed class TrackedDevice
    {
        public required BatteryDevice Device { get; set; }
        public DateTimeOffset LastSeen { get; set; }
        public int PresentStreak { get; set; }
    }
}
