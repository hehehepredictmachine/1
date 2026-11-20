@echo off
rem 1.42.4: wspolny wybor Pythona dla skryptow .bat (wolany przez CALL, bez setlocal - ustawia PY w skrypcie wolajacym).
rem Kolejnosc: 1) .venv w folderze programu (instalacja klasyczna / INSTALUJ_TRENING.bat),
rem            2) aplikacja Windows: runtime\python + biblioteki pobrane przy pierwszym starcie (<home>\pyenv\cp313-*\site-packages;
rem               <home> = PMW_HOME, folder programu przy portable.txt, inaczej %LOCALAPPDATA%\PepeMarketWizard - jak desktop\layout.go).
rem Wymaga zmiennej ROOT (folder programu bez koncowego \).
set "PY=%ROOT%\.venv\Scripts\python.exe"
if exist "%PY%" goto :eof
if not exist "%ROOT%\runtime\python\python.exe" goto :eof
set "PMW_H="
if defined PMW_HOME set "PMW_H=%PMW_HOME%"
if not defined PMW_H if exist "%ROOT%\portable.txt" set "PMW_H=%ROOT%"
if not defined PMW_H set "PMW_H=%LOCALAPPDATA%\PepeMarketWizard"
set "PMW_SITE="
for /f "delims=" %%D in ('dir /b /ad /o:d "%PMW_H%\pyenv\cp313-*" 2^>nul') do set "PMW_SITE=%PMW_H%\pyenv\%%D\site-packages"
if not defined PMW_SITE goto :eof
set "PY=%ROOT%\runtime\python\python.exe"
set "PYTHONPATH=%ROOT%\backend;%PMW_SITE%"
set "PYTHONNOUSERSITE=1"
goto :eof
