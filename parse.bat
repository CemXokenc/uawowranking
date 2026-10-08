@echo off
REM Get the folder path where this script is located
cd /d "%~dp0"

REM Run the python script
python parse.py
