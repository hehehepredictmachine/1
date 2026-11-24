@echo off
setlocal
rem 1.40.3: Python w trybie UTF-8 - polskie znaki i symbole w logach nie przerywaja skryptu (UnicodeEncodeError przy cp1250)
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
rem Trening modeli scalp (A: kierunek 1/3/5 min - baseline, regresja logistyczna, HistGradientBoosting, siec MLP 64/32, kwantyle;
rem B: jakosc setupu z replayu; C: HOLD/REDUCE/CLOSE/HEDGE_PARTIAL) na NAJNOWSZYM eksporcie data\scalp\history.
rem Opcjonalny argument: prowizja za 1 lot na strone w walucie konta (z warunkow Twojego rachunku; "Zero" nie oznacza 0 kosztow).
rem Bez argumentu scalp_train bierze prowizje z historii transakcji eksportu (metadane), a gdy jej brak - 0.50 (domyslna paczki XAUUSD,
rem zrodlo zapisane w raporcie). 1.46 arch (I0110): wczesniej skrypt zawsze podawal 0.50 jako argument uzytkownika.
rem Przyklad: 17_TRENING_SCALP_ML.bat 3.5    Wynik: data\scalp\runs\^<run_id^>\ (plan, raport, log). Tylko SHADOW.
cd /d "%~dp0"
set "COMMARG="
set "COMMTXT=z historii transakcji eksportu (gdy brak: 0.50 - domyslna paczki)"
if not "%~1"=="" set "COMMARG=--commission-per-lot-side %~1"
if not "%~1"=="" set "COMMTXT=%~1 (argument)"
echo Prowizja za 1 lot na strone: %COMMTXT% ^(inna wartosc: %~nx0 3.5^)
if not exist "%~dp0.venv_candles\Scripts\python.exe" (echo [BLAD] Brak .venv_candles - uruchom 10_PROGNOZY_INSTALUJ.bat & pause & exit /b 1)
set "PYTHONPATH=%~dp0backend"
pushd "%~dp0backend"
"%~dp0.venv_candles\Scripts\python.exe" -m gold_candles_runtime.scalp_train --latest %COMMARG%
set "RC=%ERRORLEVEL%"
popd
if "%RC%"=="0" (echo [OK] Raport: data\scalp\runs\^<run_id^>\report.json) else (echo [BLAD/BLOKADA] kod %RC% - np. BLOCKED_NO_REAL_DATA, INSUFFICIENT_DATA)
pause
exit /b %RC%
