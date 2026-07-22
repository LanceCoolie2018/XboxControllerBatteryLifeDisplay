# Build a Store-oriented folder publish of BatteryHUD (win-x64).
# Partner Center / MSIX Packaging Tool can wrap this output, or use Visual Studio
# Windows Application Packaging Project when you associate the app with the Store.
#
# Usage (from repo root, PowerShell):
#   .\scripts\build-msix.ps1
#   .\scripts\build-msix.ps1 -Configuration Release -Runtime win-x64
#
# Output: publish\win-x64-store\

param(
    [string]$Configuration = "Release",
    [string]$Runtime = "win-x64",
    [string]$OutDir = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

if (-not $OutDir) {
    $OutDir = Join-Path $Root "publish\$Runtime-store"
}

Write-Host "BatteryHUD store publish"
Write-Host "  Root:   $Root"
Write-Host "  Config: $Configuration"
Write-Host "  RID:    $Runtime"
Write-Host "  Out:    $OutDir"

if (Test-Path $OutDir) {
    Remove-Item -Recurse -Force $OutDir
}

dotnet publish (Join-Path $Root "BatteryHUD.csproj") `
    -c $Configuration `
    -r $Runtime `
    --self-contained true `
    -p:PublishReadyToRun=true `
    -p:DebugType=None `
    -p:DebugSymbols=false `
    -o $OutDir

# Never ship maintainer tooling in a customer payload
$strip = @(
    "maintenance_monkey",
    "UserReport.md",
    "mm.toml",
    "known_bugs.yaml",
    ".mm",
    ".git",
    "logs"
)
foreach ($name in $strip) {
    $p = Join-Path $OutDir $name
    if (Test-Path $p) {
        Remove-Item -Recurse -Force $p
        Write-Host "stripped $name"
    }
}

Write-Host ""
Write-Host "Publish folder ready: $OutDir"
Write-Host "Next:"
Write-Host "  1) Package as MSIX (Visual Studio packaging project or MSIX Packaging Tool)."
Write-Host "  2) Upload to Partner Center (see store\PARTNER_CENTER.md)."
Write-Host "  3) Install from Store / package flight to test the real customer path."
Write-Host "  4) Bug button should open GitHub Issues (not UserReport.md)."
