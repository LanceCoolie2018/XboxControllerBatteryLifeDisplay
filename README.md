# XboxControllerBatteryLifeDisplay

## Maintenance Monkey

[Maintenance Monkey](https://github.com/LanceCoolie2018/maintenance-monkey) watches this repo for issues and can open automated fix PRs.

| What | Where |
|------|--------|
| Your fix requests | `UserReport.md` — unchecked `- [ ]` items become fix jobs |
| App error log | `logs/batteryhud.log` (created at runtime by `FileLog`) |

**How to report a fix request:** add an unchecked checklist item in `UserReport.md` (optionally with a stable id like `[UR-short-id]`), then commit and push. After a fix merges, mark the box `[x]` so it does not re-queue.

**Where errors are written:** the app writes runtime logs to `logs/batteryhud.log` under the process working directory.
