@echo off
rem PepeMarketWizard - zgodnosc wsteczna: ten sam mechanizm co 00_TRENING_START.bat / TRENUJ_OBA.bat (XAUUSD, potem BTC).
rem Parametr opcjonalny: prowizja XAUUSD na 1 lot na strone, np. 22_TRENUJ_WSZYSTKIE_MODELE.bat 3.5 (BTC: z historii transakcji
rem albo podana w menu). Aktywowane sa tylko modele dopuszczone walidacja. Zadne zlecenie nie jest wysylane.
setlocal
title PepeMarketWizard - trening wszystkich modeli
set "COMM=%~1"
if "%COMM%"=="" set "COMM=0.50"
call "%~dp0tools\trening.cmd" run --instruments XAUUSD,BTC --commission-xauusd %COMM% --origin 22_TRENUJ_WSZYSTKIE_MODELE.bat
set "RC=%ERRORLEVEL%"
echo Kod: %RC%  (0 wszystko wykonane - jakosc w raporcie, 1 blad techniczny, 2 zablokowane, 3 anulowane, 4 czesc pominieta)
pause
exit /b %RC%
