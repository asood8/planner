@echo off
rem Schedules a daily plan with a Windows notification. Usage: schedule_morning_plan.bat [HH:MM]  (default 07:00)
rem Remove it later with: schtasks /Delete /TN "Planner morning plan" /F
setlocal
cd /d "%~dp0"

set RUN_AT=%~1
if "%RUN_AT%"=="" set RUN_AT=07:00

schtasks /Create /F /SC DAILY /ST %RUN_AT% /TN "Planner morning plan" /TR "\"%~dp0run_planner.bat\" --daily --notify"
if errorlevel 1 exit /b %errorlevel%

echo.
echo Scheduled "Planner morning plan" every day at %RUN_AT%. It runs while you're logged in.
echo Remove it with: schtasks /Delete /TN "Planner morning plan" /F
