@echo off
rem Quality check: compares the old code with the new code and opens a report.
rem   quality.bat          full run (settings in quality.json)
rem   quality.bat audit    audit only, no model
rem   quality.bat report   rebuild the latest report after saving review.json
rem   quality.bat judge    let the model judge the latest run blind
rem   quality.bat clean    remove the old code copies
cd /d "%~dp0"
set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
"%PY%" -m tests.quality %*
if not defined QUALITY_NO_PAUSE pause
