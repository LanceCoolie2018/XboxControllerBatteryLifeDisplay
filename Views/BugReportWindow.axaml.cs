using Avalonia.Controls;
using Avalonia.Interactivity;
using BatteryHUD.Services;

namespace BatteryHUD.Views;

public partial class BugReportWindow : Window
{
    private readonly bool _devMode;

    // Avalonia design-time / resource loader
    public BugReportWindow()
    {
        InitializeComponent();
        _devMode = UserReportService.IsDevRepoInstall();
        ConfigureMode();
        Opened += (_, _) => DescriptionBox.Focus();
    }

    private void ConfigureMode()
    {
        if (_devMode)
        {
            HelpText.Text =
                "Dev install: save to UserReport.md for the local assistant pipeline, " +
                "or open a public GitHub Issue (same path Store users get).";
            LocalButton.IsVisible = true;
            SubmitButton.Content = "Open on GitHub";
        }
        else
        {
            HelpText.Text =
                "Opens a GitHub bug report in your browser (you may need to sign in). " +
                "Includes app version and a short log snippet — no account tokens leave this app.";
            LocalButton.IsVisible = false;
            SubmitButton.Content = "Open on GitHub";
        }
    }

    private void OnSubmitGitHub(object? sender, RoutedEventArgs e)
    {
        var (ok, message) = GitHubIssueReportService.OpenBugReport(DescriptionBox.Text ?? string.Empty);
        if (!ok)
        {
            StatusText.Text = message;
            StatusText.IsVisible = true;
            return;
        }

        Close(true);
    }

    private void OnSubmitLocal(object? sender, RoutedEventArgs e)
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
