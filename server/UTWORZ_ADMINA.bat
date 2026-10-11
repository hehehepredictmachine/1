@echo off
setlocal
rem Tworzy konto administratora panelu licencji (haslo + kod TOTP). Bez domyslnego hasla - wpisujesz je sam.
cd /d "%~dp0"
set "PY=%~dp0..\.venv-server\Scripts\python.exe"
if not exist "%PY%" (
  echo [BLAD] Brak .venv-server - uruchom najpierw INSTALUJ_SERWER.bat
  pause
  exit /b 1
)
set "ENVF="
if exist "%~dp0.env" set "ENVF=%~dp0.env"
if exist "%~dp0data\dev\dev.env" set "ENVF=%~dp0data\dev\dev.env"
if not defined ENVF (
  echo [BLAD] Serwer nie jest jeszcze skonfigurowany. Uruchom raz start_dev_server.bat ^(test lokalny^) albo przygotuj .env ^(produkcja^).
  pause
  exit /b 1
)
"%PY%" -m mqlicense --env-file "%ENVF%" migrate >nul
echo.
echo ===== MasterQUO - nowe konto administratora =====
set /p "ADMIN_EMAIL=E-mail administratora: "
if "%ADMIN_EMAIL%"=="" (
  echo [BLAD] Nie podano e-maila.
  pause
  exit /b 1
)
echo Haslo: min. 12 znakow ^(znaki nie sa wyswietlane^).
"%PY%" -m mqlicense --env-file "%ENVF%" bootstrap-admin --email "%ADMIN_EMAIL%"
if errorlevel 3 (
  echo Pierwszy administrator juz istnieje - tworze kolejne konto ADMIN.
  "%PY%" -m mqlicense --env-file "%ENVF%" add-admin --email "%ADMIN_EMAIL%" --role ADMIN
)
echo.
echo Zeskanuj powyzszy adres otpauth:// w aplikacji TOTP ^(Google Authenticator, Aegis...^) albo wpisz sekret recznie.
echo Logowanie: http://127.0.0.1:8790/admin/  ^(e-mail + haslo + 6-cyfrowy kod^)
pause
