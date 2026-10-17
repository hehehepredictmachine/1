@echo off
rem PepeMarketWizard - menu treningu: instalacja, XAUUSD, BTC, oba, diagnostyka, wyniki, wznowienie, rollback
rem Trening offline/SHADOW: nie wysyla zlecen, nie zamyka pozycji, nie zmienia Execution Lock.
setlocal
title PepeMarketWizard - trening modeli
call "%~dp0tools\trening.cmd" menu
set "RC=%ERRORLEVEL%"
echo Kod: %RC%  (0 wszystko wykonane - jakosc w raporcie, 1 blad techniczny, 2 zablokowane, 3 anulowane, 4 czesc pominieta)
pause
exit /b %RC%
