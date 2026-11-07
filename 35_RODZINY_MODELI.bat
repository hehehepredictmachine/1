@echo off
setlocal EnableExtensions
set "MQ_PAUSE=pause"
if defined MQ_NO_PAUSE set "MQ_PAUSE=type nul"
rem PepeMarketWizard 1.33 - rodziny modeli (ARIMA, SARIMAX, GARCH, mikrostruktura, kointegracja, StatArb, Kalman, breakout, LSTM, GRU,
rem PPO, NLP). Uzycie:  35_RODZINY_MODELI.bat [XAUUSD|BTC] [smoke|research|full]
rem Trening NIE aktywuje modeli; aktywacja i rola SHADOW/ASSIST w panelu. Raport rozdziela DONE / BLOCKED / FAILED.
cd /d "%~dp0"
set "INST=%~1"
if "%INST%"=="" set "INST=XAUUSD"
set "PROF=%~2"
if "%PROF%"=="" set "PROF=smoke"
set "PY=%~dp0.venv\Scripts\python.exe"
if exist "%~dp0runtime\python\python.exe" if not exist "%PY%" set "PY=%~dp0runtime\python\python.exe"
if not exist "%PY%" (
  echo [BLAD] Brak srodowiska bota - uruchom najpierw 01_INSTALUJ.bat
  %MQ_PAUSE%
  exit /b 1
)
chcp 65001 >nul
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
pushd "%~dp0backend"
"%PY%" -m masterquo families train-all --instrument %INST% --profile %PROF%
set "RC=%ERRORLEVEL%"
popd
if not "%RC%"=="0" echo [UWAGA] Zaden model nie zostal wytrenowany ^(brak danych / zaleznosci^) - zobacz raport powyzej.
%MQ_PAUSE%
exit /b %RC%
