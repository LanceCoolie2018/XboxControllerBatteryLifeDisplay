using System;
using System.IO;
using System.Text;
using System.Text.RegularExpressions;

namespace BatteryHUD.Services;

/// <summary>
/// Appends open checklist items to the repo's UserReport.md (dev installs).
/// Store / release installs use <see cref="GitHubIssueReportService"/> instead.
/// </summary>
public static class UserReportService
{
    private static readonly object Gate = new();

    /// <summary>
    /// True when running from a source tree that has UserReport.md or the csproj
    /// (laptop / monkey workflow). False for Store/MSIX/published installs.
    /// </summary>
    public static bool IsDevRepoInstall()
    {
        var path = ResolvePath();
        if (path is not null && File.Exists(path))
            return true;

        var probe = new DirectoryInfo(AppContext.BaseDirectory);
        for (var i = 0; i < 8 && probe is not null; i++)
        {
            if (File.Exists(Path.Combine(probe.FullName, "BatteryHUD.csproj")))
                return true;
            probe = probe.Parent;
        }

        return false;
    }

    /// <summary>
    /// Locate UserReport.md by walking up from the app base directory
    /// (same strategy as <see cref="FileLog"/> for logs/).
    /// Prefers an existing file; otherwise creates next to BatteryHUD.csproj.
    /// </summary>
    public static string? ResolvePath()
    {
        var probe = new DirectoryInfo(AppContext.BaseDirectory);
        string? besideCsproj = null;

        for (var i = 0; i < 8 && probe is not null; i++)
        {
            var candidate = Path.Combine(probe.FullName, "UserReport.md");
            if (File.Exists(candidate))
                return candidate;

            if (besideCsproj is null &&
                File.Exists(Path.Combine(probe.FullName, "BatteryHUD.csproj")))
            {
                besideCsproj = candidate;
            }

            probe = probe.Parent;
        }

        return besideCsproj;
    }

    /// <summary>
    /// Append a top-level open checklist line under ## Open.
    /// Returns (ok, user-facing message).
    /// </summary>
    public static (bool Ok, string Message) AppendOpenIssue(string description)
    {
        var title = SanitizeTitle(description);
        if (string.IsNullOrEmpty(title))
            return (false, "Describe the issue first.");

        var path = ResolvePath();
        if (path is null)
            return (false, "Could not find UserReport.md (run from the BatteryHUD repo).");

        var line = $"- [ ] {title}";

        try
        {
            lock (Gate)
            {
                string text;
                if (File.Exists(path))
                {
                    text = File.ReadAllText(path, Encoding.UTF8);
                    if (ContainsOpenItem(text, title))
                        return (false, "That issue is already listed in UserReport.md.");
                }
                else
                {
                    text = DefaultTemplate();
                }

                var updated = InsertUnderOpen(text, line);
                var dir = Path.GetDirectoryName(path);
                if (!string.IsNullOrEmpty(dir))
                    Directory.CreateDirectory(dir);

                File.WriteAllText(path, updated, new UTF8Encoding(encoderShouldEmitUTF8Identifier: false));
            }

            FileLog.Info($"UserReport: appended open item → {title}");
            return (true, "Added to UserReport.md — push AssIsstant when ready.");
        }
        catch (Exception ex)
        {
            FileLog.Error("UserReport append failed", ex);
            return (false, $"Could not write UserReport.md: {ex.Message}");
        }
    }

    internal static string SanitizeTitle(string? description)
    {
        if (string.IsNullOrWhiteSpace(description))
            return string.Empty;

        // Single checklist line — collapse whitespace / newlines
        var s = Regex.Replace(description.Trim(), @"\s+", " ");
        // Avoid breaking the checkbox syntax if user types brackets weirdly
        s = s.Replace("\r", " ").Replace("\n", " ");
        if (s.Length > 240)
            s = s[..240].TrimEnd() + "…";
        return s;
    }

    private static bool ContainsOpenItem(string text, string title)
    {
        foreach (var raw in text.Split('\n'))
        {
            var line = raw.TrimEnd('\r');
            if (line.StartsWith("- [ ] ", StringComparison.Ordinal) &&
                string.Equals(line["- [ ] ".Length..].Trim(), title, StringComparison.OrdinalIgnoreCase))
            {
                return true;
            }
        }

        return false;
    }

    /// <summary>
    /// Insert <paramref name="checklistLine"/> after the last top-level checklist
    /// item in the ## Open section, or right after the ## Open heading.
    /// </summary>
    internal static string InsertUnderOpen(string text, string checklistLine)
    {
        var normalized = text.Replace("\r\n", "\n").Replace('\r', '\n');
        var lines = normalized.Split('\n').ToList();

        var openIdx = -1;
        for (var i = 0; i < lines.Count; i++)
        {
            if (lines[i].TrimStart().StartsWith("## Open", StringComparison.OrdinalIgnoreCase))
            {
                openIdx = i;
                break;
            }
        }

        if (openIdx < 0)
        {
            // No ## Open — append a section at end
            if (lines.Count > 0 && lines[^1].Length > 0)
                lines.Add(string.Empty);
            lines.Add("## Open");
            lines.Add(string.Empty);
            lines.Add(checklistLine);
            lines.Add(string.Empty);
            return string.Join("\n", lines) + (normalized.EndsWith('\n') || lines.Count == 0 ? "\n" : "");
        }

        // Find end of Open section: next ## heading at column 0-ish, or EOF
        var sectionEnd = lines.Count;
        for (var i = openIdx + 1; i < lines.Count; i++)
        {
            var t = lines[i].TrimStart();
            if (t.StartsWith("## ", StringComparison.Ordinal) &&
                !t.StartsWith("## Open", StringComparison.OrdinalIgnoreCase))
            {
                sectionEnd = i;
                break;
            }
        }

        // Prefer after the last top-level checklist item (- [ ] / - [x])
        var insertAt = openIdx + 1;
        var lastItem = -1;
        for (var i = openIdx + 1; i < sectionEnd; i++)
        {
            if (Regex.IsMatch(lines[i], @"^[-*]\s*\[[ xX]\]\s+"))
                lastItem = i;
        }

        if (lastItem >= 0)
        {
            insertAt = lastItem + 1;
        }
        else
        {
            // Empty Open section: insert after heading (+ one blank if present)
            insertAt = openIdx + 1;
            if (insertAt < sectionEnd && string.IsNullOrWhiteSpace(lines[insertAt]))
                insertAt++;
        }

        lines.Insert(insertAt, checklistLine);

        // Keep a blank line before the next ## section
        if (insertAt + 1 < lines.Count &&
            lines[insertAt + 1].TrimStart().StartsWith("## ", StringComparison.Ordinal))
        {
            lines.Insert(insertAt + 1, string.Empty);
        }

        var result = string.Join("\n", lines);
        if (!result.EndsWith('\n'))
            result += "\n";
        return result;
    }

    private static string DefaultTemplate() =>
        """
        # User Report — BatteryHUD

        ## Open

        ## Notes

        """;
}
