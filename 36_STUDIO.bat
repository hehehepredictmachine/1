@echo off
setlocal EnableExtensions
rem PepeMarketWizard 1.33 - Pepe Data ^& Training Studio (osobna aplikacja: wlasny proces, port 8780, folder data_studio).
rem Eksport -> walidacja -> dataset -> trening -> test loadera -> przekazanie do bota (kandydat SHADOW). Studio NIE wysyla zlecen.
rem Zalecane: PepeTrainingStudio.exe (okno). Ten skrypt uruchamia ten sam serwer i otwiera przegladarke.
cd /d "%~dp0"
chcp 65001 >nul
set "PY=%~dp0.venv\Scripts\python.exe"
if exist "%~dp0runtime\python\python.exe" if not exist "%PY%" set "PY=%~dp0runtime\python\python.exe"
if not exist "%PY%" (
  echo [BLAD] Brak srodowiska - uruchom najpierw 01_INSTALUJ.bat
  pause
  exit /b 1
)
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
set "MQ_STUDIO_DATA_DIR=%~dp0data_studio"
set "MQ_BOT_DATA_DIR=%~dp0data"
set "MASTERQUO_DATA_DIR=%~dp0data_studio"
pushd "%~dp0backend"
start "" "http://127.0.0.1:8780/"
"%PY%" -m masterquo studio
set "RC=%ERRORLEVEL%"
popd
exit /b %RC%
