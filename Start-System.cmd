@echo off
setlocal
chcp 65001 >nul
set "PROJECT_ROOT=%~dp0"
if not defined APP_IMAGE_PROVIDER set "APP_IMAGE_PROVIDER=mock"
set "APP_TEXT_PROVIDER=mock"
set "APP_VISION_PROVIDER=mock"
if not defined APP_IMAGE_MODEL set "APP_IMAGE_MODEL=gpt-image-2"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

if not exist "%PROJECT_ROOT%.venv\Scripts\python.exe" (
  echo Project Python environment is missing: %PROJECT_ROOT%.venv\Scripts\python.exe
  pause
  exit /b 1
)

"%PROJECT_ROOT%.venv\Scripts\python.exe" "%PROJECT_ROOT%scripts\start_local.py" %*
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" pause
endlocal & exit /b %EXIT_CODE%
