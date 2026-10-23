@echo off
title Iva 24/7 Desktop Voice Call HUD
echo =======================================================
echo   Launching Iva 24/7 Native Desktop Voice HUD
echo   Serafina Voice - Chatterbox-Nano 110M Local CPU
echo =======================================================
cd /d "c:\Users\abhis\Downloads\pt"

REM Ensure daemon on port 8090 is active
powershell -Command "try { (Invoke-WebRequest -Uri 'http://127.0.0.1:8090/api/status' -UseBasicParsing -TimeoutSec 1).StatusCode } catch { Start-Process '.\.venv_chatterbox\Scripts\python.exe' -ArgumentList 'ivy_24x7_voice_chat_daemon.py' -WindowStyle Hidden }"

REM Launch Native Desktop HUD Window
start "" "c:\Users\abhis\Downloads\pt\.venv_chatterbox\Scripts\pythonw.exe" "c:\Users\abhis\Downloads\pt\iva_desktop_voice_hud.py"
exit
