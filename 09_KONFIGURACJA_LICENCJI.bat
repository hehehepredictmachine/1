@echo off
setlocal
cd /d "%~dp0"
rem Jednorazowa konfiguracja: adres serwera licencji + klucz publiczny (bez klucza licencji).
if not exist "%~dp0.venv\Scripts\python.exe" (
  echo [BLAD] Brak .venv - uruchom najpierw 01_INSTALUJ.bat
  pause
  exit /b 1
)
cd /d "%~dp0backend"
"%~dp0.venv\Scripts\python.exe" -m masterquo license-setup
pause
