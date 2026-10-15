@echo off
setlocal
rem Przywraca poprzedni zgodny model scalp (atomowo). 21_ROLLBACK_MODELU_SCALP.bat BRAK = brak aktywnego modelu (NO_MODEL).
rem Nie zmienia strategii, ryzyka ani otwartych pozycji. Zmiana dziala od nastepnej zamknietej M1.
cd /d "%~dp0"
if not exist "%~dp0.venv_candles\Scripts\python.exe" (echo [BLAD] Brak .venv_candles & pause & exit /b 1)
set "PYTHONPATH=%~dp0backend"
pushd "%~dp0backend"
if /i "%~1"=="BRAK" (
  "%~dp0.venv_candles\Scripts\python.exe" -m gold_candles_runtime.scalp_registry deactivate
) else (
  "%~dp0.venv_candles\Scripts\python.exe" -m gold_candles_runtime.scalp_registry rollback
)
set "RC=%ERRORLEVEL%"
popd
pause
exit /b %RC%
