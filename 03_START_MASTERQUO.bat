@echo off
setlocal
cd /d "%~dp0"
rem Od wersji 1.7 start odbywa sie przez masterquo_start.bat (wklejenie licencji przy kazdym uruchomieniu).
rem Okno "MasterQUO server" poprosi o licencje - wklej ja tam (prawy przycisk myszy) i nacisnij Enter.
start "MasterQUO server" "%~dp0masterquo_start.bat" %*
echo [MasterQUO] W oknie "MasterQUO server" wklej licencje. Monitor: http://127.0.0.1:8765/
echo            Zamkniecie przegladarki NIE zatrzymuje programu. Do zatrzymania: 04_STOP_MASTERQUO.bat
timeout /t 3 >nul
exit /b 0
