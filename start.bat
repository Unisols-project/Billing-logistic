@echo off
cd /d "%~dp0"
if not exist venv\Scripts\python.exe (
  echo Virtual environment not found.
  echo Please run setup.bat first.
  pause
  exit /b 1
)
call venv\Scripts\activate.bat
python run.py
if errorlevel 1 (
  echo.
  echo Application stopped with an error.
  pause
)
