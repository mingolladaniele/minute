@echo off
rem Double-click to simulate a 3-minute call and watch minute take notes on its own.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0simulate-call.ps1" %*
pause
