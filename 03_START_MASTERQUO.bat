@echo off
setlocal
cd /d "%~dp0"
rem Start serwera MasterQUO w osobnym oknie "MasterQUO server"; monitor otworzy sie w przegladarce.
start "MasterQUO server" "%~dp0masterquo_start.bat" %*
echo [MasterQUO] Serwer uruchamiany w oknie "MasterQUO server". Monitor: http://127.0.0.1:8765/
echo            Zamkniecie przegladarki NIE zatrzymuje programu. Do zatrzymania: 04_STOP_MASTERQUO.bat
timeout /t 5 >nul
exit /b 0
