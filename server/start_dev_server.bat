@echo off
setlocal
rem TYLKO LOKALNY ROZWOJ/TEST: http://127.0.0.1:8790, klucze deweloperskie w server\data\dev (nie do produkcji).
rem Folder serwera = ten, w ktorym jest pakiet mqlicense (dziala z MasterQUO_SERWER_LICENCJI\ albo z jego podfolderu server\)
set "SRV="
if exist "%~dp0mqlicense\__init__.py" set "SRV=%~dp0"
if not defined SRV if exist "%~dp0server\mqlicense\__init__.py" set "SRV=%~dp0server\"
if not defined SRV (
  echo [BLAD] Nie znaleziono folderu serwera ^(mqlicense^) obok tego pliku ani w podfolderze server\.
  echo        Rozpakuj CALA paczke MasterQUO_SERWER_LICENCJI_*.zip i uruchom plik z folderu server\.
  pause
  exit /b 1
)
cd /d "%SRV%"
set "VENV=%SRV%..\.venv-server"
set "PY=%VENV%\Scripts\python.exe"
if not exist "%PY%" (
  echo [BLAD] Brak .venv-server - uruchom najpierw INSTALUJ_SERWER.bat
  pause
  exit /b 1
)
if not exist "data\dev\dev.env" (
  "%PY%" -m mqlicense gen-keys --out data\dev || (pause & exit /b 1)
  copy /y "data\dev\secrets.env" "data\dev\dev.env" >nul
  >>"data\dev\dev.env" echo MQL_ENV=dev
  >>"data\dev\dev.env" echo MQL_DB_PATH=data\dev\mqlicense.sqlite3
)
"%PY%" -m mqlicense --env-file data\dev\dev.env migrate
echo.
echo Serwer licencji dziala: http://127.0.0.1:8790/admin/   ZOSTAW TO OKNO OTWARTE.
echo Pierwszy administrator: UTWORZ_ADMINA.bat (w drugim oknie).
"%PY%" -m mqlicense --env-file data\dev\dev.env serve
pause
