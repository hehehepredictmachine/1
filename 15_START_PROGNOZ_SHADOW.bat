@echo off
setlocal
rem Start bota z analityka swiec i prognozami w trybie SHADOW (obserwacja, EXECUTION LOCK - bez zgody na zlecenia).
rem Prognozy sa wlaczone domyslnie (data\config.json: forecast.enabled=true); ten plik sprawdza srodowisko i uruchamia monitor.
cd /d "%~dp0"
if not exist "%~dp0.venv_candles\Scripts\python.exe" (
  echo [UWAGA] Brak .venv_candles - monitor pokaze NO_CANDLE_ENV. Uruchom najpierw 10_PROGNOZY_INSTALUJ.bat.
) else (
  set "PYTHONPATH=%~dp0backend"
  pushd "%~dp0backend"
  "%~dp0.venv_candles\Scripts\python.exe" -m gold_candles_runtime.registry_cli list
  popd
)
call "%~dp003_START_MASTERQUO.bat"
