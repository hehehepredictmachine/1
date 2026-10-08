@echo off
setlocal
cd /d "%~dp0"
if not exist "%~dp0.venv\Scripts\python.exe" (
  echo [BLAD] Brak .venv - uruchom najpierw 01_INSTALUJ.bat
  pause
  exit /b 1
)
echo [MasterQUO] Testy offline (symulator terminala, atrapa API Claude). Nie potwierdzaja polaczenia z Twoim MT5.
echo            Dodatkowo oryginalne testy regresji MasterQUO: 05_TESTY_OFFLINE.bat --legacy
"%~dp0.venv\Scripts\python.exe" "%~dp0tools\run_tests.py" %*
set "RC=%ERRORLEVEL%"
pause
exit /b %RC%
