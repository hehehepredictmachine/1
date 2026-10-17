@echo off
rem PepeMarketWizard - JEDEN plik: trenuje wszystkie modele bota i przekazuje je do dzialajacego bota.
rem  1) bot (uruchamiany w tle, jesli nie dziala) + polaczenie z MT5
rem  2) prognozy gold_candles: eksport M5/M30 + trening + przeladowanie w bocie
rem  3) scalp ML/NN (A/B/C): eksport M1-H1 + trening (prowizja 0.50/lot/strone) + replay
rem  4) ML Decision Tree / XGBoost: probki z historii + trening
rem  5) modele lab XAUUSD i BTC: LOGREG, drzewo, MiniRocket, XGBoost, ResNet1D, SEW-SNN (+ eksperymenty)
rem Zadne zlecenie nie jest wysylane. Parametry opcjonalne: prowizja, np. 22_TRENUJ_WSZYSTKIE_MODELE.bat 3.5
setlocal
cd /d "%~dp0"
title PepeMarketWizard - trening wszystkich modeli
if not exist "%~dp0.venv\Scripts\python.exe" (echo [BLAD] Brak .venv - uruchom 01_INSTALUJ.bat & pause & exit /b 1)
set "COMM=%~1"
if "%COMM%"=="" set "COMM=0.50"
if exist "%~dp0.venv_candles\Scripts\python.exe" (set "MQ_CANDLES_PYTHON=%~dp0.venv_candles\Scripts\python.exe") else (echo [UWAGA] Brak .venv_candles - prognozy i scalp zostana pominiete. Uruchom 10_PROGNOZY_INSTALUJ.bat, aby je wlaczyc.)
if not exist "%~dp0data\logs" mkdir "%~dp0data\logs"
echo.
echo [PepeMarketWizard] Trening wszystkich modeli. MT5 musi byc uruchomiony i zalogowany. To moze potrwac od kilkudziesieciu minut do kilku godzin.
echo.
pushd "%~dp0backend"
"%~dp0.venv\Scripts\python.exe" -m masterquo train-all --commission %COMM%
set "RC=%ERRORLEVEL%"
popd
if "%RC%"=="0" (echo [OK] Gotowe. Modele dzialaja w bocie - otworz monitor: Pulpit - Wszystkie modele.) else (echo [UWAGA] Czesc krokow nie powiodla sie - patrz PODSUMOWANIE powyzej i raport w data\logs.)
pause
exit /b %RC%
