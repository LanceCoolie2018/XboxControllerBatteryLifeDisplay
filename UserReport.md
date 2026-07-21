# User Report — BatteryHUD

<!--
  Maintenance Monkey reads this file.
  - Unchecked items (- [ ]) are open work → fixed on the AssIsstant branch.
  - Checked items (- [x]) are ignored.
  - Optional stable id: - [ ] [UR-short-id] description...
  Each fix must be its own top-level checkbox line (not indented under another item).
  Commit + push to Grok; Pi daemon pulls and queues.
-->

## Open

- [x] [UR-test-readme] Add a short "Maintenance Monkey" section to README.md explaining UserReport.md and logs/batteryhud.log (how to report fixes and where errors are written)
- [x] [UR-disconnect] Disconnection does not register, still not getting a positive connection and disconnection status
- [x] [UR-Closing] needs an exit button to close the app
- [x] [UR-spacing] app is now too wide can we shrink it a little
- [x] Event Type Moniker	Exception caught: 'System.Management.ManagementException' in BatteryHUD.dll ("Generic failure ") — fixed: skip-list devices that fail GetDeviceProperties; light polls only re-probe known battery devices
- [x] Event Type Moniker	Exception thrown: 'System.Management.ManagementException' in System.Management.dll ("Generic failure ") — same root cause as above (WMI GetDeviceProperties on unsupported PnP devices)




## Notes

- App logs go to `logs/batteryhud.log` (created at runtime by `FileLog`).
- After a fix merges, mark the box `[x]` so it does not re-queue.
