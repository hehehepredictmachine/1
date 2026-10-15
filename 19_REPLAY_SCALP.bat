@echo off
setlocal
rem Replay profilu scalp na najnowszym eksporcie (OHLC M1 + spread z MT5; przyblizony - bez tickow), z kosztami i stresem +50%%.
rem WYMAGANY argument: prowizja za 1 lot na strone (waluta konta). Przyklad: 19_REPLAY_SCALP.bat 3.5
rem Wynik: data\scalp\replay\^<czas^>\summary.json (cykle, dni, expectancy R z 95%% CI, hedge vs REDUCE).
cd /d "%~dp0"
if "%~1"=="" (echo [BLAD] Podaj prowizje za 1 lot na strone, np. 19_REPLAY_SCALP.bat 3.5 & pause & exit /b 2)
if not exist "%~dp0.venv\Scripts\python.exe" (echo [BLAD] Brak .venv - uruchom 01_INSTALUJ.bat & pause & exit /b 1)
pushd "%~dp0backend"
"%~dp0.venv\Scripts\python.exe" -m masterquo scalp-replay --commission-per-lot-side %~1
set "RC=%ERRORLEVEL%"
if "%RC%"=="0" "%~dp0.venv\Scripts\python.exe" -m masterquo scalp-replay --commission-per-lot-side %~1 --cost-stress 1.5
if "%RC%"=="0" "%~dp0.venv\Scripts\python.exe" -m masterquo scalp-replay --commission-per-lot-side %~1 --margin-mode NETTING
popd
pause
exit /b %RC%
