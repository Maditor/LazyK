@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (echo Run setup.bat first. & pause & exit /b 1)
rem  run.bat                  start LazyK without a console window (the log is in logs\lazyk.log)
rem  run.bat --demo           calibration boxes, no API calls      (these run in this console)
rem  run.bat --image page.png offline test on one image
if "%~1"=="" if exist .venv\Scripts\pythonw.exe (
    start "" ".venv\Scripts\pythonw.exe" main.py
    exit /b 0
)
.venv\Scripts\python.exe main.py %*
if errorlevel 1 pause
