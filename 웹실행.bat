@echo off
cd /d "%~dp0"
echo Open http://127.0.0.1:8766 in your browser.
echo Press Ctrl+C to stop the web server.
if exist "%LOCALAPPDATA%\Programs\Python\Python314\python.exe" (
    "%LOCALAPPDATA%\Programs\Python\Python314\python.exe" -m http.server 8766 --bind 127.0.0.1
) else (
    python -m http.server 8766 --bind 127.0.0.1
)
