@echo off
cd /d "%~dp0"
echo =============================================
echo Universal Solutions - Billing System Setup
echo =============================================
python -m venv venv
call venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo Installation failed. Please send this window screenshot.
  pause
  exit /b 1
)
echo.
echo Setup completed successfully.
echo Run start.bat to open the application.
pause
