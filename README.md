# BatteryHUD

Always-on-top battery overlay for **game controllers, Bluetooth mice, keyboards, headsets** — anything your OS reports a charge percentage for.

Built so you can glance at battery life **while playing** and swap packs *before* the pad dies mid-fight.

## Why

You are in a match. Your controller is about to die. BatteryHUD sits in the corner (draggable, always on top) and shows the device **you** care about. Hit **Switch** anytime to pick another peripheral.

## Features

- **Cross-platform**: Windows, Linux, macOS (best-effort)
- **Any battery peripheral** the OS exposes (not Xbox-only)
  - Windows: light WMI/PnP queries (not a full-system hammer every tick)
  - Linux: UPower + BlueZ + `/sys/class/power_supply`
  - macOS: `ioreg` battery keys where available
- **% only** — picker lists only devices the OS reports a battery percentage for (no ghosts)
- **Sticky readings** — brief BT/WMI blips keep the last % through a short grace window
- **Choose + switch anytime** — device picker, selection remembered by stable key
- **Gaming-focused HUD**: large %, color bands, low-battery pulse, “swap before a fight” hint
- **Drag to position**; remembers window placement

## Battery % caveats

Only devices that **report charge % to the OS** appear in the list. Many BLE HID keyboards
(e.g. some ProtoArc models) connect fine but **do not** implement the standard Battery
Service (`0x180F`) or UPower node — they are **omitted**, not shown as “unknown.”
Controllers that expose % (Xbox, DualSense, many mice) are the sweet spot for mid-game swaps.

## Requirements

| Platform | Needs |
|----------|--------|
| All | [.NET 8 runtime](https://dotnet.microsoft.com/download/dotnet/8.0) (or publish self-contained) |
| Linux | `upower` (usually preinstalled on desktop distros) |
| Windows | Normal user rights (no admin); Bluetooth/HID stack reporting battery |
| macOS | Devices that expose `BatteryPercent` via IOKit |

> **Note:** Only devices that **report battery % to the OS** appear. Some cheap dongles and wired-only pads never expose a percentage — there is nothing for any app to read.

## Run from source

**Windows (easiest):** double-click `run-windows.bat`, or in PowerShell / cmd:

```bat
cd /d D:\BatteryHud
dotnet restore BatteryHUD.csproj
dotnet run --project BatteryHUD.csproj
```

**Linux / macOS / any terminal with `dotnet` on PATH:**

```bash
dotnet restore BatteryHUD.csproj
dotnet run --project BatteryHUD.csproj
```

### Laptop / multi-monitor note

The overlay remembers its last position. If you undock or change displays and the window seems missing, it was often **off-screen** — BatteryHUD now snaps back to the primary bottom-right when the saved position is no longer visible. You can also delete `%AppData%\BatteryHUD\settings.json` to reset.

## Publish (single folder)

```bash
# Linux
dotnet publish BatteryHUD.csproj -c Release -r linux-x64 --self-contained true -o publish/linux

# Windows (run on Windows or with the workload)
dotnet publish BatteryHUD.csproj -c Release -r win-x64 --self-contained true -o publish/win
```

## Usage

1. Start BatteryHUD.
2. Click **Switch**.
3. Select your controller (or mouse/headset).
4. Drag the HUD where it will not block your game UI.
5. When it turns orange/red or pulses **LOW**, swap batteries between rounds.

Settings are stored in your user app data folder under `BatteryHUD/settings.json`.

## Project layout

```
Models/          BatteryDevice, AppSettings
Services/        Platform battery providers + monitor + settings
Views/           Overlay HUD + device picker
```

## Product name

The repository is still named `XboxControllerBatteryLifeDisplay` for history; the app product is **BatteryHUD**.

## Maintenance Monkey

This branch includes [Maintenance Monkey](https://github.com/LanceCoolie2018/maintenance-monkey) so the Pi can watch for issues and open fix PRs.

| What | Where |
|------|--------|
| Your fix requests | `UserReport.md` — unchecked `- [ ]` items become AssIsstant jobs |
| App error log | `logs/batteryhud.log` (created at runtime by `FileLog`) |
| Config | `mm.toml` |

**Laptop (you):** run BatteryHUD as usual. Edit `UserReport.md`, commit, push to **`AssIsstant`**. After first clone, once: `python3 -m maintenance_monkey install-hooks` (with `PYTHONPATH` set to the repo root).

**Pi (daemon):**

```bash
cd /path/to/XboxControllerBatteryLifeDisplay
git checkout AssIsstant && git pull
export PYTHONPATH="$PWD"
python3 -m maintenance_monkey start
# or: python3 -m maintenance_monkey install-systemd
```

Fixes land as `AssIsstant/fix-*` branches + PRs into **master** for you to review.

## License

Personal project — use and modify freely.
