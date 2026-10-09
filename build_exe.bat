@echo off
chcp 65001 >nul
cd /d "%~dp0"
title LazyK - Build

if not exist ".venv\Scripts\python.exe" (
  echo Environment not found. Run setup.bat first.
  pause
  exit /b 1
)
set PY="%~dp0.venv\Scripts\python.exe"
set OUT=dist\LazyK

rem Close a running LazyK build, otherwise its files are locked and the old build cannot be replaced
tasklist /fi "imagename eq LazyK.exe" | find /i "LazyK.exe" >nul
if not errorlevel 1 (
  echo LazyK is running - closing it before building...
  taskkill /im LazyK.exe /f >nul 2>nul
  timeout /t 2 /nobreak >nul
)

rem Keep the settings of the previous build (API keys, toolbar position...) if there is one
if exist "%OUT%\settings.json" copy /y "%OUT%\settings.json" "%TEMP%\lazyk_settings.json" >nul

echo === 1/4 Installing PyInstaller ===
%PY% -m pip install -q pyinstaller

echo === 2/4 Building (this takes a few minutes) ===
%PY% -m PyInstaller --noconfirm --clean --windowed --onedir ^
  --name "LazyK" ^
  --icon "assets\icon.ico" ^
  --version-file "installer\version_info.txt" ^
  --add-data "assets;assets" ^
  --hidden-import pynput.keyboard._win32 ^
  --hidden-import pynput.mouse._win32 ^
  --hidden-import pystray._win32 ^
  --collect-all rapidocr ^
  --hidden-import _miniaudio ^
  --collect-all edge_tts ^
  --collect-binaries onnxruntime ^
  main.py
if errorlevel 1 (
  echo.
  echo Build failed. See the messages above.
  pause
  exit /b 1
)
rem build\ is only PyInstaller's scratch folder (its exe cannot run)
rmdir /s /q build 2>nul

echo === 3/4 Copying settings ===
if exist "%TEMP%\lazyk_settings.json" (
  move /y "%TEMP%\lazyk_settings.json" "%OUT%\settings.json" >nul
) else if exist settings.json (
  copy /y settings.json "%OUT%\" >nul
)

echo === 4/4 Creating desktop shortcut ===
powershell -NoProfile -Command ^
  "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\LazyK.lnk');" ^
  "$s.TargetPath='%CD%\%OUT%\LazyK.exe';" ^
  "$s.WorkingDirectory='%CD%\%OUT%';" ^
  "$s.IconLocation='%CD%\%OUT%\LazyK.exe,0';" ^
  "$s.Save()"

echo.
echo ============================================
echo  Done! Open LazyK from the desktop shortcut.
echo  App folder: %CD%\%OUT%
echo  If something goes wrong, check logs\lazyk.log in the app folder.
echo.
echo  settings.json holds your API keys: do not share the
echo  %OUT% folder as it is. Use build_installer.bat to share.
echo ============================================
pause
