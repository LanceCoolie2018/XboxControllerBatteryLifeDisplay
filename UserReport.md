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
- [x] needs added button for bug report that will add a line to the open issues in the UserReport.md so that the user doesnt need to open code to notify of an issue.
- [x] need an ability to duplicate itself to monitor another device and have 2 widgets at the same time — fixed: Dup button opens another overlay; each widget has its own device + position; Exit closes one widget (last quits)
- [x] i want to add a secondary widget to this, the widget should display time in a way that looks like a 3D hologram that i can move anywhere on the screen/screens too. — fixed: Time button opens draggable cyan hologram clock (any screen); position + open state saved
- [x] blue is a bad color, lets go back to green
- [x] the background for the holotime should not be the same color as other text and the original color for the holographic background was fine, the red needs to be brighter too.
- [x] [UR-gh-20] needs a option for a holo grandfather clock so that people can personalize their space — fixed: Style toggle on hologram clock (Digital / Grandfather analog+pendulum); choice saved in settings
- [x] [UR-gh-21] the Pin Button should go under the exit button to not cut off the percentage display — fixed: Pin moved to second row under Exit; top row keeps Switch/Dup/Time/Bug/Exit so % is not squeezed
- [x] [UR-gh-23] center point on grandfather clock does not line up with clock hands — fixed: analog hand bottom margins equal full hand height so pivot matches face center pin
- [x] [UR-gh-24] starting position too low and too far right — fixed: place windows using physical pixels (DIP size × screen.Scaling) so high-DPI Windows does not push past the working-area edge
- [x] [UR-gh-26] starting position for the app should be the center of the screen — fixed: default overlay placement is primary working-area center (saved positions still restored)
- [x] [UR-gh-28] grandfather clock hand does not swing in sync with the passing of time each second — fixed: pendulum phase-locked to wall-clock (1 beat/sec); analog hands updated on 40ms scan tick for smooth second sweep

## Notes

- App logs go to `logs/batteryhud.log` (created at runtime by `FileLog`).
- Monkey auto-checks items when a job finishes; Ready for Review still lists them until you push `task complete`.
