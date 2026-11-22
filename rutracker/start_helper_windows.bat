@echo off
cd /d "%~dp0"
set /p EXTENSION_ID=ID de la extension (chrome://extensions): 
py -3 torrent_helper.py --extension-id "%EXTENSION_ID%"
echo.
pause
