@echo off
setlocal
cd /d "%~dp0"

set PYTHON_EXE=.venv\Scripts\python.exe
if not exist "%PYTHON_EXE%" (
  echo Virtual environment not found at %PYTHON_EXE%
  echo Please create it with: py -m venv .venv
  exit /b 1
)

rem Start Ollama in the background if it isn't answering yet; Generate plan and Ask AI need it.
curl -s -o nul -m 2 http://localhost:11434/api/tags
if errorlevel 1 (
  where ollama >nul 2>nul
  if errorlevel 1 (
    echo Ollama isn't running and isn't on PATH, so Generate plan and Ask AI will be unavailable.
  ) else (
    echo Starting Ollama...
    start "Ollama" /min ollama serve
  )
)

rem --open launches the browser once the server is listening.
"%PYTHON_EXE%" server.py --open
