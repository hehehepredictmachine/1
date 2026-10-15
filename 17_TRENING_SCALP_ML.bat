@echo off
setlocal
rem Trening modeli scalp (A: kierunek 1/3/5 min - baseline, regresja logistyczna, HistGradientBoosting, siec MLP 64/32, kwantyle;
rem B: jakosc setupu z replayu; C: HOLD/REDUCE/CLOSE/HEDGE_PARTIAL) na NAJNOWSZYM eksporcie data\scalp\history.
rem Opcjonalny argument (domyslnie 0.50): prowizja za 1 lot na strone w walucie konta (z warunkow Twojego rachunku; "Zero" nie oznacza 0 kosztow).
rem Przyklad: 17_TRENING_SCALP_ML.bat 3.5    Wynik: data\scalp\runs\^<run_id^>\ (plan, raport, log). Tylko SHADOW.
cd /d "%~dp0"
set "COMM=%~1"
if "%COMM%"=="" set "COMM=0.50"
echo Prowizja za 1 lot na strone: %COMM% ^(domyslnie 0.50 - inna wartosc: %~nx0 3.5^)
if not exist "%~dp0.venv_candles\Scripts\python.exe" (echo [BLAD] Brak .venv_candles - uruchom 10_PROGNOZY_INSTALUJ.bat & pause & exit /b 1)
set "PYTHONPATH=%~dp0backend"
pushd "%~dp0backend"
"%~dp0.venv_candles\Scripts\python.exe" -m gold_candles_runtime.scalp_train --latest --commission-per-lot-side %COMM%
set "RC=%ERRORLEVEL%"
popd
if "%RC%"=="0" (echo [OK] Raport: data\scalp\runs\^<run_id^>\report.json) else (echo [BLAD/BLOKADA] kod %RC% - np. BLOCKED_NO_REAL_DATA, INSUFFICIENT_DATA)
pause
exit /b %RC%
