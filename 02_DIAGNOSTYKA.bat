@echo off
setlocal
rem 1.40.3: Python w trybie UTF-8 - polskie znaki i symbole w logach nie przerywaja skryptu (UnicodeEncodeError przy cp1250)
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"
if not exist "%~dp0.venv\Scripts\python.exe" (
  echo [BLAD] Brak .venv - uruchom najpierw 01_INSTALUJ.bat
  pause
  exit /b 1
)
echo [PepeMarketWizard] Diagnostyka srodowiska, terminala MT5 i agenta Claude (bez zlecen).
pushd "%~dp0backend"
"%~dp0.venv\Scripts\python.exe" -m masterquo doctor
set "RC=%ERRORLEVEL%"
popd
pause
exit /b %RC%
