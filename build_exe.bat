@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (echo Run setup.bat first. & pause & exit /b 1)
.venv\Scripts\python.exe -m pip install pyinstaller
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --windowed --onedir --name LazyK --icon assets\icon.ico --add-data "assets;assets" main.py
if errorlevel 1 (echo Build failed. & pause & exit /b 1)
rem build\ is only PyInstaller's scratch folder (its exe cannot run) - remove it to avoid confusion
rmdir /s /q build
if exist dist\LazyK\LazyK.exe explorer dist\LazyK
echo.
echo Built: dist\LazyK\LazyK.exe  (run THIS one; share the whole dist\LazyK folder)
echo settings.json and logs\ are created next to the exe on first run.
pause
