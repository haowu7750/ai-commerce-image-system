@echo off
setlocal
chcp 65001 >nul
set "APP_IMAGE_PROVIDER=shulicode"
set "APP_IMAGE_MODEL=gpt-image-2"
echo Real image mode: Shulicode / gpt-image-2.
echo No request is sent during startup. A paid request is sent only after the operator clicks Generate.
call "%~dp0Start-System.cmd" %*
set "EXIT_CODE=%ERRORLEVEL%"
endlocal & exit /b %EXIT_CODE%
