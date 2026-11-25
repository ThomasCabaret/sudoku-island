@echo off
setlocal
cd /d "%~dp0"
python -m benchmarks.campaign status --watch %*
echo.
pause
