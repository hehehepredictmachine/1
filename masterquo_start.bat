@echo off
setlocal
cd /d "%~dp0"
if not exist "%~dp0.venv\Scripts\python.exe" (
  echo [BLAD] Brak .venv - uruchom najpierw 01_INSTALUJ.bat
  pause
  exit /b 1
)
rem masterquo_start: przy KAZDYM uruchomieniu program prosi o wklejenie licencji (MQL72-...).
rem Klucz nie jest zapisywany (brak "zapamietaj"), nie trafia do parametrow, plikow ani logow.
rem Opcja: masterquo_start.bat --demo  = DANE SYNTETYCZNE (licencja tez wymagana).
title MasterQUO server
cd /d "%~dp0backend"
"%~dp0.venv\Scripts\python.exe" -m masterquo serve %*
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
  echo [MasterQUO] Program zakonczyl sie kodem %RC% ^(5 = licencja nie zostala przyjeta^).
  pause
)
exit /b %RC%
