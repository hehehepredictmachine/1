@echo off
setlocal EnableDelayedExpansion
rem MasterQUO License Server - instalacja srodowiska Python (Windows x64). Tworzy ..\.venv-server, niczego nie zmienia globalnie.
cd /d "%~dp0"
set "VENV=%~dp0..\.venv-server"
set "PYEXE="
rem 1) py launcher: 3.13, potem 3.12 (bledy launchera ukryte)
for %%V in (3.13 3.12) do (
  if not defined PYEXE (
    for /f "delims=" %%P in (py -%%V -c "import sys,struct;print(sys.executable if struct.calcsize(\"P\")==8 else \"\")" 2^>nul) do if not "%%P"=="" set "PYEXE=%%P"
  )
)
rem 2) python z PATH, jesli to 3.13/3.12 x64
if not defined PYEXE (
  for /f "delims=" %%P in (python -c "import sys,struct;print(sys.executable if sys.version_info[:2] in ((3,13),(3,12)) and struct.calcsize(\"P\")==8 else \"\")" 2^>nul) do if not "%%P"=="" set "PYEXE=%%P"
)
rem 3) typowe katalogi instalacji python.org
if not defined PYEXE for %%D in ("%LOCALAPPDATA%\Programs\Python\Python313" "%LOCALAPPDATA%\Programs\Python\Python312" "%ProgramFiles%\Python313" "%ProgramFiles%\Python312") do (
  if not defined PYEXE if exist "%%~D\python.exe" set "PYEXE=%%~D\python.exe"
)
if not defined PYEXE (
  echo [BLAD] Nie znaleziono Python 3.13 ani 3.12 w wersji 64-bit.
  echo        Znalezione wersje ^(py --list^):
  py --list 2>/dev/null ^|^| echo        - brak py launchera
  echo        Zainstaluj Python 3.13 x64: https://www.python.org/downloads/windows/
  echo        ^(instalator "Windows installer 64-bit", zaznacz "Add python.exe to PATH" i "py launcher"^),
  echo        potem uruchom ten plik ponownie. Python 3.14 nie jest jeszcze obslugiwany ^(brak przypietych pakietow^).
  pause
  exit /b 1
)
echo [MasterQUO] Python: "%PYEXE%"
if not exist "%VENV%\Scripts\python.exe" "%PYEXE%" -m venv "%VENV%" || (echo [BLAD] Nie udalo sie utworzyc "%VENV%" & pause & exit /b 1)
"%VENV%\Scripts\python.exe" -m pip install --require-hashes --only-binary=:all: -r "%~dp0requirements-server.txt"
if errorlevel 1 (
  echo [BLAD] Instalacja pakietow nie powiodla sie.
  pause
  exit /b 1
)
echo [OK] Srodowisko serwera: "%VENV%"
echo      Test lokalny: start_dev_server.bat   Produkcja: README_SERWER_PL.md
pause
