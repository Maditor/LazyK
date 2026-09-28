@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (echo Run setup.bat first. & pause & exit /b 1)
call .venv\Scripts\activate.bat
pip install pyinstaller
pyinstaller --noconfirm --clean --windowed --onedir --name LazyK --icon assets\icon.ico --add-data "assets;assets" main.py
if errorlevel 1 (echo Build failed. & pause & exit /b 1)
echo.
echo Built: dist\LazyK\LazyK.exe
echo settings.json and logs\ are created next to the exe on first run.
pause
