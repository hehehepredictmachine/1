@echo off
setlocal
rem Trening prognoz 5/15/30 min na NAJNOWSZYM eksporcie (data\forecast\history). Tick size i symbol z source_metadata.json.
rem Plan z granicami UTC jest zamrazany przed treningiem; holdout oceniany raz. Wynik: data\forecast\runs\^<run_id^>\.
rem Trening dziala w osobnym procesie - bot moze w tym czasie pracowac. Brak zgody na zlecenia (tylko SHADOW).
cd /d "%~dp0"
if not exist "%~dp0.venv_candles\Scripts\python.exe" (echo [BLAD] Brak .venv_candles - uruchom 10_PROGNOZY_INSTALUJ.bat & pause & exit /b 1)
set "PYTHONPATH=%~dp0backend"
pushd "%~dp0backend"
"%~dp0.venv_candles\Scripts\python.exe" -m gold_candles_runtime.plan_train --latest
set "RC=%ERRORLEVEL%"
popd
if "%RC%"=="0" (
  echo [OK] Trening zakonczony - raport: data\forecast\runs\^<run_id^>\forecast_validation.json
  echo      Monitor przelaczy sie na nowy model przy nastepnej zamknietej M5 ^(Wykresy bota - Swiece i prognozy^).
) else (
  echo [BLAD/BLOKADA] kod %RC% - opis powyzej ^(np. BLOCKED_NO_REAL_DATA, INSUFFICIENT_DATA^)
)
pause
exit /b %RC%
