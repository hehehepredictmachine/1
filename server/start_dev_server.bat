@echo off
setlocal
rem TYLKO LOKALNY ROZWOJ/TEST: http://127.0.0.1:8790, klucze deweloperskie w server\data\dev (nie do produkcji).
rem Pierwszy administrator (raz): "%~dp0..\.venv-server\Scripts\python.exe" -m mqlicense --env-file data\dev\dev.env bootstrap-admin --email TWOJ@EMAIL
cd /d "%~dp0"
set "PY=%~dp0..\.venv-server\Scripts\python.exe"
if not exist "%PY%" (
  echo [BLAD] Brak .venv-server - patrz INSTRUKCJA_WINDOWS_PL.md, rozdzial "Serwer licencji".
  pause
  exit /b 1
)
if not exist "data\dev\dev.env" (
  "%PY%" -m mqlicense gen-keys --out data\dev || exit /b 1
  copy /y "data\dev\secrets.env" "data\dev\dev.env" >nul
  >>"data\dev\dev.env" echo MQL_ENV=dev
  >>"data\dev\dev.env" echo MQL_DB_PATH=data\dev\mqlicense.sqlite3
)
"%PY%" -m mqlicense --env-file data\dev\dev.env migrate
echo Panel: http://127.0.0.1:8790/admin/
"%PY%" -m mqlicense --env-file data\dev\dev.env serve
