@echo off
setlocal
rem Start bota z profilem scalp i kontrolerem hedge w trybie SHADOW (MODE=SHADOW, LIVE_TRADING=false, ML_EXECUTION=false,
rem HEDGE_EXECUTION=false - konfiguracja nie przyjmuje innych wartosci). Monitor: Wykresy bota - sekcja "Scalp M5 Range".
cd /d "%~dp0"
if exist "%~dp0.venv_candles\Scripts\python.exe" (
  set "PYTHONPATH=%~dp0backend"
  pushd "%~dp0backend"
  "%~dp0.venv_candles\Scripts\python.exe" -m gold_candles_runtime.scalp_registry list
  popd
) else (
  echo [UWAGA] Brak .venv_candles - prognozy 1/3/5 min beda UNAVAILABLE; automat i bramki SHADOW dzialaja bez nich.
)
call "%~dp003_START_MASTERQUO.bat"
