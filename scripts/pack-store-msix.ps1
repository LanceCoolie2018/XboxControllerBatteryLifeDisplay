# Full pipeline: publish win-x64, generate assets, pack + sign MSIX for Partner Center.
# Identity must match store\AppxManifest.xml (Partner Center App identity).
#
# Usage (PowerShell):
#   cd D:\BatteryHUD
#   .\scripts\pack-store-msix.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$publish = Join-Path $Root "publish\win-x64-store"
$msix = Join-Path $Root "publish\BatteryHUD_1.0.1.0_x64.msix"
$manifestSrc = Join-Path $Root "store\AppxManifest.xml"
$kit = "C:\Program Files (x86)\Windows Kits\10\bin\10.0.26100.0\x64"
$makeappx = Join-Path $kit "MakeAppx.exe"
$signtool = Join-Path $kit "SignTool.exe"
$pfx = Join-Path $Root "store\certs\BatteryHUD_PartnerCenter.pfx"
$pwdPlain = "BatteryHUD-local-sign-only"

& (Join-Path $Root "scripts\build-msix.ps1")
if (-not (Test-Path $manifestSrc)) { throw "Missing $manifestSrc" }
Copy-Item $manifestSrc (Join-Path $publish "AppxManifest.xml") -Force

# Ensure logo assets
$assets = Join-Path $publish "Assets"
if (-not (Test-Path (Join-Path $assets "StoreLogo.png"))) {
    Add-Type -AssemblyName System.Drawing
    $srcIco = Join-Path $Root "Assets\BatteryCharger.ico"
    New-Item -ItemType Directory -Force -Path $assets | Out-Null
    $icon = New-Object System.Drawing.Icon($srcIco, 256, 256)
    $bmp = $icon.ToBitmap()
    function Save-Size([System.Drawing.Bitmap]$source, [int]$w, [int]$h, [string]$path) {
        $dest = New-Object System.Drawing.Bitmap $w, $h
        $g = [System.Drawing.Graphics]::FromImage($dest)
        $g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
        $g.Clear([System.Drawing.Color]::FromArgb(30, 30, 30))
        $scale = [Math]::Min($w / $source.Width, $h / $source.Height)
        $nw = [int]($source.Width * $scale); $nh = [int]($source.Height * $scale)
        $g.DrawImage($source, [int](($w - $nw) / 2), [int](($h - $nh) / 2), $nw, $nh)
        $g.Dispose(); $dest.Save($path, [System.Drawing.Imaging.ImageFormat]::Png); $dest.Dispose()
    }
    Save-Size $bmp 50 50 (Join-Path $assets "StoreLogo.png")
    Save-Size $bmp 44 44 (Join-Path $assets "Square44x44Logo.png")
    Save-Size $bmp 150 150 (Join-Path $assets "Square150x150Logo.png")
    Save-Size $bmp 310 150 (Join-Path $assets "Wide310x150Logo.png")
    Save-Size $bmp 620 300 (Join-Path $assets "SplashScreen.png")
    $bmp.Dispose(); $icon.Dispose()
}

# Ensure Partner Center signing cert (CN matches AppxManifest Publisher)
$certDir = Join-Path $Root "store\certs"
New-Item -ItemType Directory -Force -Path $certDir | Out-Null
$subject = "CN=38612EE3-4B41-491B-A977-4F01F5A3F473"
$secure = ConvertTo-SecureString $pwdPlain -AsPlainText -Force
if (-not (Test-Path $pfx)) {
    $cert = New-SelfSignedCertificate -Type Custom -Subject $subject `
        -KeyUsage DigitalSignature -FriendlyName "BatteryHUD Partner Center" `
        -CertStoreLocation "Cert:\CurrentUser\My" `
        -TextExtension @("2.5.29.37={text}1.3.6.1.5.5.7.3.3", "2.5.29.19={text}") `
        -KeyExportPolicy Exportable -KeySpec Signature -KeyLength 2048 -HashAlgorithm SHA256 `
        -NotAfter (Get-Date).AddYears(5)
    Export-PfxCertificate -Cert $cert -FilePath $pfx -Password $secure | Out-Null
}

if (Test-Path $msix) { Remove-Item $msix -Force }
& $makeappx pack /d $publish /p $msix /o
if ($LASTEXITCODE -ne 0) { throw "MakeAppx failed" }
& $signtool sign /fd SHA256 /a /f $pfx /p $pwdPlain $msix
if ($LASTEXITCODE -ne 0) { throw "SignTool failed" }

Write-Host ""
Write-Host "MSIX ready: $msix"
Get-Item $msix | Format-List FullName, Length, LastWriteTime
