param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Args)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

$pythonExe = Join-Path $scriptDir ".venv/Scripts/python.exe"
if (-not (Test-Path $pythonExe)) {
    Write-Host "Virtual environment not found at $pythonExe"
    Write-Host "Please create it with: py -m venv .venv"
    exit 1
}

if (-not $Args -or $Args.Count -eq 0) {
    $Args = @("--daily")
}

Write-Host "Running planner with: $($Args -join ' ')"
& $pythonExe "plan.py" @Args

if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "Open output/planner_dashboard.html in your browser when the run finishes."
