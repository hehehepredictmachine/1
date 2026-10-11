@echo off
setlocal
cd /d "%~dp0"
if not exist "%~dp0.venv\Scripts\python.exe" (
  echo [BLAD] Brak .venv - uruchom najpierw 01_INSTALUJ.bat
  pause
  exit /b 1
)
rem masterquo_start: uruchamia serwer MasterQUO w tym oknie (monitor: http://127.0.0.1:8765/).
rem Opcja: masterquo_start.bat --demo  = DANE SYNTETYCZNE (symulator, osobna baza).
title MasterQUO server
cd /d "%~dp0backend"
"%~dp0.venv\Scripts\python.exe" -m masterquo serve %*
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
  echo [MasterQUO] Program zakonczyl sie kodem %RC%.
  pause
)
exit /b %RC%
