# Sideload BatteryHUD MSIX for local testing (self-signed package).
# Run PowerShell as Administrator if install fails with 0x800B0109.
#
# Usage:
#   Right-click PowerShell -> Run as administrator
#   cd D:\BatteryHUD
#   .\scripts\sideload-local-test.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$msix = Join-Path $Root "publish\BatteryHUD_1.0.0.0_x64.msix"
$pfx = Join-Path $Root "store\certs\BatteryHUD_PartnerCenter.pfx"
$cer = Join-Path $Root "store\certs\BatteryHUD_PartnerCenter.cer"
$pwdPlain = "BatteryHUD-local-sign-only"

if (-not (Test-Path $msix)) { throw "Missing MSIX: $msix" }

# Export CER from PFX if needed
if (-not (Test-Path $cer)) {
    $secure = ConvertTo-SecureString $pwdPlain -AsPlainText -Force
    $cert = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2(
        $pfx, $secure, "Exportable")
    [IO.File]::WriteAllBytes(
        $cer,
        $cert.Export([System.Security.Cryptography.X509Certificates.X509ContentType]::Cert))
    Write-Host "Exported $cer"
}

$import = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2($cer)
foreach ($loc in @("LocalMachine", "CurrentUser")) {
    foreach ($name in @("TrustedPeople", "Root")) {
        try {
            $store = New-Object System.Security.Cryptography.X509Certificates.X509Store($name, $loc)
            $store.Open("ReadWrite")
            $store.Add($import)
            $store.Close()
            Write-Host "Trusted: $loc\$name"
        } catch {
            Write-Host "Skip $loc\$name — $($_.Exception.Message)"
        }
    }
}

Get-AppxPackage *BatteryHUD* | ForEach-Object {
    Write-Host "Removing $($_.PackageFullName)"
    Remove-AppxPackage $_.PackageFullName
}

Write-Host "Installing $msix ..."
Add-AppxPackage -Path $msix
$pkg = Get-AppxPackage *BatteryHUD* | Select-Object -First 1
if (-not $pkg) { throw "Install finished but package not found" }

$pkg | Format-List Name, PackageFullName, Version, InstallLocation
$family = $pkg.PackageFamilyName
$appId = ($pkg | Get-AppxPackageManifest).Package.Applications.Application.Id
Write-Host "Launching $family!$appId"
Start-Process "shell:AppsFolder\$family!$appId"
Write-Host "OK — BatteryHUD should be open. Use Bug button to test GitHub Issue flow."
