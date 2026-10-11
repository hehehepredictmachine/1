@echo off
setlocal
rem MasterQUO License Server - instalacja srodowiska Python (Windows x64). Tworzy ..\.venv-server, niczego nie zmienia globalnie.
cd /d "%~dp0"
set "VENV=%~dp0..\.venv-server"
set "PYV="
py -3.13 -c "import sys" >/dev/null 2>&1 && set "PYV=-3.13"
if not defined PYV py -3.12 -c "import sys" >/dev/null 2>&1 && set "PYV=-3.12"
if not defined PYV (
  echo [BLAD] Brak Python 3.13/3.12 x64 ^(py launcher^). Zainstaluj z python.org.
  pause
  exit /b 1
)
if not exist "%VENV%\Scripts\python.exe" py %PYV% -m venv "%VENV%" || exit /b 1
"%VENV%\Scripts\python.exe" -m pip install --require-hashes --only-binary=:all: -r "%~dp0requirements-server.txt"
if errorlevel 1 (
  echo [BLAD] Instalacja pakietow nie powiodla sie.
  pause
  exit /b 1
)
echo [OK] Srodowisko serwera: "%VENV%"
echo      Test lokalny: start_dev_server.bat   Produkcja: README_SERWER_PL.md
pause
