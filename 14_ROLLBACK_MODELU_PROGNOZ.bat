@echo off
setlocal
rem Przywraca poprzedni zgodny model prognoz (atomowo). Bez wczesniejszego zgodnego modelu: 14_ROLLBACK_MODELU_PROGNOZ.bat BRAK
rem ustawia brak aktywnego modelu (monitor pokaze NO_MODEL). Nie zmienia strategii, ryzyka ani otwartych pozycji.
cd /d "%~dp0"
if not exist "%~dp0.venv_candles\Scripts\python.exe" (echo [BLAD] Brak .venv_candles & pause & exit /b 1)
set "PYTHONPATH=%~dp0backend"
pushd "%~dp0backend"
if /i "%~1"=="BRAK" (
  "%~dp0.venv_candles\Scripts\python.exe" -m gold_candles_runtime.registry_cli deactivate
) else (
  "%~dp0.venv_candles\Scripts\python.exe" -m gold_candles_runtime.registry_cli rollback
)
set "RC=%ERRORLEVEL%"
popd
echo Monitor uzyje zmiany przy nastepnej zamknietej M5.
pause
exit /b %RC%
