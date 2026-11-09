@echo off
setlocal EnableExtensions EnableDelayedExpansion
set "MQ_PAUSE=pause"
if defined MQ_NO_PAUSE set "MQ_PAUSE=type nul"
rem PepeMarketWizard - instalacja modelu Kronos (NeoQuasar/Kronos-base + Kronos-Tokenizer-base; od 1.37 najwiekszy publiczny Kronos, przetrenowane wagi).
rem Tworzy izolowane .venv_kronos (PyTorch CPU z PyPI, pakiety tylko z sumami SHA-256), pobiera oficjalne wagi w przypietych
rem rewizjach, sprawdza sumy ze zrodlem i wykonuje krotka prognoze testowa. Glowne .venv bota NIE jest zmieniane.
rem Uzycie:  33_KRONOS_INSTALUJ.bat            (CPU)
rem          33_KRONOS_INSTALUJ.bat cu126      (GPU NVIDIA: PyTorch z indeksu download.pytorch.org dla CUDA 12.6)
cd /d "%~dp0"
set "ROOT=%~dp0"
if not exist "%ROOT%data\logs" mkdir "%ROOT%data\logs"
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss" 2^>nul') do set "TS=%%i"
if "%TS%"=="" set "TS=kronos"
set "LOG=%ROOT%data\logs\instalacja_kronos_%TS%.log"
echo [PepeMarketWizard] Instalacja Kronos - log: "%LOG%"
set "PYEXE="
if exist "%ROOT%runtime\python\python.exe" "%ROOT%runtime\python\python.exe" "%ROOT%tools\check_python.py" >> "%LOG%" 2>&1 && set "PYEXE=%ROOT%runtime\python\python.exe"
for %%V in (3.13 3.12) do (
  if not defined PYEXE (
    py -%%V -c "import sys" >nul 2>&1 && for /f "delims=" %%P in ('py -%%V -c "import sys;print(sys.executable)"') do set "PYEXE=%%P"
  )
)
if not defined PYEXE (
  echo [BLAD] Brak Python 3.13/3.12 x64 ^(py launcher^) i brak sprawnego runtime\python z paczki. Zainstaluj Python 3.13 x64
  echo        z python.org i uruchom ponownie.
  %MQ_PAUSE%
  exit /b 1
)
set "CUDA_ARG="
if /i "%~1"=="cu126" set "CUDA_ARG=--cuda cu126"
if /i "%~1"=="cu128" set "CUDA_ARG=--cuda cu128"
echo [..] Trwa instalacja ^(PyTorch ok. 250 MB + wagi ok. 420 MB^). Postep ponizej i w logu.
"%PYEXE%" "%ROOT%tools\kronos_setup.py" --root "%ROOT%." --weights-dir auto --python "%PYEXE%" --log "%LOG%" %CUDA_ARG%
if errorlevel 1 (
  echo [BLAD] Instalacja Kronos nie powiodla sie - szczegoly: "%LOG%"
  echo        Najczestsze przyczyny: brak internetu, zapora/proxy blokuje huggingface.co lub pypi.org, za malo miejsca na dysku.
  %MQ_PAUSE%
  exit /b 2
)
echo [OK] Kronos zainstalowany. Uruchom bota - panel "Wykresy bota" ^> "Kronos AI Forecast" pokaze status i prognozy ^(SHADOW^).
%MQ_PAUSE%
exit /b 0
