using Avalonia.Controls;
using Avalonia.Interactivity;
using BatteryHUD.Services;

namespace BatteryHUD.Views;

public partial class BugReportWindow : Window
{
    // Avalonia design-time / resource loader
    public BugReportWindow()
    {
        InitializeComponent();
        Opened += (_, _) => DescriptionBox.Focus();
    }

    private void OnSubmit(object? sender, RoutedEventArgs e)
    {
        var (ok, message) = UserReportService.AppendOpenIssue(DescriptionBox.Text ?? string.Empty);
        if (!ok)
        {
            StatusText.Text = message;
            StatusText.IsVisible = true;
            return;
        }

        Close(true);
    }

    private void OnCancel(object? sender, RoutedEventArgs e) => Close(false);
}
