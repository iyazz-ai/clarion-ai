@echo off
REM Runs the Clarion pipeline. Put this file next to manage.py.
REM Scheduled with Windows Task Scheduler (every 4 hours).

cd /d "%~dp0"
if not exist logs mkdir logs

REM UTF-8 so headlines with ' " and accents are written correctly to the log
chcp 65001 >nul
set PYTHONIOENCODING=utf-8

call venv\Scripts\activate

echo ===== %date% %time% ===== >> logs\update.log
python manage.py update_news >> logs\update.log 2>&1
echo exit code: %errorlevel% >> logs\update.log
