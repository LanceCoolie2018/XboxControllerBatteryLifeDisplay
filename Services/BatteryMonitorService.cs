using BatteryHUD.Models;

namespace BatteryHUD.Services;

/// <summary>
/// Polls the platform provider and tracks the user-selected device.
/// Keeps recently-seen devices in the list for a grace period so flaky
/// Bluetooth/WMI polls don't make the picker flicker or drop the selection.
/// </summary>
public sealed class BatteryMonitorService : IDisposable
{
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
        // Stay visible for a while after a missed poll (BT sleep / WMI glitch)
        _grace = TimeSpan.FromSeconds(Math.Clamp(settings.DeviceGraceSeconds, 5, 300));
    }

    public string PlatformName => _provider.PlatformName;

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
                if (_tracked.Count == 0) return null;

                if (!string.IsNullOrEmpty(_selectedId))
                {
                    // Exact id
                    if (_tracked.TryGetValue(_selectedId, out var exact))
                        return exact.Device;

                    // Fuzzy: same stable key / name (Windows ids can shift)
                    var fuzzy = _tracked.Values
                        .Select(t => t.Device)
                        .FirstOrDefault(d =>
                            string.Equals(d.StableKey, _selectedId, StringComparison.OrdinalIgnoreCase) ||
                            string.Equals(d.Id, _selectedId, StringComparison.OrdinalIgnoreCase) ||
                            (!string.IsNullOrEmpty(d.Address) &&
                             _selectedId.Contains(d.Address, StringComparison.OrdinalIgnoreCase)));
                    if (fuzzy is not null)
                        return fuzzy;
                }

                return _tracked.Values.Select(t => t.Device).FirstOrDefault(d => d.Kind == "Controller")
                       ?? _tracked.Values.Select(t => t.Device).FirstOrDefault(d => d.IsPresent)
                       ?? _tracked.Values.Select(t => t.Device).FirstOrDefault();
            }
        }
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
        try
        {
            snapshot = _provider.GetDevices().ToList();
        }
        catch
        {
            // Provider failed hard — keep previous list, just age it
            snapshot = [];
        }

        var now = DateTimeOffset.UtcNow;
        var providerFailedEmpty = snapshot.Count == 0;

        lock (_gate)
        {
            if (providerFailedEmpty && _tracked.Count > 0)
            {
                // Don't wipe the list on a blank poll (common BT/WMI blip)
                foreach (var t in _tracked.Values)
                {
                    if (now - t.LastSeen > _grace)
                        continue;
                    // Mark soft-disconnected but keep entry + last %
                    t.Device = t.Device with { IsPresent = false };
                }
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
                        // Prefer fresh percent; if missing, keep last known
                        var percent = device.Percent ?? existing.Device.Percent;
                        existing.Device = device with
                        {
                            Percent = percent,
                            IsPresent = device.IsPresent
                        };
                        existing.LastSeen = now;
                    }
                    else
                    {
                        // Also merge if same StableKey under a new Id
                        var byStable = _tracked.Values
                            .FirstOrDefault(t =>
                                !string.IsNullOrEmpty(device.StableKey) &&
                                string.Equals(t.Device.StableKey, device.StableKey, StringComparison.OrdinalIgnoreCase));

                        if (byStable is not null)
                        {
                            _tracked.Remove(byStable.Device.Id);
                            var percent = device.Percent ?? byStable.Device.Percent;
                            _tracked[key] = new TrackedDevice
                            {
                                Device = device with { Percent = percent },
                                LastSeen = now
                            };
                        }
                        else
                        {
                            _tracked[key] = new TrackedDevice
                            {
                                Device = device,
                                LastSeen = now
                            };
                        }
                    }
                }

                // Devices not in this snapshot: keep during grace
                foreach (var kv in _tracked.ToList())
                {
                    if (seenIds.Contains(kv.Key))
                        continue;

                    if (now - kv.Value.LastSeen > _grace)
                    {
                        _tracked.Remove(kv.Key);
                    }
                    else
                    {
                        kv.Value.Device = kv.Value.Device with { IsPresent = false };
                    }
                }
            }
        }

        Updated?.Invoke(this, EventArgs.Empty);
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
    }
}
