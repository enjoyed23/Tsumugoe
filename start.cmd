@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONDONTWRITEBYTECODE=1
set PYTHONIOENCODING=utf-8
py -3 -B app.py
if errorlevel 1 pause
