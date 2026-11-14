@echo off
setlocal EnableExtensions EnableDelayedExpansion
rem 1.40.3: Python w trybie UTF-8 - polskie znaki i symbole w logach nie przerywaja skryptu (UnicodeEncodeError przy cp1250)
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "MQ_PAUSE=pause"
if defined MQ_NO_PAUSE set "MQ_PAUSE=type nul"
rem PepeMarketWizard 1.40 - instalacja modeli Chronos-2 (amazon/chronos-2, 120M) i IBM Granite TTM R2 (ok. 0,8M, lekki, CPU).
rem FinCast zostal wycofany w 1.40 (zastapiony przez Granite TTM) - nie jest juz instalowany.
rem Kazdy model dostaje wlasne izolowane srodowisko (.venv_chronos2, .venv_granite; PyTorch CPU z PyPI, pakiety tylko z sumami
rem SHA-256), oficjalne wagi w przypietych rewizjach (rozmiar + SHA-256 kazdego pliku), test ladowania, prognoza testowa i
rem zgodnosc adaptera z oficjalnym API. Glowne .venv bota i .venv_kronos NIE sa zmieniane.
rem Uzycie:  38_MODELE_CHRONOS2_GRANITE.bat                    (oba modele, CPU)
rem          38_MODELE_CHRONOS2_GRANITE.bat chronos2           (tylko Chronos-2)
rem          38_MODELE_CHRONOS2_GRANITE.bat granite            (tylko Granite TTM - ok. 3 MB wag, ok. 0,35 GB RAM)
rem          38_MODELE_CHRONOS2_GRANITE.bat all cu126          (GPU NVIDIA: PyTorch dla CUDA 12.6; cu128 dla CUDA 12.8)
rem Instalacja offline: 38_MODELE_CHRONOS2_GRANITE.bat all "" D:\wagi   (katalog z wczesniej pobranymi plikami wag)
cd /d "%~dp0"
set "ROOT=%~dp0"
if not exist "%ROOT%data\logs" mkdir "%ROOT%data\logs"
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss" 2^>nul') do set "TS=%%i"
if "%TS%"=="" set "TS=tsfm"
set "LOG=%ROOT%data\logs\instalacja_chronos2_granite_%TS%.log"
echo [PepeMarketWizard] Instalacja Chronos-2 / Granite TTM - log: "%LOG%"
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
set "MODEL=all"
if /i "%~1"=="chronos2" set "MODEL=chronos2"
if /i "%~1"=="granite" set "MODEL=granite_ttm"
if /i "%~1"=="granite_ttm" set "MODEL=granite_ttm"
set "CUDA_ARG="
if /i "%~2"=="cu126" set "CUDA_ARG=--cuda cu126"
if /i "%~2"=="cu128" set "CUDA_ARG=--cuda cu128"
set "FROM_ARG="
if not "%~3"=="" set "FROM_ARG=--from-dir "%~3""
echo [..] Trwa instalacja ^(PyTorch ok. 250 MB na model, wagi: Chronos-2 ok. 0,5 GB, Granite TTM ok. 3 MB^). Postep ponizej i w logu.
"%PYEXE%" "%ROOT%tools\tsfm_setup.py" --model %MODEL% --root "%ROOT%." --weights-root auto --python "%PYEXE%" --log "%LOG%" %CUDA_ARG% %FROM_ARG%
if errorlevel 1 (
  echo [BLAD] Instalacja nie powiodla sie - szczegoly: "%LOG%"
  echo        Najczestsze przyczyny: brak internetu, zapora/proxy blokuje huggingface.co lub pypi.org, za malo miejsca na dysku,
  echo        za malo RAM. Model, ktory sie nie zainstalowal, pozostaje NOT_INSTALLED - bot dziala dalej bez niego.
  %MQ_PAUSE%
  exit /b 2
)
echo [OK] Zainstalowano. Uruchom bota - panel "Wykresy bota" ^> "Modele prognoz" pokaze status, prognozy i porownanie ^(rola OBSERVE^).
%MQ_PAUSE%
exit /b 0
