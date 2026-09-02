@echo off
rem Locate a real CPython 3.10.x interpreter and export its absolute path.
rem This file intentionally does not use setlocal: callers consume XB_PYTHON_*.

set "XB_PYTHON_DETECTED="
rem Values left by an earlier installer run are candidates only. They must
rem pass the executable/version probe below before being exported again.
set "XB_PYTHON_CANDIDATE_EXE=%XB_PYTHON_EXE%"
set "XB_PYTHON_CANDIDATE_DIR=%XB_PYTHON_DIR%"
set "XB_PYTHON_EXE="
set "XB_PYTHON_DIR="

rem Honour an explicit executable or directory before probing global commands.
if defined XB_PYTHON_CANDIDATE_EXE call :TRY_PYTHON "%XB_PYTHON_CANDIDATE_EXE%"
if defined XB_PYTHON_DETECTED goto PYTHON_FOUND
if defined XB_PYTHON_CANDIDATE_DIR call :TRY_PYTHON "%XB_PYTHON_CANDIDATE_DIR%\python.exe"
if defined XB_PYTHON_DETECTED goto PYTHON_FOUND

rem Python's launcher resolves Store installs and installations outside PATH.
where py >nul 2>&1 && (
  for /f "delims=" %%P in ('py -3.10 -c "import sys; print(sys.executable)" 2^>nul') do if not defined XB_PYTHON_DETECTED call :TRY_PYTHON "%%P"
)
if defined XB_PYTHON_DETECTED goto PYTHON_FOUND

rem Check every PATH result. The first one may be the non-runnable WindowsApps alias.
for /f "delims=" %%P in ('where python 2^>nul') do if not defined XB_PYTHON_DETECTED call :TRY_PYTHON "%%P"
if defined XB_PYTHON_DETECTED goto PYTHON_FOUND

rem Keep the common per-user CPython 3.10 location as a final fallback.
call :TRY_PYTHON "%LocalAppData%\Programs\Python\Python310\python.exe"
if defined XB_PYTHON_DETECTED goto PYTHON_FOUND

set "XB_PYTHON_EXE="
set "XB_PYTHON_DIR="
set "XB_PYTHON_CANDIDATE_EXE="
set "XB_PYTHON_CANDIDATE_DIR="
exit /b 1

:PYTHON_FOUND
set "XB_PYTHON_EXE=%XB_PYTHON_DETECTED%"
for %%D in ("%XB_PYTHON_EXE%") do set "XB_PYTHON_DIR=%%~dpD"
if "%XB_PYTHON_DIR:~-1%"=="\" set "XB_PYTHON_DIR=%XB_PYTHON_DIR:~0,-1%"
set "XB_PYTHON_DETECTED="
set "XB_PYTHON_CANDIDATE_EXE="
set "XB_PYTHON_CANDIDATE_DIR="
exit /b 0

:TRY_PYTHON
if "%~1"=="" exit /b 1
if not exist "%~1" exit /b 1
rem A trailing slash is not a reliable directory test on Windows: it can
rem also match a runnable python.exe. The execution probe rejects directories.
"%~1" -c "import sys; raise SystemExit(0 if sys.implementation.name == 'cpython' and sys.version_info[:2] == (3, 10) and sys.maxsize > 2**32 else 1)" >nul 2>&1
if errorlevel 1 exit /b 1
set "XB_PYTHON_DETECTED=%~f1"
exit /b 0
