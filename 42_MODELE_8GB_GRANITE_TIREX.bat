@echo off
setlocal EnableExtensions EnableDelayedExpansion
rem 1.40.3: Python w trybie UTF-8 - polskie znaki i symbole w logach nie przerywaja skryptu (UnicodeEncodeError przy cp1250)
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "MQ_PAUSE=pause"
if defined MQ_NO_PAUSE set "MQ_PAUSE=type nul"
rem PepeMarketWizard 1.42.1 - zestaw modeli dla komputera z 8 GB RAM: IBM Granite TTM (lekki, ok. 0,35 GB RAM) + TiRex-2 (ok. 1 GB RAM).
rem Kronos i Chronos-2 NIE sa instalowane. Po instalacji (gdy bot nie dziala) ustawiany jest profil pamieci LOW_MEMORY_8GB:
rem tylko Granite TTM + jeden ciezki model naraz (TiRex-2 albo TabICLv2), zwalnianie po 90 s bezczynnosci, 2 watki CPU.
rem Gdy bot dziala - wybierz profil w panelu Diagnostyka ^> Zasoby. Kazdy model: wlasne srodowisko, wagi z sumami SHA-256, test
rem ladowania, prognoza testowa i zgodnosc z oficjalnym API. Ponowne uruchomienie nie pobiera zgodnych plikow ponownie.
cd /d "%~dp0"
set "ROOT=%~dp0"
if not exist "%ROOT%data\logs" mkdir "%ROOT%data\logs"
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss" 2^>nul') do set "TS=%%i"
if "%TS%"=="" set "TS=tsfm"
set "LOG=%ROOT%data\logs\instalacja_8gb_%TS%.log"
echo [PepeMarketWizard] Instalacja 8 GB: Granite TTM + TiRex-2 - log: "%LOG%"
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
set "MODEL=low8gb"
echo [..] Trwa instalacja ^(PyTorch ok. 125-250 MB na srodowisko, wagi: Granite TTM ok. 3 MB, TiRex-2 ok. 0,33 GB^). Postep ponizej i w logu.
"%PYEXE%" "%ROOT%tools\tsfm_setup.py" --model %MODEL% --root "%ROOT%." --weights-root auto --python "%PYEXE%" --log "%LOG%"
if errorlevel 1 (
  echo [BLAD] Instalacja nie powiodla sie - szczegoly: "%LOG%"
  echo        Najczestsze przyczyny: brak internetu, zapora/proxy blokuje huggingface.co lub pypi.org, za malo miejsca na dysku,
  echo        blokada Smart App Control. Model, ktory sie nie zainstalowal, pozostaje NOT_INSTALLED - bot dziala dalej bez niego.
  %MQ_PAUSE%
  exit /b 2
)
echo [OK] Zainstalowano Granite TTM + TiRex-2. Profil pamieci: patrz linia [8GB] powyzej ^(Diagnostyka ^> Zasoby: LOW_MEMORY_8GB^).
%MQ_PAUSE%
exit /b 0
