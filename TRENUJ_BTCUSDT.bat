@echo off
rem PepeMarketWizard - trening wszystkich rodzin modeli dla BTC (symbol np. BTCUSDT- wybierany z terminala)
rem Trening offline/SHADOW: nie wysyla zlecen, nie zamyka pozycji, nie zmienia Execution Lock.
setlocal
title PepeMarketWizard - trening BTC
call "%~dp0tools\trening.cmd" run --instruments BTC --interactive --origin TRENUJ_BTCUSDT.bat
set "RC=%ERRORLEVEL%"
echo Kod: %RC%  (0 wszystko wykonane - jakosc w raporcie, 1 blad techniczny, 2 zablokowane, 3 anulowane, 4 czesc pominieta)
pause
exit /b %RC%
