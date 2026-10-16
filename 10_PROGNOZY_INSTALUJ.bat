@echo off
setlocal EnableExtensions EnableDelayedExpansion
rem PepeMarketWizard - izolowane srodowisko .venv_candles dla modulu prognoz gold_candles (numpy/pandas/scikit-learn przypiete
rem przez modul referencyjny). Glowne .venv bota NIE jest zmieniane. Bez kompilacji, tylko pakiety z hashami.
cd /d "%~dp0"
set "ROOT=%~dp0"
if not exist "%ROOT%data\logs" mkdir "%ROOT%data\logs"
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss" 2^>nul') do set "TS=%%i"
if "%TS%"=="" set "TS=candles"
set "LOG=%ROOT%data\logs\instalacja_prognoz_%TS%.log"
echo [PepeMarketWizard] Srodowisko prognoz - log: "%LOG%"
set "PYEXE="
for %%V in (3.13 3.12) do (
  if not defined PYEXE (
    py -%%V -c "import sys" >nul 2>&1 && for /f "delims=" %%P in ('py -%%V -c "import sys;print(sys.executable)"') do set "PYEXE=%%P"
  )
)
if not defined PYEXE (
  echo [BLAD] Brak Python 3.13/3.12 x64 ^(py launcher^). Zainstaluj z python.org i uruchom ponownie.
  pause
  exit /b 1
)
if not exist "%ROOT%.venv_candles\Scripts\python.exe" (
  echo [..] Tworze .venv_candles
  "%PYEXE%" -m venv "%ROOT%.venv_candles" >> "%LOG%" 2>&1 || (echo [BLAD] venv - patrz log & pause & exit /b 2)
)
set "CPY=%ROOT%.venv_candles\Scripts\python.exe"
echo [..] Instaluje numpy/pandas/scikit-learn ^(przypiete wersje z hashami^)
"%CPY%" -m pip install --disable-pip-version-check --no-input --require-hashes --only-binary=:all: -r "%ROOT%requirements\requirements-candles-win.txt" >> "%LOG%" 2>&1
if errorlevel 1 (
  echo [BLAD] Instalacja pakietow nie powiodla sie - szczegoly: "%LOG%"
  pause
  exit /b 3
)
echo [..] Testy modulu i integracji ^(dane SYNTETYCZNE - test programu, nie rynku^)
set "PYTHONPATH=%ROOT%backend"
pushd "%ROOT%tests\gold_candles"
"%CPY%" -m unittest discover -s . -p "test_*.py" >> "%LOG%" 2>&1
set "RC=%ERRORLEVEL%"
popd
if not "%RC%"=="0" (
  echo [BLAD] Testy modulu prognoz nie przeszly - szczegoly: "%LOG%"
  pause
  exit /b 4
)
echo [OK] .venv_candles gotowe. Monitor uruchomi analityke SHADOW automatycznie ^(strona Wykresy bota^).
echo      Dalej: 11_EKSPORT_HISTORII_XAUUSD.bat, potem 12_TRENING_MODELI_XAUUSD.bat
pause
exit /b 0
