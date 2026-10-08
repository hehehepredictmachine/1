@echo off
setlocal
cd /d "%~dp0"
if not exist "%~dp0.venv\Scripts\python.exe" (
  echo [BLAD] Brak .venv - uruchom najpierw 01_INSTALUJ.bat
  pause
  exit /b 1
)
echo [MasterQUO] Diagnostyka srodowiska, terminala MT5 i agenta Claude (bez zlecen).
pushd "%~dp0backend"
"%~dp0.venv\Scripts\python.exe" -m masterquo doctor
set "RC=%ERRORLEVEL%"
popd
pause
exit /b %RC%
