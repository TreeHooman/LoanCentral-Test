# Make Windows keep the LoanCentral bot running.
#
#   powershell -ExecutionPolicy Bypass -File scripts\install_bot_task.ps1              # install / update
#   powershell -ExecutionPolicy Bypass -File scripts\install_bot_task.ps1 -Uninstall   # remove it
#
# Registers the scheduled task "LoanCentral Bot", which launches
# scripts\run_bot_forever.py (the supervisor) with pythonw, so no window:
#   - when you sign in to Windows, and
#   - every 5 minutes after that. If the supervisor is already running the new
#     launch exits at once (it holds a lock), so this only matters when the
#     supervisor was closed or crashed: it is back within 5 minutes.
# The supervisor itself restarts the bot if it crashes or freezes.
#
# Unlike `schtasks /Create`, this turns off Task Scheduler's default 3-day
# limit, which would otherwise stop the bot every 72 hours.
#
# Run it from the 2.0 folder on the bot computer, never on the old bot's folder.
# Check on the bot:  python scripts\run_bot_forever.py --status
# Stop it for real:  python scripts\run_bot_forever.py --stop   (the task then
#                    leaves it stopped until you run it with --start)

param([switch]$Uninstall)

$ErrorActionPreference = "Stop"
$TaskName = "LoanCentral Bot"

if ($Uninstall) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Removed the '$TaskName' task. A bot that is running now keeps running until you stop it:"
    Write-Host "  python scripts\run_bot_forever.py --stop"
    exit 0
}

$Root = Split-Path -Parent $PSScriptRoot
$Supervisor = Join-Path $Root "scripts\run_bot_forever.py"
if (-not (Test-Path (Join-Path $Root "main.py"))) {
    throw "main.py not found next to scripts\ ($Root). Run this from the LoanCentral 2.0 folder."
}

# pythonw.exe sits next to python.exe; it runs without a console window.
$Python = (Get-Command python -ErrorAction Stop).Source
$PythonW = Join-Path (Split-Path $Python) "pythonw.exe"
if (-not (Test-Path $PythonW)) {
    throw "pythonw.exe not found next to $Python. Install Python from python.org (it includes pythonw)."
}

$Action = New-ScheduledTaskAction -Execute $PythonW -Argument "`"$Supervisor`"" -WorkingDirectory $Root
$Triggers = @(
    (New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME),
    (New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5))
)
$Settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Triggers -Settings $Settings `
    -Description "Keeps the LoanCentral Reddit bot running (scripts\run_bot_forever.py)." -Force | Out-Null

Write-Host "Installed '$TaskName'. The bot starts within a minute and at every sign-in."
Write-Host "Check it:  python scripts\run_bot_forever.py --status"
Write-Host ""
Write-Host "Also on the bot computer:"
Write-Host "  - Never sleep while plugged in:  powercfg /change standby-timeout-ac 0"
Write-Host "  - After a reboot Windows must sign in for the task to run (automatic sign-in, or sign in yourself)."
