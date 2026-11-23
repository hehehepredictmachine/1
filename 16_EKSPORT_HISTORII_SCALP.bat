@echo off
setlocal
rem 1.40.3: Python w trybie UTF-8 - polskie znaki i symbole w logach nie przerywaja skryptu (UnicodeEncodeError przy cp1250)
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
rem Eksport zamknietych M1/M5/M15/M30/H1 XAUUSD- z TWOJEGO zalogowanego MT5 do profilu scalp (osobne polaczenie; bez zlecen).
rem Domyslnie 6 miesiecy (argument = liczba miesiecy, np. 16_EKSPORT_HISTORII_SCALP.bat 12). Wynik: data\scalp\history\^<cutoff^>\
cd /d "%~dp0"
for %%I in ("%~dp0.") do set "ROOT=%%~fI"
call "%ROOT%\tools\pmwpy.cmd"
if not exist "%PY%" (echo [BLAD] Brak Pythona bota (.venv albo runtime aplikacji) - uruchom INSTALUJ_TRENING.bat albo raz aplikacje Apollo23 - PepeMarketWizard.exe & pause & exit /b 2)
set "MONTHS=%~1"
if "%MONTHS%"=="" set "MONTHS=6"
pushd "%~dp0backend"
"%PY%" -m masterquo export-scalp --months %MONTHS%
set "RC=%ERRORLEVEL%"
popd
echo Wynik: %RC% - CSV per interwal, source_metadata.json, DATA_QUALITY_REPORT.json ^(dane faktycznie otrzymane, nie zadane^)
pause
exit /b %RC%
