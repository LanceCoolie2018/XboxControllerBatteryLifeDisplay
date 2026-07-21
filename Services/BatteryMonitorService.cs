using BatteryHUD.Models;

namespace BatteryHUD.Services;

/// <summary>
/// Polls the platform provider and tracks the user-selected device.
/// Only devices with a reported battery % are listed.
/// Keeps recently-seen (with %) devices through a short grace window so
/// flaky BT/WMI polls don't blank the HUD mid-game.
/// Disconnects on the first successful miss / IsPresent=false; (re)connects
/// only after consecutive present polls — including first sightings — so
/// stale BT/WMI/sysfs ghosts cannot flap or stick "connected" while the
/// controller is off. Provider hard-failures leave presence unchanged within
/// the grace window so brief WMI blips do not force a false disconnect.
/// </summary>
public sealed class BatteryMonitorService : IDisposable
{
    /// <summary>
    /// How many consecutive polls must report the device present before we
    /// flip offline → online (including first sightings).
    /// One successful poll is enough to go offline.
    /// At the default 3s interval this is ~6s of stable presence to (re)connect.
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
        // Stay visible for a while after a missed poll (BT sleep / WMI glitch)
        _grace = TimeSpan.FromSeconds(Math.Clamp(settings.DeviceGraceSeconds, 5, 300));
    }

    public string PlatformName => _provider.PlatformName;

    /// <summary>Devices that currently have (or recently had) a battery percentage.</summary>
    public IReadOnlyList<BatteryDevice> Devices
    {
        get
        {
            lock (_gate)
                return _tracked.Values
                    .Select(t => t.Device)
                    .Where(d => d.Percent is not null)
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
                var withPercent = _tracked.Values
                    .Select(t => t.Device)
                    .Where(d => d.Percent is not null)
                    .ToList();

                if (withPercent.Count == 0) return null;

                if (!string.IsNullOrEmpty(_selectedId))
                {
                    // Exact id
                    if (_tracked.TryGetValue(_selectedId, out var exact) &&
                        exact.Device.Percent is not null)
                        return exact.Device;

                    // Fuzzy: same stable key / name (Windows ids can shift)
                    var fuzzy = withPercent.FirstOrDefault(d =>
                        string.Equals(d.StableKey, _selectedId, StringComparison.OrdinalIgnoreCase) ||
                        string.Equals(d.Id, _selectedId, StringComparison.OrdinalIgnoreCase) ||
                        (!string.IsNullOrEmpty(d.Address) &&
                         _selectedId.Contains(d.Address, StringComparison.OrdinalIgnoreCase)));
                    if (fuzzy is not null)
                        return fuzzy;
                }

                return withPercent.FirstOrDefault(d => d.Kind == "Controller")
                       ?? withPercent.FirstOrDefault(d => d.IsPresent)
                       ?? withPercent.FirstOrDefault();
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
        bool providerHardFail;
        try
        {
            // Hard filter: never track devices without a %
            snapshot = _provider.GetDevices()
                .Where(d => d.Percent is not null)
                .ToList();
            providerHardFail = false;
        }
        catch
        {
            // Provider threw (e.g. WMI ManagementException) — keep prior presence/%
            // for a short window; do not treat a single throw as a disconnect.
            providerHardFail = true;
            snapshot = [];
        }

        var now = DateTimeOffset.UtcNow;

        lock (_gate)
        {
            // Drop any historical ghosts that somehow lack a percent
            foreach (var kv in _tracked.ToList())
            {
                if (kv.Value.Device.Percent is null)
                    _tracked.Remove(kv.Key);
            }

            if (providerHardFail)
            {
                // Sticky only within grace from last confirmed presence.
                // A long-lived WMI outage after a real power-off must not leave
                // the HUD saying "connected" forever.
                foreach (var t in _tracked.Values)
                {
                    if (t.Device.IsPresent && now - t.LastSeen > _grace)
                        MarkAbsent(t);
                }

                PruneExpired(now);
            }
            else if (snapshot.Count == 0 && _tracked.Count > 0)
            {
                // Successful empty poll: every tracked device is gone → disconnect now
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
                        // Prefer fresh percent; if missing, keep last known (still required)
                        var percent = device.Percent ?? existing.Device.Percent;
                        if (percent is null)
                        {
                            _tracked.Remove(key);
                            continue;
                        }

                        ApplyObservation(existing, device with { Percent = percent }, now);
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
                            if (percent is null)
                                continue;

                            // Preserve offline streak / last-seen across id churn
                            byStable.Device = byStable.Device with { Id = key };
                            ApplyObservation(byStable, device with { Percent = percent }, now);
                            _tracked[key] = byStable;
                        }
                        else
                        {
                            // First sighting (or reappear after grace prune): never
                            // trust a single present poll — WMI/UPower/sysfs often
                            // keep a cached % + "present" while the pad is off.
                            // Start offline and require ReconnectConfirmPolls.
                            var tracked = new TrackedDevice
                            {
                                Device = device with { IsPresent = false, IsCharging = false },
                                // Unconfirmed ghosts must not look "freshly seen present"
                                // or grace never expires while the pad stays off.
                                LastSeen = now - _grace,
                                PresentStreak = 0
                            };
                            if (device.IsPresent)
                                ApplyObservation(tracked, device, now);
                            _tracked[key] = tracked;
                        }
                    }
                }

                // Devices not in this snapshot: offline immediately, keep during grace only
                foreach (var kv in _tracked.ToList())
                {
                    if (seenIds.Contains(kv.Key))
                        continue;

                    if (kv.Value.Device.Percent is null)
                    {
                        _tracked.Remove(kv.Key);
                        continue;
                    }

                    MarkAbsent(kv.Value);
                    if (now - kv.Value.LastSeen > _grace)
                        _tracked.Remove(kv.Key);
                }
            }
        }

        Updated?.Invoke(this, EventArgs.Empty);
    }

    /// <summary>
    /// Merge a provider observation into a tracked device with disconnect-fast /
    /// reconnect-slow hysteresis so stale BT/WMI ghosts don't flap online.
    /// </summary>
    private static void ApplyObservation(TrackedDevice tracked, BatteryDevice observed, DateTimeOffset now)
    {
        var percent = observed.Percent ?? tracked.Device.Percent;

        if (!observed.IsPresent)
        {
            // Provider says offline → register disconnect immediately
            MarkAbsent(tracked, percent, observed);
            return;
        }

        // Provider says present
        if (tracked.Device.IsPresent)
        {
            // Already online: stay online, refresh reading + grace clock
            tracked.PresentStreak = Math.Min(tracked.PresentStreak + 1, ReconnectConfirmPolls);
            tracked.LastSeen = now;
            tracked.Device = observed with
            {
                Percent = percent,
                IsPresent = true
            };
            return;
        }

        // Currently offline — require consecutive present polls before flipping online.
        // Do NOT advance LastSeen on unconfirmed ghosts (would reset the grace timer).
        tracked.PresentStreak++;
        if (tracked.PresentStreak >= ReconnectConfirmPolls)
        {
            tracked.LastSeen = now;
            tracked.Device = observed with
            {
                Percent = percent,
                IsPresent = true
            };
        }
        else
        {
            // Keep offline UI; refresh % if the stack still has a cached reading
            tracked.Device = tracked.Device with
            {
                Percent = percent,
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
        // LastSeen stays at last *confirmed* presence so grace counts down correctly
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
            if (kv.Value.Device.Percent is null || now - kv.Value.LastSeen > _grace)
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
        /// <summary>Last time the device was confirmed present (not a single-poll ghost).</summary>
        public DateTimeOffset LastSeen { get; set; }
        /// <summary>Consecutive polls reporting IsPresent=true while reconciling offline→online.</summary>
        public int PresentStreak { get; set; }
    }
}
