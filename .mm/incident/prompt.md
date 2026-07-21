# Maintenance Monkey fix job

You are running unattended in a **git worktree** on branch `grok/fix-cdd542553113`.
Project: **BatteryHUD**
Base branch for the eventual PR: **master**

## Mission

Investigate and fix the issue below. Make a minimal, correct change.
Run existing tests if the project has them.
Commit your changes on the current branch with a clear message.
Do **not** merge to main/master. Do **not** force-push.
Do **not** push yourself unless needed — the monkey may push after you exit.
Leave other UserReport checklist items alone.

This came from the project's UserReport.md checklist.

## Job metadata

- Job ID: `cdd542553113`
- Incident ID: `b0d351aab61b`
- Fingerprint: `userreport:UR-test-readme`
- Title: UserReport: Add a short "Maintenance Monkey" section to README.md explaining UserReport.md a

## Environment

- OS: Linux-6.18.34+rpt-rpi-2712-aarch64-with-glibc2.41
- Python: 3.13.5
- Machine: aarch64
- grok: /home/lance/.grok/bin/grok
- gh: /usr/bin/gh

## Git log (last 5)
```
0eb55b2 Attach Maintenance Monkey for automated fix dispatch
d6e31db Add dashboard launcher for the Windows release build.
518f230 List only devices with a battery percent.
8ad8d0d Laptop(Fixed PI)
ac9185d Use single TargetFramework so dotnet run works cleanly.
```

## Git status
```
## Grok...origin/Grok
```

## Recent files (name-status)
```
0eb55b2 Attach Maintenance Monkey for automated fix dispatch
M	.gitignore
M	Program.cs
M	README.md
A	Services/FileLog.cs
A	UserReport.md
A	known_bugs.yaml
A	maintenance_monkey/__init__.py
A	maintenance_monkey/__main__.py
A	maintenance_monkey/cli.py
A	maintenance_monkey/config.py
A	maintenance_monkey/daemon.py
A	maintenance_monkey/dispatch/__init__.py
A	maintenance_monkey/dispatch/git_workflow.py
A	maintenance_monkey/dispatch/grok_runner.py
A	maintenance_monkey/dispatch/prompt.py
A	maintenance_monkey/patterns.py
A	maintenance_monkey/pipeline/__init__.py
A	maintenance_monkey/pipeline/context.py
A	maintenance_monkey/pipeline/fingerprint.py
A	maintenance_monkey/pipeline/queue.py
A	maintenance_monkey/sensors/__init__.py
A	maintenance_monkey/sensors/known_bugs.py
A	maintenance_monkey/sensors/logs.py
A	maintenance_monkey/sensors/process.py
A	maintenance_monkey/sensors/user_report.py
A	maintenance_monkey/state.py
A	mm.toml
d6e31db Add dashboard launcher for the Windows release build.
A	BatteryHUD-Dashboard.bat
518f230 List only devices with a battery percent.
M	Models/BatteryDevice.cs
M	README.md
M	Services/BatteryMonitorService.cs
M	Services/CompositeBatteryProvider.cs
M	Services/LinuxBluezBatteryProvider.cs
M	Services/LinuxSysfsBatteryProvider.cs
M	Services/LinuxUpowerBatteryProvider.cs
M	Services/WindowsWmiBatteryProvider.cs
M	Views/OverlayWindow.axaml.cs
```

## Evidence

# UserReport item

**Title:** Add a short "Maintenance Monkey" section to README.md explaining UserReport.md and logs/batteryhud.log (how to report fixes and where errors are written)
**Line:** 14
**Id:** UR-test-readme
**Trigger:** push

## Item
- [ ] [UR-test-readme] Add a short "Maintenance Monkey" section to README.md explaining UserReport.md and logs/batteryhud.log (how to report fixes and where errors are written)

## Full UserReport notes (non-checklist)
# User Report — BatteryHUD

<!--
  Maintenance Monkey reads this file.
  - Unchecked items (- [ ]) are open work → Grok fix branch + PR.
  - Checked items (- [x]) are ignored.
  - Optional stable id: - [ ] [UR-short-id] description...
  Commit + push (hooks installed) or save while the Pi daemon is running.
-->

## Open

<!-- Add items you want fixed. Example for your first end-to-end test: -->

## Notes

- App logs go to `logs/batteryhud.log` (created at runtime by `FileLog`).
- Run the app on your laptop as usual; leave this repo’s Grok branch tracking open on the Pi with `python -m maintenance_monkey start`.
- After a fix merges, mark the box `[x]` so it does not re-queue.

## Full UserReport file
```markdown
# User Report — BatteryHUD

<!--
  Maintenance Monkey reads this file.
  - Unchecked items (- [ ]) are open work → Grok fix branch + PR.
  - Checked items (- [x]) are ignored.
  - Optional stable id: - [ ] [UR-short-id] description...
  Commit + push (hooks installed) or save while the Pi daemon is running.
-->

## Open

<!-- Add items you want fixed. Example for your first end-to-end test: -->
- [ ] [UR-test-readme] Add a short "Maintenance Monkey" section to README.md explaining UserReport.md and logs/batteryhud.log (how to report fixes and where errors are written)

## Notes

- App logs go to `logs/batteryhud.log` (created at runtime by `FileLog`).
- Run the app on your laptop as usual; leave this repo’s Grok branch tracking open on the Pi with `python -m maintenance_monkey start`.
- After a fix merges, mark the box `[x]` so it does not re-queue.

```

## Evidence files

Also see files under `.mm/incident/` in this worktree (if present).

## Done criteria

1. Root cause addressed (or explain why not in the commit message).
2. Changes committed on `grok/fix-cdd542553113`.
3. Summarize what you changed in your final response.
