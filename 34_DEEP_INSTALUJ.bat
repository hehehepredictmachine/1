@echo off
setlocal EnableExtensions EnableDelayedExpansion
set "MQ_PAUSE=pause"
if defined MQ_NO_PAUSE set "MQ_PAUSE=type nul"
rem PepeMarketWizard 1.33 - instalacja izolowanego srodowiska .venv_deep (PyTorch CPU, Gymnasium, Stable-Baselines3) dla modeli
rem SEQ_LSTM, SEQ_GRU i RL_PPO. Pakiety tylko z sumami SHA-256. Glowne .venv bota i .venv_kronos NIE sa zmieniane.
cd /d "%~dp0"
set "ROOT=%~dp0"
if not exist "%ROOT%data\logs" mkdir "%ROOT%data\logs"
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss" 2^>nul') do set "TS=%%i"
if "%TS%"=="" set "TS=deep"
set "LOG=%ROOT%data\logs\instalacja_deep_%TS%.log"
echo [PepeMarketWizard] Instalacja .venv_deep - log: "%LOG%"
set "PYEXE="
if exist "%ROOT%runtime\python\python.exe" "%ROOT%runtime\python\python.exe" "%ROOT%tools\check_python.py" >> "%LOG%" 2>&1 && set "PYEXE=%ROOT%runtime\python\python.exe"
for %%V in (3.13 3.12) do (
  if not defined PYEXE (
    py -%%V -c "import sys" >nul 2>&1 && for /f "delims=" %%P in ('py -%%V -c "import sys;print(sys.executable)"') do set "PYEXE=%%P"
  )
)
if not defined PYEXE (
  echo [BLAD] Brak Python 3.13/3.12 x64 ^(py launcher^) i brak sprawnego runtime\python z paczki.
  %MQ_PAUSE%
  exit /b 1
)
"%PYEXE%" "%ROOT%tools\deep_setup.py" --root "%ROOT%." --python "%PYEXE%" --log "%LOG%"
if errorlevel 1 (
  echo [BLAD] Instalacja .venv_deep nie powiodla sie - szczegoly: "%LOG%"
  %MQ_PAUSE%
  exit /b 2
)
echo [OK] .venv_deep gotowe. Centrum treningu ^> Rodziny modeli: LSTM / GRU / PPO maja status "dostepny".
%MQ_PAUSE%
exit /b 0
