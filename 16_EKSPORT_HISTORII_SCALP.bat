@echo off
setlocal
rem Eksport zamknietych M1/M5/M15/M30/H1 XAUUSD- z TWOJEGO zalogowanego MT5 do profilu scalp (osobne polaczenie; bez zlecen).
rem Domyslnie 6 miesiecy (argument = liczba miesiecy, np. 16_EKSPORT_HISTORII_SCALP.bat 12). Wynik: data\scalp\history\^<cutoff^>\
cd /d "%~dp0"
if not exist "%~dp0.venv\Scripts\python.exe" (echo [BLAD] Brak .venv - uruchom 01_INSTALUJ.bat & pause & exit /b 1)
set "MONTHS=%~1"
if "%MONTHS%"=="" set "MONTHS=6"
pushd "%~dp0backend"
"%~dp0.venv\Scripts\python.exe" -m masterquo export-scalp --months %MONTHS%
set "RC=%ERRORLEVEL%"
popd
echo Wynik: %RC% - CSV per interwal, source_metadata.json, DATA_QUALITY_REPORT.json ^(dane faktycznie otrzymane, nie zadane^)
pause
exit /b %RC%
