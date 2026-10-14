@echo off
setlocal
rem Eksport zamknietych M5/M30 XAUUSD- z TWOJEGO zalogowanego MT5 (wlasne, osobne polaczenie tego polecenia; bez zlecen).
rem Domyslnie 12 miesiecy (mozna podac liczbe miesiecy jako argument, np. 11_EKSPORT_HISTORII_XAUUSD.bat 6).
cd /d "%~dp0"
if not exist "%~dp0.venv\Scripts\python.exe" (echo [BLAD] Brak .venv - uruchom 01_INSTALUJ.bat & pause & exit /b 1)
set "MONTHS=%~1"
if "%MONTHS%"=="" set "MONTHS=12"
if not exist "%~dp0data\logs" mkdir "%~dp0data\logs"
pushd "%~dp0backend"
"%~dp0.venv\Scripts\python.exe" -m masterquo export-candles --months %MONTHS%
set "RC=%ERRORLEVEL%"
popd
echo Wynik: %RC% - dane w data\forecast\history\^<cutoff^>\ ^(CSV, source_metadata.json, DATA_QUALITY_REPORT.json^)
pause
exit /b %RC%
