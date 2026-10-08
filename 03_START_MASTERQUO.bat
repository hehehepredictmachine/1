@echo off
setlocal
cd /d "%~dp0"
if not exist "%~dp0.venv\Scripts\python.exe" (
  echo [BLAD] Brak .venv - uruchom najpierw 01_INSTALUJ.bat
  pause
  exit /b 1
)
rem Ponowny START otwiera istniejacy monitor zamiast uruchamiac kolejna kopie.
rem Opcja: 03_START_MASTERQUO.bat --demo  = DANE SYNTETYCZNE (symulator, osobna baza)
start "MasterQUO server" /D "%~dp0backend" "%~dp0.venv\Scripts\python.exe" -m masterquo serve %*
echo [MasterQUO] Serwer uruchamiany w oknie "MasterQUO server". Monitor otworzy sie w przegladarce: http://127.0.0.1:8765/
echo            Zamkniecie przegladarki NIE zatrzymuje programu. Do zatrzymania: 04_STOP_MASTERQUO.bat
timeout /t 5 >nul
exit /b 0
