param([switch]$EnableStartup)

$ErrorActionPreference = "Stop"
$AppRoot = Split-Path -Parent $PSScriptRoot
$Venv = Join-Path $AppRoot ".venv"
$Python = Join-Path $Venv "Scripts\python.exe"
$Launcher = Join-Path $AppRoot "start-api-budget.cmd"

if (-not (Test-Path $Python)) {
    py -3 -m venv $Venv
}

& $Python -m pip install --upgrade pip
& $Python -m pip install -r (Join-Path $AppRoot "requirements.txt")

$AppPy = Join-Path $AppRoot "app.py"
$launcherText = "@echo off`r`nstart `"`" `"$Python`" `"$AppPy`"`r`n"
Set-Content -Path $Launcher -Value $launcherText -Encoding ASCII

if ($EnableStartup) {
    $Startup = [Environment]::GetFolderPath("Startup")
    $ShortcutPath = Join-Path $Startup "API Budget.lnk"
    $Shell = New-Object -ComObject WScript.Shell
    $Shortcut = $Shell.CreateShortcut($ShortcutPath)
    $Shortcut.TargetPath = $Launcher
    $Shortcut.WorkingDirectory = $AppRoot
    $Shortcut.Save()
    Write-Host "Startup shortcut installed: $ShortcutPath"
}

Write-Host "Installed. Launch with: $Launcher"
Write-Host "Config and secrets are created on first launch under %LOCALAPPDATA%\ApiBudgetMonitor."
