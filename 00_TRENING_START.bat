@echo off
rem PepeMarketWizard - menu treningu: instalacja, XAUUSD, BTC, oba, diagnostyka, wyniki, wznowienie, rollback
rem Trening offline/SHADOW: nie wysyla zlecen, nie zamyka pozycji, nie zmienia Execution Lock.
setlocal
rem ---- 0. kompletnosc rozpakowania (brak plikow to nie problem z Pythonem)
set "MQ_MISSING="
for %%F in ("tools\check_python.py" "tools\trening.cmd" "backend\masterquo\__main__.py" "backend\mq_instruments.py" "frontend\dist\index.html" "MANIFEST_SHA256.txt") do (
  if not exist "%~dp0%%~F" set "MQ_MISSING=%%~F"
)
if defined MQ_MISSING (
  echo [BLAD] Niekompletny folder programu - brak pliku: %MQ_MISSING%
  echo        Folder: "%~dp0"
  echo        Rozpakuj CALY plik ZIP: prawy klik - Wyodrebnij wszystkie - do NOWEGO, pustego folderu,
  echo        potem uruchom instalator z tego folderu. Nie uruchamiaj .bat z podgladu ZIP i nie kopiuj pojedynczych plikow.
  echo        Jesli plik znika po rozpakowaniu, sprawdz kwarantanne antywirusa.
  pause
  exit /b 2
)
title PepeMarketWizard - trening modeli
call "%~dp0tools\trening.cmd" menu
set "RC=%ERRORLEVEL%"
echo Kod: %RC%  (0 wszystko wykonane - jakosc w raporcie, 1 blad techniczny, 2 zablokowane, 3 anulowane, 4 czesc pominieta)
pause
exit /b %RC%
