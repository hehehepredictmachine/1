@echo off
setlocal
rem 1.40.3: Python w trybie UTF-8 - polskie znaki i symbole w logach nie przerywaja skryptu (UnicodeEncodeError przy cp1250)
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
rem Walidacja rejestru modeli scalp: checksumy artefaktow, kontrakt cech, odczyt przez sciezke workera bota, lista statusow.
cd /d "%~dp0"
if not exist "%~dp0.venv_candles\Scripts\python.exe" (echo [BLAD] Brak .venv_candles & pause & exit /b 1)
set "PYTHONPATH=%~dp0backend"
pushd "%~dp0backend"
"%~dp0.venv_candles\Scripts\python.exe" -m gold_candles_runtime.scalp_registry validate
set "RC=%ERRORLEVEL%"
"%~dp0.venv_candles\Scripts\python.exe" -m gold_candles_runtime.scalp_registry list
popd
pause
exit /b %RC%
