@echo off
title Kaizen Desktop UI
cd /d "%~dp0"
echo ============================================================
echo   Starting Kaizen Autonomous Desktop Engine...
echo ============================================================
echo.
call .\.venv\Scripts\python.exe gui_server.py
pause
