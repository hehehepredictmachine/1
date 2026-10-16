@echo off
setlocal
cd /d "%~dp0"
rem Start serwera PepeMarketWizard w osobnym oknie "PepeMarketWizard server"; monitor otworzy sie w przegladarce.
start "PepeMarketWizard server" "%~dp0masterquo_start.bat" %*
echo [PepeMarketWizard] Serwer uruchamiany w oknie "PepeMarketWizard server". Monitor: http://127.0.0.1:8765/
echo            Zamkniecie przegladarki NIE zatrzymuje programu. Do zatrzymania: 04_STOP_MASTERQUO.bat
timeout /t 5 >nul
exit /b 0
