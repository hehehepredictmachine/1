@echo off
rem PepeMarketWizard - diagnostyka: srodowisko, blokady wersji, terminal MT5, symbole XAUUSD/BTC (odczyt)
rem Trening offline/SHADOW: nie wysyla zlecen, nie zamyka pozycji, nie zmienia Execution Lock.
setlocal
title PepeMarketWizard - diagnostyka treningu
call "%~dp0tools\trening.cmd" diag
set "RC=%ERRORLEVEL%"
echo Kod: %RC%  (0 wszystko wykonane - jakosc w raporcie, 1 blad techniczny, 2 zablokowane, 3 anulowane, 4 czesc pominieta)
pause
exit /b %RC%
