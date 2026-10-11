@echo off
setlocal
cd /d "%~dp0"
rem Start w TYM SAMYM oknie terminala: najpierw wklejasz licencje, dopiero potem startuje serwer glowny.
call "%~dp0masterquo_start.bat" %*
exit /b %ERRORLEVEL%
