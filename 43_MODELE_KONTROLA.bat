@echo off
rem Apollo23 - kontrola zdrowia wszystkich modeli (1.46): rejestr kanoniczny (quant/ids.py), srodowiska modeli, import,
rem opcjonalnie smoke (trening / artefakt / predykcja na danych SYNTHETIC_TEST) i sciezka na zywo (Runtime demo na symulatorze).
rem Wszystko w folderze tymczasowym: dane uzytkownika, tryb wykonania i aktywne modele bez zmian. Zadne zlecenie nie jest wysylane.
rem Wynik smoke to test techniczny sciezki - NIE jakosc modelu. Brak srodowiska / wag = NIEZWERYFIKOWANY (nigdy "dziala").
setlocal
chcp 65001 >nul
title Apollo23 - Kontrola modeli
set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
call "%ROOT%\tools\pmwpy.cmd"
if not exist "%PY%" (echo [BLAD] Brak Pythona bota (.venv albo runtime aplikacji) - uruchom INSTALUJ_TRENING.bat albo raz aplikacje Apollo23 - PepeMarketWizard.exe & pause & exit /b 2)
set "ROOT=%ROOT%\"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
set "OUT=%TEMP%\Apollo23_kontrola_modeli.md"
:menu
echo.
echo  1 - Szybka kontrola: rejestr, srodowiska modeli, import (kilka sekund)
echo  2 - Kontrola ze smoke: trening/artefakt/predykcja na danych testowych (kilka minut)
echo  3 - Smoke + sciezka na zywo (Runtime demo na symulatorze przez 120 s)
echo  0 - Koniec
set "CH="
set /p "CH=Wybor: "
pushd "%ROOT%backend"
if "%CH%"=="1" "%PY%" -m masterquo models check --md "%OUT%"
if "%CH%"=="2" "%PY%" -m masterquo models check --smoke --md "%OUT%"
if "%CH%"=="3" "%PY%" -m masterquo models check --smoke --live 120 --md "%OUT%"
popd
if "%CH%"=="0" exit /b 0
if not "%CH%"=="" echo. & echo Tabela wyniku: "%OUT%"
goto menu
