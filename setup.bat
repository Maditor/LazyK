@echo off
setlocal
cd /d "%~dp0"
echo === LazyK setup ===
where py >nul 2>nul && (py -3.11 -m venv .venv) || (python -m venv .venv)
if errorlevel 1 (echo Could not create venv. Install Python 3.11 first. & pause & exit /b 1)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
if errorlevel 1 (echo Install failed. & pause & exit /b 1)
echo.
echo Done. Start with run.bat
pause
