@echo off
setlocal
rem Replay profilu scalp na najnowszym eksporcie (OHLC M1 + spread z MT5; przyblizony - bez tickow), z kosztami i stresem +50%%.
rem Opcjonalny argument (domyslnie 0.50): prowizja za 1 lot na strone (waluta konta). Przyklad: 19_REPLAY_SCALP.bat 3.5
rem Wynik: data\scalp\replay\^<czas^>\summary.json (cykle, dni, win ratio, expectancy R z 95%% CI, hedge vs REDUCE) oraz
rem variants.json - porownanie wariantow poprawy win ratio (wybor po expectancy w development, test oceniany raz).
cd /d "%~dp0"
set "COMM=%~1"
if "%COMM%"=="" set "COMM=0.50"
echo Prowizja za 1 lot na strone: %COMM% ^(domyslnie 0.50 - inna wartosc: %~nx0 3.5^)
if not exist "%~dp0.venv\Scripts\python.exe" (echo [BLAD] Brak .venv - uruchom 01_INSTALUJ.bat & pause & exit /b 1)
pushd "%~dp0backend"
"%~dp0.venv\Scripts\python.exe" -m masterquo scalp-replay --commission-per-lot-side %COMM%
set "RC=%ERRORLEVEL%"
if "%RC%"=="0" "%~dp0.venv\Scripts\python.exe" -m masterquo scalp-replay --commission-per-lot-side %COMM% --cost-stress 1.5
if "%RC%"=="0" "%~dp0.venv\Scripts\python.exe" -m masterquo scalp-replay --commission-per-lot-side %COMM% --margin-mode NETTING
if "%RC%"=="0" "%~dp0.venv\Scripts\python.exe" -m masterquo scalp-replay --commission-per-lot-side %COMM% --variants
popd
pause
exit /b %RC%
