# BatteryHUD

Always-on-top battery overlay for **game controllers, Bluetooth mice, keyboards, headsets** — anything your OS reports a charge percentage for.

Built so you can glance at battery life **while playing** and swap packs *before* the pad dies mid-fight.

## Why

You are in a match. Your controller is about to die. BatteryHUD sits in the corner (draggable, always on top) and shows the device **you** care about. Hit **Switch** anytime to pick another peripheral.

## Features

- **Cross-platform**: Windows, Linux, macOS (best-effort)
- **Any battery peripheral** the OS exposes (not Xbox-only)
  - Windows: WMI/PnP device battery properties (Xbox, DualSense, BT mice, etc.)
  - Linux: [UPower](https://upower.freedesktop.org/) (`upower`)
  - macOS: `ioreg` battery keys where available
- **Choose + switch anytime** — device picker, selection remembered
- **Gaming-focused HUD**: large %, color bands, low-battery pulse, “swap before a fight” hint
- **Drag to position**; remembers window placement

## Requirements

| Platform | Needs |
|----------|--------|
| All | [.NET 8 runtime](https://dotnet.microsoft.com/download/dotnet/8.0) (or publish self-contained) |
| Linux | `upower` (usually preinstalled on desktop distros) |
| Windows | Normal user rights (no admin); Bluetooth/HID stack reporting battery |
| macOS | Devices that expose `BatteryPercent` via IOKit |

> **Note:** Only devices that **report battery % to the OS** appear. Some cheap dongles and wired-only pads never expose a percentage — there is nothing for any app to read.

## Run from source

```bash
dotnet restore BatteryHUD.csproj
dotnet run --project BatteryHUD.csproj
```

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

## License

Personal project — use and modify freely.
