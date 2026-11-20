@echo off
setlocal
rem 1.40.3: Python w trybie UTF-8 - polskie znaki i symbole w logach nie przerywaja skryptu (UnicodeEncodeError przy cp1250)
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"
if not exist "%~dp0.venv\Scripts\python.exe" (
  echo [BLAD] Brak .venv
  pause
  exit /b 1
)
rem Zatrzymuje wylacznie serwer PepeMarketWizard (token z data\runtime). Nie zamyka MT5 ani innych programow Python.
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
