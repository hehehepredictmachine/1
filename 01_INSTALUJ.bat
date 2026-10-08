@echo off
setlocal EnableExtensions EnableDelayedExpansion
rem MasterQUO AI - instalacja (Windows 10/11 x64). Nie zmienia globalnego Pythona ani zabezpieczen Windows.
cd /d "%~dp0"
set "ROOT=%~dp0"
if not exist "%ROOT%data\logs" mkdir "%ROOT%data\logs"
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss" 2^>nul') do set "TS=%%i"
if "%TS%"=="" set "TS=install"
set "LOG=%ROOT%data\logs\instalacja_%TS%.log"
echo [MasterQUO] Instalacja - log: "%LOG%"
echo MasterQUO AI install %DATE% %TIME% > "%LOG%"

rem ---- 1. wybor sprawnego interpretera: preferowany Python 3.13 x64, potem 3.12 (bez automatycznego najnowszego)
set "PYEXE="
for %%V in (3.13 3.12) do (
  if not defined PYEXE (
    py -%%V -c "import sys" >nul 2>&1 && (
      py -%%V "%ROOT%tools\check_python.py" >> "%LOG%" 2>&1
      if !errorlevel! EQU 0 (
        for /f "delims=" %%P in ('py -%%V -c "import sys;print(sys.executable)"') do set "PYEXE=%%P"
      ) else (
        echo [UWAGA] Python %%V nie przeszedl kontroli - szczegoly w logu.
      )
    )
  )
)
if not defined PYEXE (
  where python >nul 2>&1 && (
    python "%ROOT%tools\check_python.py" >> "%LOG%" 2>&1 && for /f "delims=" %%P in ('python -c "import sys;print(sys.executable)"') do set "PYEXE=%%P"
  )
)
if not defined PYEXE (
  echo.
  echo [BLAD] Nie znaleziono sprawnego Python 3.13 lub 3.12 w wersji 64-bit.
  echo        Zainstaluj Python 3.13 x64 z https://www.python.org/downloads/windows/
  echo        ^(zaznacz "py launcher"^). Nie usuwaj innych wersji Pythona.
  echo        Szczegoly kontroli: "%LOG%"
  type "%LOG%"
  pause
  exit /b 1
)
echo [OK] Interpreter: "%PYEXE%"
echo Interpreter: %PYEXE% >> "%LOG%"

rem ---- 2. izolowane srodowisko .venv (stare, uszkodzone zostaje zachowane pod inna nazwa)
if exist "%ROOT%.venv\Scripts\python.exe" (
  "%ROOT%.venv\Scripts\python.exe" "%ROOT%tools\check_python.py" >> "%LOG%" 2>&1
  if errorlevel 1 (
    echo [INFO] Istniejace .venv jest niesprawne - zmieniam nazwe na .venv_old_%TS%
    ren "%ROOT%.venv" ".venv_old_%TS%"
  ) else (
    echo [OK] Uzywam istniejacego .venv
  )
) else if exist "%ROOT%.venv" (
  echo [INFO] Niekompletne .venv - zmieniam nazwe na .venv_old_%TS%
  ren "%ROOT%.venv" ".venv_old_%TS%"
)
if not exist "%ROOT%.venv\Scripts\python.exe" (
  echo [..] Tworze .venv
  "%PYEXE%" -m venv "%ROOT%.venv" >> "%LOG%" 2>&1
  if errorlevel 1 (
    echo [BLAD] Nie udalo sie utworzyc .venv - patrz log. Typowa przyczyna: uszkodzona instalacja Pythona
    echo        ^(brak venvlauncher.exe^). Zainstaluj ponownie Python 3.13 x64.
    pause
    exit /b 2
  )
)
set "VPY=%ROOT%.venv\Scripts\python.exe"

rem ---- 3. zaleznosci przypiete z hashami, tylko gotowe pakiety (bez kompilacji), wylacznie do .venv
echo [..] Instaluje zaleznosci (wymaga internetu, kilka minut)
"%VPY%" -m pip install --disable-pip-version-check --no-input --require-hashes --only-binary=:all: -r "%ROOT%requirements\requirements-win.txt" >> "%LOG%" 2>&1
if errorlevel 1 (
  echo [BLAD] Instalacja pakietow nie powiodla sie - szczegoly: "%LOG%"
  pause
  exit /b 3
)
"%VPY%" -c "import fastapi, uvicorn, pydantic, anthropic, numpy, websockets, MetaTrader5; print('IMPORT_OK')" >> "%LOG%" 2>&1
if errorlevel 1 (
  echo [BLAD] Kontrola importow nie powiodla sie - szczegoly: "%LOG%"
  pause
  exit /b 4
)
echo [OK] IMPORT_OK
if not exist "%ROOT%frontend\dist\index.html" (
  echo [BLAD] Brak zbudowanego monitora frontend\dist - rozpakuj ponownie caly ZIP.
  pause
  exit /b 5
)

rem ---- 4. baza danych i konfiguracja (migracje z kopia zapasowa)
pushd "%ROOT%backend"
"%VPY%" -c "from masterquo.config import ConfigStore; from masterquo.db.database import Database; ConfigStore(); print('DB', Database().schema_versions())" >> "%LOG%" 2>&1
popd
echo.
echo [GOTOWE] Instalacja zakonczona.
echo   Dalej: 02_DIAGNOSTYKA.bat (przy uruchomionym i zalogowanym MT5), potem 03_START_MASTERQUO.bat
echo   Klucz Claude wpiszesz w monitorze (Ustawienia - Agent Claude); nie wklejaj go do rozmow ani plikow.
pause
exit /b 0
