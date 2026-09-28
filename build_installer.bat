@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title LazyK - Build installer

rem Version shown in the installer: build_installer.bat 1.2.0   (default 1.0.0)
set "VER=%~1"
if "%VER%"=="" set "VER=1.0.0"

if not exist "dist\LazyK\LazyK.exe" (
  echo No build found. Run build_exe.bat first.
  pause
  exit /b 1
)

echo === 1/2 Looking for Inno Setup ===
call :find_iscc
if not defined ISCC (
  echo Inno Setup not found, installing...
  winget install -e --id JRSoftware.InnoSetup --accept-package-agreements --accept-source-agreements
  call :find_iscc
)
if not defined ISCC (
  echo Inno Setup not found. Download it from https://jrsoftware.org/isdl.php and run this again.
  pause
  exit /b 1
)

echo === 2/2 Compressing into one file (this takes a few minutes) ===
"%ISCC%" /DAppVersion=%VER% installer\lazyk.iss
if errorlevel 1 (
  echo Installer build failed. See the messages above.
  pause
  exit /b 1
)

echo.
echo ============================================
echo  Done! Installer: %CD%\Output\LazyK-Setup-%VER%.exe
echo ============================================
explorer Output
pause
exit /b 0

:find_iscc
set "ISCC="
for %%P in ("%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" "%ProgramFiles%\Inno Setup 6\ISCC.exe") do (
  if exist %%P set "ISCC=%%~P"
)
if not defined ISCC for /f "delims=" %%I in ('where ISCC.exe 2^>nul') do set "ISCC=%%I"
exit /b 0
