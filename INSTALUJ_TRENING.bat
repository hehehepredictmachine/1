@echo off
rem PepeMarketWizard - instalacja / naprawa srodowiska treningu. Nie nadpisuje sprawnego srodowiska; uzywa istniejacych
rem instalatorow (01_INSTALUJ.bat: .venv, 10_PROGNOZY_INSTALUJ.bat: .venv_candles) - Python 3.13/3.12 x64, pakiety z hashami, CPU.
setlocal
title PepeMarketWizard - instalacja treningu
set "MQ_NO_PAUSE=1"
if not exist "%~dp0.venv\Scripts\python.exe" (
  echo [..] Brak .venv - uruchamiam 01_INSTALUJ.bat
  call "%~dp001_INSTALUJ.bat"
)
if not exist "%~dp0.venv_candles\Scripts\python.exe" (
  echo [..] Brak .venv_candles - uruchamiam 10_PROGNOZY_INSTALUJ.bat
  call "%~dp010_PROGNOZY_INSTALUJ.bat"
)
call "%~dp0tools\trening.cmd" install
set "RC=%ERRORLEVEL%"
if "%RC%"=="0" (echo [OK] Srodowisko treningu gotowe. Dalej: 00_TRENING_START.bat) else (echo [UWAGA] Sa problemy - opis powyzej i w data\training\install_check.json)
pause
exit /b %RC%
