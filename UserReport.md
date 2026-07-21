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
  - disconnection does not register right away and falsly reconnects to the controller even when its still off

## Notes

- App logs go to `logs/batteryhud.log` (created at runtime by `FileLog`).
- Run the app on your laptop as usual; leave this repo’s Grok branch tracking open on the Pi with `python -m maintenance_monkey start`.
- After a fix merges, mark the box `[x]` so it does not re-queue.
