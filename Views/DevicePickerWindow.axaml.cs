using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Interactivity;
using BatteryHUD.Models;

namespace BatteryHUD.Views;

public partial class DevicePickerWindow : Window
{
    public const string ClearSelectionId = "__clear__";

    private List<BatteryDevice> _devices;

    private readonly Func<IReadOnlyList<BatteryDevice>>? _refresh;

    // Avalonia design-time / resource loader
    public DevicePickerWindow() : this(Array.Empty<BatteryDevice>(), null)
    {
    }

    public DevicePickerWindow(
        IReadOnlyList<BatteryDevice> devices,
        string? selectedId,
        Func<IReadOnlyList<BatteryDevice>>? refresh = null)
    {
        InitializeComponent();
        _refresh = refresh;
        _devices = devices.ToList();
        DeviceList.ItemsSource = _devices;
        SelectId(selectedId);
    }

    private void SelectId(string? selectedId)
    {
        if (!string.IsNullOrEmpty(selectedId))
        {
            var match = _devices.FirstOrDefault(d => d.Id == selectedId);
            if (match is not null)
            {
                DeviceList.SelectedItem = match;
                return;
            }
        }

        if (_devices.Count > 0)
        {
            DeviceList.SelectedItem = _devices.FirstOrDefault(d => d.Kind == "Controller")
                                      ?? _devices[0];
        }
    }

    private void OnConfirm(object? sender, RoutedEventArgs e) => CloseWithSelection();

    private void OnDoubleTapped(object? sender, TappedEventArgs e) => CloseWithSelection();

    private void CloseWithSelection()
    {
        if (DeviceList.SelectedItem is BatteryDevice device)
            Close(device.Id);
        else
            Close(null);
    }

    private void OnCancel(object? sender, RoutedEventArgs e) => Close(null);

    private void OnClear(object? sender, RoutedEventArgs e) => Close(ClearSelectionId);

    private void OnRefresh(object? sender, RoutedEventArgs e)
    {
        if (_refresh is null) return;
        var selected = (DeviceList.SelectedItem as BatteryDevice)?.Id;
        _devices = _refresh().ToList();
        DeviceList.ItemsSource = null;
        DeviceList.ItemsSource = _devices;
        SelectId(selected);
    }
}
