@echo off
rem PepeMarketWizard - trening wszystkich rodzin modeli dla XAUUSD
rem Trening offline/SHADOW: nie wysyla zlecen, nie zamyka pozycji, nie zmienia Execution Lock.
setlocal
title PepeMarketWizard - trening XAUUSD
call "%~dp0tools\trening.cmd" run --instruments XAUUSD --interactive --origin TRENUJ_XAUUSD.bat
set "RC=%ERRORLEVEL%"
echo Kod: %RC%  (0 wszystko wykonane - jakosc w raporcie, 1 blad techniczny, 2 zablokowane, 3 anulowane, 4 czesc pominieta)
pause
exit /b %RC%
