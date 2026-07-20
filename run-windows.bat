@echo off
setlocal
cd /d "%~dp0"

where dotnet >nul 2>&1
if errorlevel 1 (
  echo .NET SDK/runtime not found on PATH.
  echo Install .NET 8 from https://dotnet.microsoft.com/download/dotnet/8.0
  pause
  exit /b 1
)

echo Restoring and running BatteryHUD...
dotnet restore BatteryHUD.csproj
if errorlevel 1 (
  echo Restore failed.
  pause
  exit /b 1
)

dotnet run --project BatteryHUD.csproj
if errorlevel 1 (
  echo.
  echo Run failed. Common fixes:
  echo   - Install .NET 8 SDK or runtime
  echo   - From this folder:  dotnet build BatteryHUD.csproj
  pause
  exit /b 1
)
