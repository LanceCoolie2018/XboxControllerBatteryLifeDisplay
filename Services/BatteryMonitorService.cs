using BatteryHUD.Models;

namespace BatteryHUD.Services;

/// <summary>
/// Polls the platform provider and tracks the user-selected device.
/// </summary>
public sealed class BatteryMonitorService : IDisposable
{
    private readonly IBatteryDeviceProvider _provider;
    private readonly object _gate = new();
    private List<BatteryDevice> _devices = [];
    private string? _selectedId;
    private Timer? _timer;
    private int _pollMs;

    public event EventHandler? Updated;

    public BatteryMonitorService(IBatteryDeviceProvider provider, AppSettings settings)
    {
        _provider = provider;
        _selectedId = settings.SelectedDeviceId;
        _pollMs = Math.Clamp(settings.PollIntervalMs, 500, 60_000);
    }

    public string PlatformName => _provider.PlatformName;

    public IReadOnlyList<BatteryDevice> Devices
    {
        get { lock (_gate) return _devices.ToList(); }
    }

    public BatteryDevice? Selected
    {
        get
        {
            lock (_gate)
            {
                if (_devices.Count == 0) return null;
                if (!string.IsNullOrEmpty(_selectedId))
                {
                    var match = _devices.FirstOrDefault(d => d.Id == _selectedId);
                    if (match is not null) return match;
                }
                // Prefer a controller if nothing selected / selection gone
                return _devices.FirstOrDefault(d => d.Kind == "Controller")
                       ?? _devices.FirstOrDefault();
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
            snapshot = [];
        }

        lock (_gate)
        {
            _devices = snapshot;
        }

        Updated?.Invoke(this, EventArgs.Empty);
    }

    public void Dispose()
    {
        _timer?.Dispose();
        _timer = null;
    }
}
