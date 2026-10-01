@echo off
rem FemisBot GUI launcher - double-click this file to run the bot console.
rem (Double-clicking bot_gui.py itself opens it in VS Code because .py files
rem are associated with the editor on this machine.)
cd /d "%~dp0"
python bot_gui.py
if errorlevel 1 pause
