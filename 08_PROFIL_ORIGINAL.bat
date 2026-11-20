@echo off
setlocal
rem 1.40.3: Python w trybie UTF-8 - polskie znaki i symbole w logach nie przerywaja skryptu (UnicodeEncodeError przy cp1250)
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"
if not exist "%~dp0.venv\Scripts\python.exe" (
  echo [BLAD] Brak .venv - uruchom najpierw 01_INSTALUJ.bat
  pause
  exit /b 1
)
echo [MasterQUO] Powrot do profilu ORIGINAL (wykrywanie M07 jak w wersji 1.1). Najpierw zatrzymaj program: 04_STOP_MASTERQUO.bat
echo            Ponowne wlaczenie ACTIVE: w monitorze Ustawienia - AUTO / ACTIVE albo: 08_PROFIL_ORIGINAL.bat ACTIVE
pushd "%~dp0backend"
set "P=%~1"
if "%P%"=="" set "P=ORIGINAL"
"%~dp0.venv\Scripts\python.exe" -m masterquo profile %P%
set "RC=%ERRORLEVEL%"
popd
pause
exit /b %RC%
