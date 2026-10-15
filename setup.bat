@echo off
setlocal
cd /d "%~dp0"
echo === LazyK setup ===

rem LazyK needs Python 3.10, 3.11 or 3.12 (not 3.13+). 64-bit is recommended: only 64-bit runs the local
rem OCR engine and the local Piper voice. 32-bit works too, but those two are skipped (use AI
rem translation and the online voice).

set "PYVER=3.12.8"
call :scan
if defined PYCMD goto :havepython

echo No suitable Python (3.10-3.12) found - installing Python %PYVER% automatically...
call :autoinstall
call :scan
if defined PYCMD goto :havepython

echo.
echo Automatic install did not work (no internet, a proxy, or it was blocked).
echo Please install Python 3.12 by hand from:
echo    https://www.python.org/downloads/release/python-3128/
echo  - tick "Add python.exe to PATH" during install
echo Then run setup.bat again.
echo.
pause
exit /b 1

:havepython
rem Is the chosen Python 64-bit? (local OCR + Piper need it)
set "BIT64="
%PYCMD% -c "import struct,sys;sys.exit(0 if struct.calcsize('P')==8 else 1)" >nul 2>nul
if not errorlevel 1 set "BIT64=1"
if defined BIT64 (echo Using: %PYCMD%  ^(64-bit: all features^)) else (echo Using: %PYCMD%  ^(32-bit: no local OCR / Piper voice^))

rem A .venv copied/moved from another folder, or built with an unsupported Python, is rebuilt.
set "HERE=%~dp0"
set "MARK=.venv\lazyk_path.txt"
if exist .venv (
    set "OLD="
    if exist "%MARK%" set /p OLD=<"%MARK%"
    call :check_venv
)

if not exist .venv\Scripts\python.exe (
    echo Creating .venv ...
    %PYCMD% -m venv .venv
    if not exist .venv\Scripts\python.exe (echo Could not create the .venv. & pause & exit /b 1)
)
> "%MARK%" echo %HERE%

set "PY=.venv\Scripts\python.exe"
"%PY%" -m pip install --upgrade pip
"%PY%" -m pip install -r requirements.txt
if errorlevel 1 (echo Install failed. & pause & exit /b 1)

rem numpy / opencv need the Microsoft Visual C++ Runtime. On a fresh machine it is often missing
rem ("DLL load failed importing _multiarray_umath") - install it automatically if so.
"%PY%" -c "import numpy" >nul 2>nul
if errorlevel 1 call :ensure_vcredist
"%PY%" -c "import numpy" >nul 2>nul
if errorlevel 1 (
    echo.
    echo The Python libraries need the Microsoft Visual C++ Runtime, which could not be installed here.
    echo Install it by hand ^(it asks for admin^), then run setup.bat again:
    if defined BIT64 (echo    https://aka.ms/vs/17/release/vc_redist.x64.exe) else (echo    https://aka.ms/vs/17/release/vc_redist.x86.exe)
    echo.
    pause
    exit /b 1
)

if not defined BIT64 (
    echo.
    echo 32-bit Python: skipping local OCR and the local Piper voice ^(no 32-bit support^).
    echo LazyK will use AI translation and the online voice.
    echo.
    echo Done. Start with run.bat
    pause
    exit /b 0
)

echo Installing local OCR + voice ^(64-bit^) ...
"%PY%" -m pip install -r requirements-ocr.txt
if errorlevel 1 (echo Install failed. & pause & exit /b 1)
rem rapidocr --no-deps: its own requirement opencv-python would clash with opencv-python-headless
"%PY%" -m pip install --no-deps rapidocr==3.9.2
if errorlevel 1 (echo Install failed. & pause & exit /b 1)
rem Piper --no-deps: it would add a second onnxruntime next to onnxruntime-directml
"%PY%" -m pip install --no-deps piper-tts==1.8.0
if errorlevel 1 (echo Install failed. & pause & exit /b 1)
echo.
echo Downloading the speech bubble model ^(168 MB, once^) ...
"%PY%" main.py --get-models
echo.
echo Done. Start with run.bat
pause
exit /b 0

rem =====================================================================
:scan
rem Find a Python 3.10-3.12 and put it in PYCMD (quoted if it is a full path).
set "PYCMD="
call :pick py -3.12
if not defined PYCMD call :pick py -3.11
if not defined PYCMD call :pick py -3.10
if not defined PYCMD call :pick python
if not defined PYCMD call :pick py
rem freshly-installed per-user Python (PATH is not refreshed in this window): check known folders
if not defined PYCMD call :pickexe "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined PYCMD call :pickexe "%LOCALAPPDATA%\Programs\Python\Python312-32\python.exe"
if not defined PYCMD call :pickexe "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
if not defined PYCMD call :pickexe "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
if not defined PYCMD call :pickexe "%ProgramFiles%\Python312\python.exe"
if not defined PYCMD call :pickexe "%ProgramFiles(x86)%\Python312\python.exe"
exit /b 0

:pick
rem %* = a candidate launcher; accept if it is Python 3.10-3.12 (any bit).
%* -c "import sys;v=sys.version_info;sys.exit(0 if (3,10)<=(v[0],v[1])<=(3,12) else 1)" >nul 2>nul
if not errorlevel 1 set "PYCMD=%*"
exit /b 0

:pickexe
if not exist "%~1" exit /b 0
"%~1" -c "import sys;v=sys.version_info;sys.exit(0 if (3,10)<=(v[0],v[1])<=(3,12) else 1)" >nul 2>nul
if not errorlevel 1 set PYCMD="%~1"
exit /b 0

:autoinstall
rem Try winget first (clean); if missing, download the official installer from python.org.
set "OSARCH=x86"
if defined PROCESSOR_ARCHITEW6432 set "OSARCH=x64"
if /i "%PROCESSOR_ARCHITECTURE%"=="AMD64" set "OSARCH=x64"
if /i "%PROCESSOR_ARCHITECTURE%"=="ARM64" set "OSARCH=arm64"

where winget >nul 2>nul
if not errorlevel 1 (
    echo Installing with winget ...
    winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements --override "/passive PrependPath=1 Include_launcher=1 Include_tcltk=1 Include_pip=1" >nul 2>nul
    call :scan
    if defined PYCMD exit /b 0
)

set "SUF=-amd64"
if /i "%OSARCH%"=="x86" set "SUF="
if /i "%OSARCH%"=="arm64" set "SUF=-arm64"
set "URL=https://www.python.org/ftp/python/%PYVER%/python-%PYVER%%SUF%.exe"
set "DEST=%TEMP%\lazyk_python_%PYVER%.exe"
echo Downloading Python %PYVER% (%OSARCH%) from python.org ...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; try { [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -UseBasicParsing '%URL%' -OutFile '%DEST%' } catch { exit 1 }"
if not exist "%DEST%" (echo Download failed. & exit /b 1)
echo Installing Python (a progress window will appear) ...
"%DEST%" /passive PrependPath=1 Include_launcher=1 Include_tcltk=1 Include_pip=1
del "%DEST%" >nul 2>nul
exit /b 0

:ensure_vcredist
rem Install the Visual C++ 2015-2022 redistributable matching the Python bit (it self-elevates via UAC).
set "RA=x64"
if not defined BIT64 set "RA=x86"
set "VURL=https://aka.ms/vs/17/release/vc_redist.%RA%.exe"
set "VDEST=%TEMP%\lazyk_vcredist_%RA%.exe"
echo Installing the Microsoft Visual C++ Runtime (%RA%) - please click Yes if Windows asks ...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; try { [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -UseBasicParsing '%VURL%' -OutFile '%VDEST%' } catch { exit 1 }"
if not exist "%VDEST%" (echo Could not download the VC++ runtime. & exit /b 1)
"%VDEST%" /install /passive /norestart
del "%VDEST%" >nul 2>nul
exit /b 0

:check_venv
if /i not "%OLD%"=="%HERE%" goto :rebuild
.venv\Scripts\python.exe -c "import sys;v=sys.version_info;sys.exit(0 if (3,10)<=(v[0],v[1])<=(3,12) else 1)" >nul 2>nul || goto :rebuild
exit /b 0
:rebuild
echo Old .venv is from another folder or uses an unsupported Python - recreating it...
rmdir /s /q .venv
exit /b 0
