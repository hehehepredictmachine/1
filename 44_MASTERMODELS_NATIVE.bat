@echo off
rem 1.40.3: Python w trybie UTF-8 - polskie znaki i symbole w logach nie przerywaja skryptu (UnicodeEncodeError przy cp1250)
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
rem PepeMarketWizard - Master models + Math Fidelity native MQL5 (1.46 arch I0488): instalacja zrodel mql5\MasterModels i
rem mql5\MathFidelity, kompilacja w WYKRYTYM MetaEditorze (kod wyjscia + log + NOWY plik EX5 + hashe), status do
rem MQL5\Files\PMW\mm_native_status.json, fixture parytetu do MQL5\Files\PMW_MM i pliki benchmarku do MQL5\Files\PMW_MathFidelity.
rem Nie zmienia ustawien terminala ani AutoTrading, nie dolacza EA do wykresu, nie uruchamia handlu, nie tworzy fikcyjnego EX5.
rem EA tego pakietu (PMW_*ShadowEA, MathFidelityBenchmark_EA) nie maja OrderSend/CTrade - tylko logi CSV.
rem Uzycie: 44_MASTERMODELS_NATIVE.bat "folder danych terminala" "sciezka metaeditor64.exe" (oba argumenty opcjonalne)
setlocal EnableDelayedExpansion
chcp 65001 >nul
title Apollo23 - Master models native MQL5
for %%I in ("%~dp0.") do set "ROOT=%%~fI"
call "%ROOT%\tools\pmwpy.cmd"
if not exist "%PY%" (echo [BLAD] Brak Pythona bota - .venv albo runtime aplikacji; uruchom INSTALUJ_TRENING.bat albo raz aplikacje & exit /b 2)
set "DATA=%~1"
set "ME=%~2"
if "%DATA%"=="" for /d %%T in ("%APPDATA%\MetaQuotes\Terminal\*") do if exist "%%~fT\MQL5" echo   %%~fT
if "%DATA%"=="" set /p "DATA=Podaj folder danych terminala (Plik > Otworz folder danych): "
if not exist "%DATA%\MQL5" (echo [BLAD] Brak "%DATA%\MQL5" - podaj prawidlowy folder danych terminala & exit /b 2)
if "%ME%"=="" for %%P in ("%ProgramFiles%\MetaTrader 5\metaeditor64.exe" "%ProgramFiles%\MetaTrader 5 Terminal\metaeditor64.exe") do if exist "%%~fP" set "ME=%%~fP"
if "%ME%"=="" set /p "ME=Podaj pelna sciezke metaeditor64.exe: "
if not exist "%ME%" (echo [BLAD] NOT_COMPILED_NO_METAEDITOR: brak metaeditor64.exe - zrodla w mql5\MasterModels i mql5\MathFidelity & exit /b 3)
xcopy /y /i "%ROOT%\mql5\MasterModels\Include\PMW\*.mqh" "%DATA%\MQL5\Include\PMW\" >nul
xcopy /y /i "%ROOT%\mql5\MasterModels\Indicators\*.mq5" "%DATA%\MQL5\Indicators\PMW\" >nul
xcopy /y /i "%ROOT%\mql5\MasterModels\Experts\*.mq5" "%DATA%\MQL5\Experts\PMW\" >nul
xcopy /y /i "%ROOT%\mql5\MasterModels\Scripts\*.mq5" "%DATA%\MQL5\Scripts\PMW\" >nul
xcopy /y /i "%ROOT%\mql5\MathFidelity\Include\PMW_MathFidelity\*.mqh" "%DATA%\MQL5\Include\PMW_MathFidelity\" >nul
xcopy /y /i "%ROOT%\mql5\MathFidelity\Indicators\*.mq5" "%DATA%\MQL5\Indicators\PMW\" >nul
xcopy /y /i "%ROOT%\mql5\MathFidelity\Experts\*.mq5" "%DATA%\MQL5\Experts\PMW\" >nul
xcopy /y /i "%ROOT%\mql5\MathFidelity\Scripts\*.mq5" "%DATA%\MQL5\Scripts\PMW\" >nul
if not exist "%DATA%\MQL5\Files\PMW" mkdir "%DATA%\MQL5\Files\PMW"
if not exist "%DATA%\MQL5\Files\PMW_MM" mkdir "%DATA%\MQL5\Files\PMW_MM"
if not exist "%DATA%\MQL5\Files\PMW_MathFidelity" mkdir "%DATA%\MQL5\Files\PMW_MathFidelity"
set "LOG=%DATA%\MQL5\Files\PMW\mm_compile.log"
if exist "%LOG%" del "%LOG%"
set ERR=0
set "DS=%DATA%\MQL5\Scripts\PMW"
set "DI=%DATA%\MQL5\Indicators\PMW"
set "DE=%DATA%\MQL5\Experts\PMW"
for %%F in ("%DS%\PMW_MM_SelfTest.mq5" "%DS%\MathFidelity_SelfTest.mq5" "%DI%\PMW_AlignMean.mq5" "%DI%\PMW_BreakoutZones.mq5" "%DI%\PMW_GPR_Forecast.mq5" "%DI%\PMW_KalmanCross.mq5" "%DI%\PMW_TickSessionVP.mq5" "%DI%\FidelityMonitor.mq5" "%DE%\PMW_GPR_ShadowEA.mq5" "%DE%\PMW_KalmanShadowEA.mq5" "%DE%\MathFidelityBenchmark_EA.mq5") do (
  if exist "%%~dpnF.ex5" del "%%~dpnF.ex5"
  if not exist "%%~F" (echo [BLAD] brak zrodla %%~nxF & set /a ERR+=1) else (
    "%ME%" /compile:"%%~F" /inc:"%DATA%\MQL5" /log:"%%~dpnF.log"
    if not exist "%%~dpnF.ex5" (echo [BLAD] brak EX5 dla %%~nxF - zobacz %%~dpnF.log & set /a ERR+=1) else (echo [OK] %%~nxF)
    type "%%~dpnF.log" >> "%LOG%" 2>nul
  )
)
"%PY%" -I "%ROOT%\tools\mr2_native_status.py" "%DATA%" !ERR! "%LOG%" --mm
pushd "%ROOT%\backend"
"%PY%" -m masterquo mm export-fixtures --out "%DATA%\MQL5\Files\PMW_MM"
"%PY%" -m masterquo mm mathbench-export --out "%DATA%\MQL5\Files\PMW_MathFidelity"
popd
if !ERR! GTR 0 exit /b 4
echo.
echo Teraz w terminalu: Nawigator ^> Skrypty ^> PMW ^> PMW_MM_SelfTest (wynik MQL5\Files\PMW_MM\PMW_MM_NATIVE.txt) oraz MathFidelity_SelfTest.
echo Parytet: "%PY%" -m masterquo mm export-fixtures --out "%DATA%\MQL5\Files\PMW_MM" --parity "%DATA%\MQL5\Files\PMW_MM\PMW_MM_NATIVE.txt"
echo Ustaw MQ_MT5_FILES_DIR=%DATA%\MQL5\Files - inwentarz master models pokaze wtedy kompilacje i parytet. Instalacja nie uruchamia handlu.
exit /b 0
