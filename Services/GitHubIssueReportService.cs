using System;
using System.Diagnostics;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text;

namespace BatteryHUD.Services;

/// <summary>
/// Opens a pre-filled GitHub Issue in the default browser.
/// No tokens or OAuth — customers sign in on GitHub if needed.
/// </summary>
public static class GitHubIssueReportService
{
    /// <summary>Public repo that receives customer bug reports.</summary>
    public const string Owner = "LanceCoolie2018";
    public const string Repo = "XboxControllerBatteryLifeDisplay";

    /// <summary>Labels applied via the new-issue URL (must exist on the repo).</summary>
    public static readonly string[] DefaultLabels = ["customer-report", "needs-triage"];

    public static string AppVersion
    {
        get
        {
            var asm = Assembly.GetExecutingAssembly();
            var info = asm.GetCustomAttribute<AssemblyInformationalVersionAttribute>()
                ?.InformationalVersion;
            if (!string.IsNullOrWhiteSpace(info))
            {
                // Strip build metadata (+...)
                var plus = info.IndexOf('+');
                return plus >= 0 ? info[..plus] : info;
            }

            return asm.GetName().Version?.ToString(3) ?? "0.0.0";
        }
    }

    /// <summary>
    /// Build a github.com/…/issues/new URL with title, body, and labels.
    /// </summary>
    public static string BuildNewIssueUrl(string userDescription, int logTailLines = 50)
    {
        var title = UserReportService.SanitizeTitle(userDescription);
        if (string.IsNullOrEmpty(title))
            title = "BatteryHUD bug report";
        if (title.Length > 80)
            title = title[..80].TrimEnd() + "…";

        var body = BuildIssueBody(userDescription, logTailLines);
        var labels = string.Join(",", DefaultLabels);

        var qs = new StringBuilder();
        qs.Append("title=").Append(Uri.EscapeDataString(title));
        qs.Append("&body=").Append(Uri.EscapeDataString(body));
        qs.Append("&labels=").Append(Uri.EscapeDataString(labels));

        return $"https://github.com/{Owner}/{Repo}/issues/new?{qs}";
    }

    public static string BuildIssueBody(string userDescription, int logTailLines = 50)
    {
        var os = RuntimeInformation.OSDescription;
        var rid = RuntimeInformation.RuntimeIdentifier;
        var framework = RuntimeInformation.FrameworkDescription;
        var desc = string.IsNullOrWhiteSpace(userDescription)
            ? "(no description)"
            : userDescription.Trim();

        var sb = new StringBuilder();
        sb.AppendLine("### What went wrong?");
        sb.AppendLine();
        sb.AppendLine(desc);
        sb.AppendLine();
        sb.AppendLine("### Environment");
        sb.AppendLine();
        sb.AppendLine($"- **App version:** {AppVersion}");
        sb.AppendLine($"- **OS:** {os}");
        sb.AppendLine($"- **RID:** {rid}");
        sb.AppendLine($"- **Runtime:** {framework}");
        sb.AppendLine($"- **Install mode:** {(UserReportService.IsDevRepoInstall() ? "dev/source" : "release/store")}");
        sb.AppendLine();
        sb.AppendLine("### Recent log (last lines)");
        sb.AppendLine();
        sb.AppendLine("```");
        sb.AppendLine(FileLog.ReadTail(logTailLines));
        sb.AppendLine("```");
        sb.AppendLine();
        sb.AppendLine("<!-- filed from BatteryHUD Bug button -->");
        return sb.ToString();
    }

    /// <summary>
    /// Open the default browser to a new pre-filled Issue.
    /// Returns (ok, user-facing message).
    /// </summary>
    public static (bool Ok, string Message) OpenBugReport(string userDescription)
    {
        var title = UserReportService.SanitizeTitle(userDescription);
        if (string.IsNullOrEmpty(title))
            return (false, "Describe the issue first.");

        try
        {
            var url = BuildNewIssueUrl(userDescription);
            OpenUrl(url);
            FileLog.Info($"GitHub Issue report opened (v{AppVersion})");
            return (true, "Opened GitHub in your browser — sign in if asked, then Submit the issue.");
        }
        catch (Exception ex)
        {
            FileLog.Error("Failed to open GitHub Issue URL", ex);
            return (false, $"Could not open browser: {ex.Message}");
        }
    }

    private static void OpenUrl(string url)
    {
        // Use shell execute so the OS default browser handles https://
        var psi = new ProcessStartInfo
        {
            FileName = url,
            UseShellExecute = true
        };
        Process.Start(psi);
    }
}
