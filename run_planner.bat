@echo off
setlocal
cd /d "%~dp0"

set PYTHON_EXE=.venv\Scripts\python.exe
if not exist "%PYTHON_EXE%" (
  echo Virtual environment not found at %PYTHON_EXE%
  echo Please create it with: py -m venv .venv
  exit /b 1
)

if "%~1"=="" (
  set ARGS=--daily
) else (
  set ARGS=%*
)

echo Running planner with: %ARGS%
"%PYTHON_EXE%" plan.py %ARGS%

if errorlevel 1 (
  exit /b %errorlevel%
)

echo.
echo Open output\planner_dashboard.html in your browser when the run finishes.
