@echo off
title A-Share Review - stopping...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop.ps1"
timeout /t 2 >nul
