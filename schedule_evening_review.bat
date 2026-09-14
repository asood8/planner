@echo off
rem Schedules the end-of-day review notification. Usage: schedule_evening_review.bat [HH:MM]  (default 21:00)
rem Remove it later with: schtasks /Delete /TN "Planner evening review" /F
setlocal
cd /d "%~dp0"

set RUN_AT=%~1
if "%RUN_AT%"=="" set RUN_AT=21:00

schtasks /Create /F /SC DAILY /ST %RUN_AT% /TN "Planner evening review" /TR "\"%~dp0run_planner.bat\" --review"
if errorlevel 1 exit /b %errorlevel%

echo.
echo Scheduled "Planner evening review" every day at %RUN_AT%. It runs while you're logged in.
echo Remove it with: schtasks /Delete /TN "Planner evening review" /F
