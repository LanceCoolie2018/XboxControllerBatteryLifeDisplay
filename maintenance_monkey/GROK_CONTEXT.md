# Maintainer context (not for end users)

Ambiguous on purpose for public readers. **Pi Grok / laptop Grok** use this when AssIsstant work involves customer Issues or releases.

## Inputs → AssIsstant

1. **UserReport.md** open `- [ ]` lines (dev laptop + push AssIsstant).
2. **GitHub Issues** with label `customer-report` (Store/source users via Bug button → browser).
3. **logs/** patterns in mm.toml (local/dev).

Daemon: `python3 -m maintenance_monkey start` with `PYTHONPATH` = repo root, branch **AssIsstant**.

Issue poll: `[watch.github_issues]` in mm.toml; needs `gh` authenticated on the host. Manual: `python3 -m maintenance_monkey github-issues scan`.

Fingerprint for Issues: `github-issue:{number}` — do not re-open duplicates.

## Rules (unchanged)

- Work only on **AssIsstant**. Never push/merge **master**.
- After fix: commit, push AssIsstant; PR AssIsstant → master is for human review only.
- Closing a GitHub Issue is maintainer choice after Store release — not automatic on job done.

## Release path (human)

1. Verify AssIsstant.
2. Merge to master.
3. Bump Version in BatteryHUD.csproj.
4. `scripts/build-msix.ps1` (or Partner Center packaging).
5. Upload MSIX; price **$4.99**.
6. Test by **installing from Store** on the laptop (not only `dotnet run`).

## Partner Center money

See `store/PARTNER_CENTER.md` (payout account + tax profile). Not needed for monkey operation.
