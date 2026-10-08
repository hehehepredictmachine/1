@echo off
setlocal
cd /d "%~dp0"
if not exist "%~dp0.venv\Scripts\python.exe" (
  echo [BLAD] Brak .venv - uruchom najpierw 01_INSTALUJ.bat
  pause
  exit /b 1
)
echo [MasterQUO] Diagnoza czasu MT5: surowe czasy tickow i swiec, zmierzony offset serwera, zegar PC.
echo            Najlepiej uruchomic przy otwartym rynku. Bez zlecen.
pushd "%~dp0backend"
"%~dp0.venv\Scripts\python.exe" -m masterquo clock
set "RC=%ERRORLEVEL%"
popd
pause
exit /b %RC%
