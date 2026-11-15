@echo off
setlocal
rem Launch the XB-SVCB installer with a writable TEMP/TMP.
rem Usage: Start-Setup.cmd [path-to-setup.exe]

set "SETUP=%~1"
if not defined SETUP (
  for %%F in ("%~dp0..\dist\XB-SVCB-Setup-*.exe") do (
    set "SETUP=%%~fF"
    goto :have_setup
  )
)
:have_setup
if not defined SETUP (
  echo No installer found under dist\XB-SVCB-Setup-*.exe
  echo Pass the setup path explicitly:
  echo   Start-Setup.cmd "X:\path\XB-SVCB-Setup-CPU.exe"
  pause
  exit /b 1
)
if not exist "%SETUP%" (
  echo Installer not found: %SETUP%
  pause
  exit /b 1
)

set "XB_TMP="
call :trytemp "%TEMP%"
if not defined XB_TMP call :trytemp "%LOCALAPPDATA%\XB-SVCB\setup-temp"
if not defined XB_TMP call :trytemp "%~dp0setup-temp"
if not defined XB_TMP call :trytemp "%USERPROFILE%\XB-SVCB-setup-temp"
if not defined XB_TMP (
  echo No writable temp folder found.
  echo Right-click this file and choose "Run as administrator", or fix TEMP permissions.
  pause
  exit /b 1
)

set "XB_LOG=%XB_TMP%\launcher.log"
> "%XB_LOG%" echo [%DATE% %TIME%] setup=%SETUP%
>> "%XB_LOG%" echo TEMP was: %TEMP%
>> "%XB_LOG%" echo TMP  was: %TMP%
>> "%XB_LOG%" echo USER: %USERDOMAIN%\%USERNAME%
>> "%XB_LOG%" echo using TEMP: %XB_TMP%
echo Launcher log: %XB_LOG%

set "TEMP=%XB_TMP%"
set "TMP=%XB_TMP%"
start "" /wait "%SETUP%" /SP-
set "CODE=%ERRORLEVEL%"
>> "%XB_LOG%" echo exit=%CODE%
echo Installer exit code: %CODE%
pause
exit /b %CODE%

:trytemp
if "%~1"=="" exit /b 0
mkdir "%~1" >nul 2>nul
if not exist "%~1" exit /b 0
> "%~1\.xb-write-test" echo ok
if not exist "%~1\.xb-write-test" exit /b 0
del "%~1\.xb-write-test" >nul 2>nul
set "XB_TMP=%~1"
exit /b 0
