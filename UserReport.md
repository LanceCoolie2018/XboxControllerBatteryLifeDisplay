# User Report — BatteryHUD

<!--
  Maintenance Monkey reads this file.
  - Unchecked items (- [ ]) are open work → AssIsstant-fix-* branch + PR.
  - Checked items (- [x]) are ignored.
  - Optional stable id: - [ ] [UR-short-id] description...
  Each fix must be its own top-level checkbox line (not indented under another item).
  Commit + push to Grok; Pi daemon pulls and queues.
-->

## Open

- [x] [UR-test-readme] Add a short "Maintenance Monkey" section to README.md explaining UserReport.md and logs/batteryhud.log (how to report fixes and where errors are written)
- [ ] [UR-disconnect] Disconnection does not register, still not getting a positive connection and disconnection status
- [x] [UR-Closing] needs an exit button to close the app
- [x] [UR-spacing] app is now too wide can we shrink it a little
- [ ] Event Type Moniker	Exception caught: 'System.Management.ManagementException' in BatteryHUD.dll ("Generic failure ") Exception caught: 'System.Management.ManagementException' in BatteryHUD.dll ("Generic failure ") Hyperlink: Activate Historical Debugging	483.57s		[31732] Worker Thread 
- [ ] Event Type Moniker	Exception thrown: 'System.Management.ManagementException' in System.Management.dll ("Generic failure ") Exception thrown: 'System.Management.ManagementException' in System.Management.dll ("Generic failure ") Hyperlink: Activate Historical Debugging	621.36s		[32440] Worker Thread 



## Notes

- App logs go to `logs/batteryhud.log` (created at runtime by `FileLog`).
- After a fix merges, mark the box `[x]` so it does not re-queue.
