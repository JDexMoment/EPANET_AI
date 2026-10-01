@echo off
REM ====================================================================
REM  EPANET 2.2 Local AI & Engineering Analytics Service launcher
REM  Run this BEFORE clicking the "AI" button in epanet2w.exe
REM ====================================================================
cd /d "%~dp0"
echo.
echo Starting EPANET 2.2 AI Service on http://127.0.0.1:8765 ...
echo Press Ctrl+C to stop.
echo.
python -m ai_module.run_service --host 127.0.0.1 --port 8765
pause
