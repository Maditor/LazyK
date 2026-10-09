@echo off
setlocal
cd /d "%~dp0"
echo === LazyK setup ===

rem A .venv copied or moved from another folder still points to the old path -> rebuild it.
set "HERE=%~dp0"
set "MARK=.venv\lazyk_path.txt"
if exist .venv (
    set "OLD="
    if exist "%MARK%" set /p OLD=<"%MARK%"
    call :check_venv
)

if not exist .venv\Scripts\python.exe (
    echo Creating .venv ...
    where py >nul 2>nul && (py -3.11 -m venv .venv) || (python -m venv .venv)
    if not exist .venv\Scripts\python.exe (echo Could not create venv. Install Python 3.11 first. & pause & exit /b 1)
)
> "%MARK%" echo %HERE%

set "PY=.venv\Scripts\python.exe"
"%PY%" -m pip install --upgrade pip
"%PY%" -m pip install -r requirements.txt
if errorlevel 1 (echo Install failed. & pause & exit /b 1)
rem Local OCR engine (PaddleOCR models, PP-OCRv6 built in)
"%PY%" -m pip install --no-deps rapidocr==3.9.2
if errorlevel 1 (echo Install failed. & pause & exit /b 1)
rem Local voice (Piper). --no-deps: it would add a second onnxruntime next to onnxruntime-directml
"%PY%" -m pip install --no-deps piper-tts==1.8.0 pathvalidate
if errorlevel 1 (echo Install failed. & pause & exit /b 1)
echo.
echo Done. Start with run.bat
pause
exit /b 0

:check_venv
if /i not "%OLD%"=="%HERE%" goto :rebuild
.venv\Scripts\python.exe -c "import sys" >nul 2>nul || goto :rebuild
exit /b 0
:rebuild
echo Old .venv belongs to another folder or is broken - recreating it...
rmdir /s /q .venv
exit /b 0
