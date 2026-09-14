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

rem The evening review doesn't use the model, so it doesn't need Ollama.
echo %ARGS% | findstr /c:"--review" >nul || call :ensure_ollama

echo Running planner with: %ARGS%
"%PYTHON_EXE%" plan.py %ARGS%

if errorlevel 1 (
  exit /b %errorlevel%
)

echo.
echo Open output\planner_dashboard.html in your browser when the run finishes.
exit /b 0

:ensure_ollama
rem Start Ollama if it isn't answering, then wait up to about 20 seconds for it; the plan needs it.
curl -s -o nul -m 2 http://localhost:11434/api/tags && exit /b 0
where ollama >nul 2>nul || (
  echo Ollama isn't running and isn't on PATH, so the plan will fall back to raw context.
  exit /b 0
)
echo Starting Ollama...
start "Ollama" /min ollama serve
rem ping is used as a sleep because timeout fails when there is no console, e.g. under Task Scheduler.
for /l %%i in (1,1,20) do (
  ping -n 2 127.0.0.1 >nul
  curl -s -o nul -m 2 http://localhost:11434/api/tags && exit /b 0
)
echo Ollama didn't start in time.
exit /b 0
