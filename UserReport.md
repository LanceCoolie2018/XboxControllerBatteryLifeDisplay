# User Report — BatteryHUD

<!--
  Maintenance Monkey reads this file.
  - Unchecked items (- [ ]) are open work → fixed on the AssIsstant branch.
  - Checked items (- [x]) are ignored.
  - Optional stable id: - [ ] [UR-short-id] description...
  Each fix must be its own top-level checkbox line (not indented under another item).
  Commit + push to AssIsstant; Pi daemon pulls and queues.
  Clear Ready for Review: commit "task complete" or "task UR-xxx complete" and push.
-->

## Open

- [x] [UR-test-readme] Add a short "Maintenance Monkey" section to README.md explaining UserReport.md and logs/batteryhud.log (how to report fixes and where errors are written)
- [x] [UR-disconnect] Disconnection does not register, still not getting a positive connection and disconnection status
- [x] [UR-Closing] needs an exit button to close the app
- [x] [UR-spacing] app is now too wide can we shrink it a little
- [x] Event Type MonikerException caught: 'System.Management.ManagementException' in BatteryHUD.dll ("Generic failure ") — fixed: skip-list devices that fail GetDeviceProperties; light polls only re-probe known battery devices
- [x] Event Type MonikerException thrown: 'System.Management.ManagementException' in System.Management.dll ("Generic failure ") — same root cause as above (WMI GetDeviceProperties on unsupported PnP devices)
- [x] still falsly indicating that the controller is connected when its not — fixed: require confirm polls on first sighting; BlueZ/sysfs address veto; WMI IsConnected/Present
- [x] widget needs to be a little smaller, i dont want it interfearing with gameplay but i still want the buttons that where added, the bottom two lines can be shrunk to just say the name of the device and wether or not they are connected
- [x] make the percent display blue for better reading.

## Notes

- App logs go to `logs/batteryhud.log` (created at runtime by `FileLog`).
- Monkey auto-checks items when a job finishes; Ready for Review still lists them until you push `task complete`.
