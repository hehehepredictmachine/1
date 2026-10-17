@echo off
rem PepeMarketWizard - wspolny, cienki launcher treningu. Cala logika: backend\masterquo\training (Python).
rem Bez EnableDelayedExpansion - sciezki ze spacjami, znakami narodowymi i ! dzialaja.
setlocal
chcp 65001 >nul
for %%I in ("%~dp0..") do set "ROOT=%%~fI"
set "PY=%ROOT%\.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo [BLAD] Brak srodowiska .venv - uruchom INSTALUJ_TRENING.bat
  exit /b 2
)
if exist "%ROOT%\.venv_candles\Scripts\python.exe" set "MQ_CANDLES_PYTHON=%ROOT%\.venv_candles\Scripts\python.exe"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
if not exist "%ROOT%\data\logs" mkdir "%ROOT%\data\logs"
pushd "%ROOT%\backend"
"%PY%" -m masterquo training %*
set "RC=%ERRORLEVEL%"
popd
exit /b %RC%
