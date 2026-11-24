@echo off
setlocal EnableExtensions EnableDelayedExpansion
rem 1.40.3: Python w trybie UTF-8 - polskie znaki i symbole w logach nie przerywaja skryptu (UnicodeEncodeError przy cp1250)
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "MQ_PAUSE=pause"
if defined MQ_NO_PAUSE set "MQ_PAUSE=type nul"
rem PepeMarketWizard 1.41 - instalacja modeli AI tej aktualizacji: TiRex-2 (NX-AI/TiRex-2, prognozy szeregu, Apache-2.0) oraz
rem TabICLv2 Classifier (jingang/TabICL v2, ocena zdarzenia setupu / confidence, BSD-3-Clause).
rem Kazdy model: wlasne srodowisko (.venv_tirex2, .venv_tabicl; PyTorch CPU 2.14.1 z PyPI, pakiety tylko z sumami SHA-256), oficjalne
rem wagi w przypietych rewizjach (rozmiar + SHA-256), test ladowania, wynik testowy i zgodnosc z oficjalnym API. Ponowne uruchomienie
rem nie pobiera zgodnych plikow ponownie. Bot dziala dalej w czasie instalacji; modele startuja same po jej zakonczeniu.
rem Uzycie:  41_AI_TABICL_TIREX_INSTALUJ.bat            (oba modele)
rem          41_AI_TABICL_TIREX_INSTALUJ.bat tirex2     (tylko TiRex-2)
rem          41_AI_TABICL_TIREX_INSTALUJ.bat tabicl     (tylko TabICLv2)
cd /d "%~dp0"
set "ROOT=%~dp0"
if not exist "%ROOT%data\logs" mkdir "%ROOT%data\logs"
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss" 2^>nul') do set "TS=%%i"
if "%TS%"=="" set "TS=tsfm"
set "LOG=%ROOT%data\logs\instalacja_ai141_%TS%.log"
echo [Apollo23] Instalacja TiRex-2 + TabICLv2 - log: "%LOG%"
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
set "MODEL=ai141"
if /i "%~1"=="tirex2" set "MODEL=tirex2"
if /i "%~1"=="tabicl" set "MODEL=tabicl"
echo [..] Trwa instalacja ^(PyTorch ok. 125 MB na srodowisko, wagi: TiRex-2 ok. 0,33 GB, TabICLv2 ok. 0,11 GB^). Postep ponizej i w logu.
"%PYEXE%" "%ROOT%tools\tsfm_setup.py" --model %MODEL% --root "%ROOT%." --weights-root auto --python "%PYEXE%" --log "%LOG%"
if errorlevel 1 (
  echo [BLAD] Instalacja nie powiodla sie - szczegoly: "%LOG%"
  echo        Najczestsze przyczyny: brak internetu, zapora/proxy blokuje huggingface.co lub pypi.org, za malo miejsca na dysku,
  echo        blokada Smart App Control. Model, ktory sie nie zainstalowal, pozostaje NOT_INSTALLED - bot dziala dalej bez niego.
  %MQ_PAUSE%
  exit /b 2
)
echo [OK] Zainstalowano. Uruchom bota - TiRex-2 liczy prognozy po kazdej zamknietej swiecy M5/M15, TabICLv2 ocenia setupy (confidence surowe).
%MQ_PAUSE%
exit /b 0
