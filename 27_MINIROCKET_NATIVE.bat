@echo off
rem PepeMarketWizard - MiniRocket V2 native MQL5 (PMW-UPD-09 R21): instalacja zrodel, kompilacja w WYKRYTYM MetaEditorze,
rem weryfikacja (kod wyjscia + log + NOWY plik EX5 + hashe), status do MQL5\Files\PMW\native_status.json.
rem Nie zmienia ustawien terminala, nie uruchamia handlu, nie tworzy fikcyjnego EX5. Self-test/benchmark uruchamiasz w terminalu (Skrypty).
setlocal EnableDelayedExpansion
chcp 65001 >nul
for %%I in ("%~dp0.") do set "ROOT=%%~fI"
set "PY=%ROOT%\.venv\Scripts\python.exe"
set "DATA=%~1"
set "ME=%~2"
if "%DATA%"=="" set /p "DATA=Podaj folder danych terminala (Plik > Otworz folder danych), np. C:\Users\X\AppData\Roaming\MetaQuotes\Terminal\HASH: "
if not exist "%DATA%\MQL5" (echo [BLAD] Brak "%DATA%\MQL5" - podaj prawidlowy folder danych terminala & exit /b 2)
if "%ME%"=="" for %%P in ("%ProgramFiles%\MetaTrader 5\metaeditor64.exe") do if exist "%%~P" set "ME=%%~P"
if "%ME%"=="" set /p "ME=Podaj pelna sciezke metaeditor64.exe: "
if not exist "%ME%" (echo [BLAD] NOT_COMPILED_NO_METAEDITOR: brak metaeditor64.exe & exit /b 3)
xcopy /y /i "%ROOT%\mql5\MiniRocketV2\Include\PMW\*.mqh" "%DATA%\MQL5\Include\PMW\" >nul
xcopy /y /i "%ROOT%\mql5\MiniRocketV2\Scripts\*.mq5" "%DATA%\MQL5\Scripts\PMW\" >nul
xcopy /y /i "%ROOT%\mql5\MiniRocketV2\Indicators\*.mq5" "%DATA%\MQL5\Indicators\PMW\" >nul
if not exist "%DATA%\MQL5\Files\PMW" mkdir "%DATA%\MQL5\Files\PMW"
set "LOG=%DATA%\MQL5\Files\PMW\mr2_compile.log"
set ERR=0
for %%F in ("%DATA%\MQL5\Scripts\PMW\PMW_MR2_*.mq5" "%DATA%\MQL5\Indicators\PMW\PMW_MR2_*.mq5") do (
  if exist "%%~dpnF.ex5" del "%%~dpnF.ex5"
  "%ME%" /compile:"%%~F" /inc:"%DATA%\MQL5" /log:"%%~dpnF.log"
  if not exist "%%~dpnF.ex5" (echo [BLAD] brak EX5 dla %%~nxF - zobacz %%~dpnF.log & set /a ERR+=1) else (echo [OK] %%~nxF)
  type "%%~dpnF.log" >> "%LOG%" 2>nul
)
"%PY%" -I "%ROOT%\tools\mr2_native_status.py" "%DATA%" !ERR! "%LOG%"
if !ERR! GTR 0 exit /b 4
echo Teraz w terminalu: Nawigator ^> Skrypty ^> PMW ^> PMW_MR2_SelfTest (potem PMW_MR2_Benchmark). Wynik: MQL5\Files\PMW\mr2_selftest.txt
exit /b 0
