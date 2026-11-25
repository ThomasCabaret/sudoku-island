@echo off
setlocal
cd /d "%~dp0"
python -m benchmarks.campaign start %*
echo.
pause
