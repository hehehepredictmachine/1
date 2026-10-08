@echo off
setlocal
cd /d "%~dp0"
if not exist "%~dp0.venv\Scripts\python.exe" (
  echo [BLAD] Brak .venv
  pause
  exit /b 1
)
rem Zatrzymuje wylacznie serwer MasterQUO (token z data\runtime). Nie zamyka MT5 ani innych programow Python.
pushd "%~dp0backend"
"%~dp0.venv\Scripts\python.exe" -m masterquo stop
set "RC=%ERRORLEVEL%"
if exist "%~dp0data\demo_synthetic\runtime\shutdown.token" (
  set "MASTERQUO_DATA_DIR=%~dp0data\demo_synthetic"
  "%~dp0.venv\Scripts\python.exe" -m masterquo stop
)
popd
timeout /t 3 >nul
exit /b %RC%
