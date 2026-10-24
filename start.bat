@echo off
rem Start this PC's sites (Home Page server). First run: creates the virtual environment and the logon task.
cd /d "%~dp0"
py -3 launcher.py %*
if errorlevel 1 pause
