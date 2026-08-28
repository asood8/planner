@echo off
setlocal
cd /d "%~dp0"

set PYTHON_EXE=.venv\Scripts\python.exe
if not exist "%PYTHON_EXE%" (
  echo Virtual environment not found at %PYTHON_EXE%
  echo Please create it with: py -m venv .venv
  exit /b 1
)

echo Running planner (weekly)
"%PYTHON_EXE%" plan.py --weekly

if errorlevel 1 (
  exit /b %errorlevel%
)

echo.
echo Weekly dashboard written to output\planner_dashboard.html
