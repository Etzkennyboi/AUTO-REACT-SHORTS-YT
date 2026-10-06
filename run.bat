@echo off
title React Stack
echo.
echo  ========================================
echo    React Stack - Starting Server
echo  ========================================
echo.
set "PATH=%USERPROFILE%\AppData\Roaming\Python\Python314\Scripts;%APPDATA%\Python\Python314\Scripts;%PATH%"
echo  Checking dependencies...
python -m pip install -r requirements.txt -q
echo.
echo  Open http://localhost:8000 in your browser
echo  Press Ctrl+C to stop.
echo.
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload

