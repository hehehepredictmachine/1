@echo off
setlocal
rem Ponowna walidacja aktywnego modelu: checksum, zgodnosc kontraktu z obecnym kodem, odczyt przez sciezke bota, tabela jakosci.
cd /d "%~dp0"
if not exist "%~dp0.venv_candles\Scripts\python.exe" (echo [BLAD] Brak .venv_candles - uruchom 10_PROGNOZY_INSTALUJ.bat & pause & exit /b 1)
set "PYTHONPATH=%~dp0backend"
pushd "%~dp0backend"
"%~dp0.venv_candles\Scripts\python.exe" -m gold_candles_runtime.registry_cli list
"%~dp0.venv_candles\Scripts\python.exe" -m gold_candles_runtime.validate %*
set "RC=%ERRORLEVEL%"
popd
pause
exit /b %RC%
