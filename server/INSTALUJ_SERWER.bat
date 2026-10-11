@echo off
setlocal EnableDelayedExpansion
rem MasterQUO License Server - instalacja srodowiska Python (Windows x64). Tworzy .venv-server obok folderu server, niczego nie zmienia globalnie.
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
set "PYEXE="
for %%V in (3.13 3.12) do (
  if not defined PYEXE (
    for /f "delims=" %%P in ('py -%%V -c "import sys,struct;print(sys.executable if struct.calcsize(\"P\")==8 else \"\")" 2^>nul') do if not "%%P"=="" set "PYEXE=%%P"
  )
)
if not defined PYEXE (
  for /f "delims=" %%P in ('python -c "import sys,struct;print(sys.executable if sys.version_info[:2] in ((3,13),(3,12)) and struct.calcsize(\"P\")==8 else \"\")" 2^>nul') do if not "%%P"=="" set "PYEXE=%%P"
)
if not defined PYEXE for %%D in ("%LOCALAPPDATA%\Programs\Python\Python313" "%LOCALAPPDATA%\Programs\Python\Python312" "%ProgramFiles%\Python313" "%ProgramFiles%\Python312") do (
  if not defined PYEXE if exist "%%~D\python.exe" set "PYEXE=%%~D\python.exe"
)
if not defined PYEXE (
  echo [BLAD] Nie znaleziono Python 3.13 ani 3.12 w wersji 64-bit.
  echo        Zainstaluj: winget install -e --id Python.Python.3.13 --scope user
  pause
  exit /b 1
)
echo [MasterQUO] Python: "%PYEXE%"
echo [MasterQUO] Folder serwera: "%SRV%"
if not exist "%PY%" "%PYEXE%" -m venv "%VENV%" || (echo [BLAD] Nie udalo sie utworzyc "%VENV%" & pause & exit /b 1)
"%PY%" -m pip install --require-hashes --only-binary=:all: -r "%SRV%requirements-server.txt"
if errorlevel 1 (
  echo [BLAD] Instalacja pakietow nie powiodla sie.
  pause
  exit /b 1
)
echo [OK] Srodowisko serwera: "%VENV%"
echo      Nastepnie: start_dev_server.bat ^(zostaw okno otwarte^), potem UTWORZ_ADMINA.bat
pause
