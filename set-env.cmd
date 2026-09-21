@echo off
setlocal
set ENV=%1
if "%ENV%"=="" set ENV=int
if /I "%ENV%"=="int" copy /Y "%~dp0env\int.env" "%~dp0.env" >nul
if /I "%ENV%"=="syst" copy /Y "%~dp0env\syst.env" "%~dp0.env" >nul
if /I "%ENV%"=="accept" copy /Y "%~dp0env\accept.env" "%~dp0.env" >nul
if not "%ENV%"=="int" if not "%ENV%"=="syst" if not "%ENV%"=="accept" (
    echo Usage: set-env.cmd ^<int^|syst^|accept^>
    exit /b 1
)
echo Selected environment: %ENV%
