@echo off
rem PepeMarketWizard - instalacja / naprawa srodowiska treningu. Nie nadpisuje sprawnego srodowiska; uzywa istniejacych
rem instalatorow (01_INSTALUJ.bat: .venv, 10_PROGNOZY_INSTALUJ.bat: .venv_candles) - Python 3.13/3.12 x64, pakiety z hashami, CPU.
setlocal
title PepeMarketWizard - instalacja treningu
set "MQ_NO_PAUSE=1"
rem ---- 0. kompletnosc rozpakowania (brak plikow to nie problem z Pythonem)
set "MQ_MISSING="
for %%F in ("tools\check_python.py" "tools\trening.cmd" "backend\masterquo\__main__.py" "backend\mq_instruments.py" "frontend\dist\index.html" "MANIFEST_SHA256.txt") do (
  if not exist "%~dp0%%~F" set "MQ_MISSING=%%~F"
)
if defined MQ_MISSING (
  echo [BLAD] Niekompletny folder programu - brak pliku: %MQ_MISSING%
  echo        Folder: "%~dp0"
  echo        Rozpakuj CALY plik ZIP: prawy klik - Wyodrebnij wszystkie - do NOWEGO, pustego folderu,
  echo        potem uruchom instalator z tego folderu. Nie uruchamiaj .bat z podgladu ZIP i nie kopiuj pojedynczych plikow.
  echo        Jesli plik znika po rozpakowaniu, sprawdz kwarantanne antywirusa.
  pause
  exit /b 2
)
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
