@echo off
title Atlas Financial Assistant Bot Daemon
echo Starting Atlas Financial Assistant Bot...
cd /d "%~dp0"
$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
python run.py
pause
