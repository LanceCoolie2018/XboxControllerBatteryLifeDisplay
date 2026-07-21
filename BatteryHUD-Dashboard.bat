@echo off
rem Stable entry point for dashboards / shortcuts / Stream Deck / etc.
setlocal
cd /d "%~dp0"

set "EXE=%~dp0publish\win\BatteryHUD.exe"
if not exist "%EXE%" (
  echo Release build not found:
  echo   %EXE%
  echo.
  echo Build it with:
  echo   dotnet publish BatteryHUD.csproj -c Release -r win-x64 --self-contained true -o publish\win
  pause
  exit /b 1
)

start "" "%EXE%"
exit /b 0
