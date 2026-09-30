@echo off
cd /d "%~dp0game"
if exist "%LOCALAPPDATA%\Programs\Python\Python314\python.exe" (
    "%LOCALAPPDATA%\Programs\Python\Python314\python.exe" main.py
) else (
    python main.py
)
if errorlevel 1 pause
