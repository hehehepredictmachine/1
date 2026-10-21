@echo off
rem PepeMarketWizard - SCALPING / HEDGING (PMW-SH-1): eksport historii, kontrola jakosci, replay obu strategii,
rem model zdarzenia P(TP2 przed SL) i raport walidacji. Bez zlecen, bez zmian Execution Lock. Wyniki: data\sh\validation\.
setlocal EnableDelayedExpansion
chcp 65001 >nul
title PepeMarketWizard - SCALPING / HEDGING walidacja
for %%I in ("%~dp0.") do set "ROOT=%%~fI"
set "PY=%ROOT%\.venv\Scripts\python.exe"
if not exist "%PY%" (echo [BLAD] Brak .venv - uruchom INSTALUJ_TRENING.bat ^& pause ^& exit /b 2)
set "PYTHONIOENCODING=utf-8"
set "ASSET=%~1"
if "%ASSET%"=="" set "ASSET=XAUUSD"
pushd "%ROOT%\backend"
"%PY%" -m masterquo training run --instruments %ASSET% --profile PELNY_TRENING --tasks sh_models
popd
pause
