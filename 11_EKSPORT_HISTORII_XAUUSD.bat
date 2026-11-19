@echo off
setlocal
rem 1.40.3: Python w trybie UTF-8 - polskie znaki i symbole w logach nie przerywaja skryptu (UnicodeEncodeError przy cp1250)
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
rem Eksport zamknietych M5/M30 XAUUSD- z TWOJEGO zalogowanego MT5 (wlasne, osobne polaczenie tego polecenia; bez zlecen).
rem Domyslnie 12 miesiecy (mozna podac liczbe miesiecy jako argument, np. 11_EKSPORT_HISTORII_XAUUSD.bat 6).
cd /d "%~dp0"
for %%I in ("%~dp0.") do set "ROOT=%%~fI"
call "%ROOT%\tools\pmwpy.cmd"
if not exist "%PY%" (echo [BLAD] Brak Pythona bota (.venv albo runtime aplikacji) - uruchom INSTALUJ_TRENING.bat albo raz aplikacje PepeMarketWizard & pause & exit /b 2)
set "MONTHS=%~1"
if "%MONTHS%"=="" set "MONTHS=12"
if not exist "%~dp0data\logs" mkdir "%~dp0data\logs"
pushd "%~dp0backend"
"%PY%" -m masterquo export-candles --months %MONTHS%
set "RC=%ERRORLEVEL%"
popd
echo Wynik: %RC% - dane w data\forecast\history\^<cutoff^>\ ^(CSV, source_metadata.json, DATA_QUALITY_REPORT.json^)
pause
exit /b %RC%
