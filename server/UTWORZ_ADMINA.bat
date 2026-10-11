@echo off
setlocal
rem Tworzy konto administratora panelu licencji (haslo + kod TOTP). Bez domyslnego hasla - wpisujesz je sam.
rem Folder serwera = ten, w ktorym jest pakiet mqlicense (dziala z MasterQUO_SERWER_LICENCJI\ albo z jego podfolderu server\)
set "SRV="
if exist "%~dp0mqlicense\__init__.py" set "SRV=%~dp0"
if not defined SRV if exist "%~dp0server\mqlicense\__init__.py" set "SRV=%~dp0server\"
if not defined SRV (
  echo [BLAD] Nie znaleziono folderu serwera ^(mqlicense^) obok tego pliku ani w podfolderze server\.
  echo        Rozpakuj CALA paczke MasterQUO_SERWER_LICENCJI_*.zip i uruchom plik z folderu server\.
  pause
  exit /b 1
)
cd /d "%SRV%"
set "VENV=%SRV%..\.venv-server"
set "PY=%VENV%\Scripts\python.exe"
if not exist "%PY%" (
  echo [BLAD] Brak .venv-server - uruchom najpierw INSTALUJ_SERWER.bat
  pause
  exit /b 1
)
set "ENVF="
if exist "%SRV%.env" set "ENVF=%SRV%.env"
if exist "%SRV%data\dev\dev.env" set "ENVF=%SRV%data\dev\dev.env"
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
