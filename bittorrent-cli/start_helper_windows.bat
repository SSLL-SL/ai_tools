@echo off
cd /d "%~dp0"
set /p EXTENSION_ID=ID de la extension (chrome://extensions): 
if exist "target\release\torrent-helper.exe" (
  "target\release\torrent-helper.exe" --extension-id "%EXTENSION_ID%"
) else if exist "target\debug\torrent-helper.exe" (
  "target\debug\torrent-helper.exe" --extension-id "%EXTENSION_ID%"
) else (
  echo No se encontro torrent-helper.exe. Ejecuta: cargo build --release
)
echo.
pause
