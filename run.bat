@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (echo Run setup.bat first. & pause & exit /b 1)
rem  run.bat          normal run (console shows the log)
rem  run.bat --demo   calibration boxes, no API calls
rem  run.bat --image page.png   offline test on one image
.venv\Scripts\python.exe main.py %*
if errorlevel 1 pause
