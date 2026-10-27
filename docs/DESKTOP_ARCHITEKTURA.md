# PepeMarketWizard Desktop – architektura aplikacji Windows (1.24.0)

Status: **zbudowana i przetestowana na Linuksie (kompilacja krzyżowa, testy jednostkowe i integracyjne nadzoru silnika); NIE uruchomiona
na rzeczywistym Windows** – w środowisku budowania nie było Windows. Lista kontrolna pierwszego uruchomienia: §9.

## 1. Wybór technologii

| Wariant | Ocena |
|---|---|
| **Go + WebView2 (wybrany)** | Jeden mały EXE (~7 MB), bez CGO, kompiluje się z Linuksa i Windows; okno to systemowy Edge WebView2 (Windows 11 – wbudowany, Windows 10 – instalowany z Edge). Panel React działa bez zmian. Nadzór procesu, Job Object, zasobnik i autostart – natywne API Windows. |
| Electron | Gotowy ekosystem, ale +150 MB, drugi runtime Node w paczce, osobny łańcuch aktualizacji. |
| Tauri | Lekki, ale wymaga Rust + MSVC do budowy (brak w środowisku), a i tak potrzebuje WebView2. |
| pywebview / PyInstaller | Okno zależne od Pythona; zamrożony Python utrudnia aktualizację zależności i bywa flagowany przez antywirusy. |
| Sam przeglądarkowy panel + BAT | Stan dotychczasowy – brak własnego okna, zasobnika, autostartu i nadzoru silnika. |

Biblioteka okna: `github.com/jchv/go-webview2` (MIT, ładuje WebView2Loader z pamięci – bez dodatkowych DLL).
Silnik pozostaje w Pythonie (bez zmian architektury bota): oficjalny CPython z pakietu NuGet `python` 3.13.17 (sprawdzony SHA-512
z katalogu NuGet, przypięty SHA-256 w `tools/build_desktop.py`).

## 2. Układ folderów

```
<program>\PepeMarketWizardDesktop.exe     aplikacja (okno, nadzór silnika, zasobnik)
<program>\runtime\python\python.exe       wbudowany Python (nic nie jest instalowane w systemie)
<program>\runtime\wheels\                 tylko paczka OFFLINE – zależności bez internetu
<program>\backend, frontend\dist, ...     silnik i panel (te same pliki co w paczce KLIENT)
%LOCALAPPDATA%\PepeMarketWizard\
    data\                                 konfiguracja, baza, logi, modele, sekrety DPAPI (MASTERQUO_DATA_DIR)
    pyenv\cp313-<sha12>\site-packages     zależności (jeden folder na wersję requirements – poprzedni zostaje do rollbacku)
    backups\<data>_przed_<wersja>\        kopia danych przed uruchomieniem nowej wersji (+ BACKUP_MANIFEST.json)
    webview2\                             profil okna WebView2 (pamięć podręczna, preferencje wyglądu panelu)
    desktop.log, desktop_state.json       dziennik powłoki, ostatnia wersja / decyzja importu
```

Tryb przenośny: plik `portable.txt` obok EXE → wszystko powyższe w folderze programu.
Aktualizacja = nowy folder programu; dane i zależności poza nim nie są nadpisywane. Rollback = uruchomienie poprzedniego folderu
(jego `pyenv` nadal istnieje) i ewentualnie przywrócenie kopii z `backups\` (instrukcja w manifeście kopii).

## 3. Przebieg startu

1. Jedna kopia na sesję Windows (mutex `Local\PepeMarketWizardDesktop`); druga kopia tylko pokazuje okno pierwszej.
2. Brak WebView2 Runtime → komunikat: strona instalatora Microsoftu albo tryb awaryjny (bot + panel w przeglądarce).
3. Okno z ekranem startowym (logo Pepe, postęp, błędy z przyciskami „Spróbuj ponownie”, „Otwórz folder logów”, „Zamknij”).
4. **Dane** – przy pierwszym starcie, jeśli obok programu jest poprzednia instalacja (`…\data\config.json`), użytkownik wybiera:
   skopiować dane (oryginał tylko czytany; stan `runtime\`, blokada instancji i kopie nie są kopiowane) albo zacząć od zera.
   Import nigdy nie nadpisuje istniejących danych. **Tryb AUTO_DEMO/AUTO_LIVE z kopii zamieniany jest na PAPER** z notatką
   w panelu – nowa instalacja nie wykonuje zleceń bez ponownego, świadomego wyboru.
5. **Kopia przed aktualizacją** – gdy zapisana wersja ≠ bieżąca. Nieudana kopia zatrzymuje start (dane bez zmian).
6. **Zależności** – jeśli `pyenv` dla bieżącego `requirements-win.txt` nie jest gotowy: `pip install --require-hashes
   --only-binary=:all: --no-deps --target …` (z PyPI albo z `runtime\wheels`), instalacja do folderu tymczasowego, sprawdzenie
   importów (`fastapi, uvicorn, pydantic, anthropic, numpy, websockets, MetaTrader5`), dopiero potem zamiana folderu.
   Dodatkowo nieblokujące sprawdzenie `sklearn, xgboost` (XGBoost wymaga środowiska OpenMP z pakietu Microsoft Visual C++
   Redistributable – brak jest zgłaszany, bot startuje).
7. **Silnik** – `python -m masterquo serve --no-browser` bez okna konsoli, `PYTHONPATH=backend;site-packages`,
   `PYTHONNOUSERSITE=1` (obcy Python w systemie nie ma wpływu), `MASTERQUO_DATA_DIR`, `PMW_DESKTOP=1`, `PMW_DESKTOP_EXE`.
   Gotowość = `/api/v1/health` z nazwą tej aplikacji. Działający już silnik (np. z `03_START_MASTERQUO.bat`) jest **podłączany**,
   nie dublowany – i nie jest zatrzymywany przy zamknięciu okna.
8. Okno przechodzi na panel `http://127.0.0.1:<port>/` (port z `data\config.json`, domyślnie 8765).

## 4. Nadzór silnika

* Proces w Job Object z `KILL_ON_JOB_CLOSE`: gdy powłoka zniknie (także awaria / Menedżer zadań), Windows kończy silnik – nie zostaje
  niewidoczny bot handlujący bez okna i ikony.
* Nieoczekiwane zakończenie → ponowny start po 2/5/15/30/60 s, maks. 5 w 10 min, potem stan „nie działa” z przyciskiem ponowienia.
  Po powrocie silnika panel jest przeładowywany (nowa sesja).
* „Uruchom ponownie silnik” (zasobnik lub panel `POST /api/v1/desktop/restart-engine`) → `runtime\restart.request` + zwykłe
  zamknięcie → natychmiastowy start bez traktowania jako awarii.
* Zatrzymanie: `POST /api/v1/admin/shutdown` z tokenem z `runtime\shutdown.token`, po 25 s wymuszenie. Koniec sesji Windows
  (`WM_ENDSESSION`) – zatrzymanie z limitem 10 s.

## 5. Okno, zamykanie, zasobnik, autostart

* Zamknięcie okna według ustawienia **Centrum sterowania → Praca aplikacji** (`data\desktop_prefs.json`):
  `ask` (domyślnie – pytanie Tak/Nie/Anuluj), `background` (ukrycie, bot działa, ikona przy zegarze), `exit` (zatrzymanie bota).
* Ikona przy zegarze: stan silnika w podpowiedzi; menu „Otwórz okno”, „Uruchom ponownie silnik”, „Folder logów”,
  „Zamknij aplikację (zatrzymaj bota)”. Odtwarzana po restarcie Eksploratora.
* **Autostart jest wyłączony, dopóki użytkownik go nie włączy.** Włączenie zapisuje wartość `PepeMarketWizard` w
  `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` (`"<exe>" --autostart`, bez uprawnień administratora), wyłączenie ją usuwa.
  Opcja „start w tle” ukrywa okno przy starcie z autostartu. Wpis wskazujący inną kopię programu jest pokazywany w panelu.

## 6. Bezpieczeństwo

* Panel komunikuje się z powłoką **wyłącznie przez lokalne API silnika** z dotychczasową ochroną: nasłuch tylko 127.0.0.1,
  kontrola nagłówka Host (DNS rebinding), Origin, sesja + token CSRF dla każdej zmiany. Inne strony w przeglądarce i inne procesy
  bez sesji nie zmienią ustawień, autostartu ani nie zrestartują silnika (testy: `tests/test_desktop_app.py`).
* Jedyna funkcja powiązana z oknem (`window.pmw`) obsługuje wyłącznie ekran startowy (import/start od zera/ponów/logi/zamknij)
  i odmawia działania, gdy wyświetlany jest panel.
* Sekrety: bez zmian – DPAPI (bieżący użytkownik Windows) w `data\secrets`; powłoka nie czyta ani nie loguje sekretów.
  Kopia danych do `backups\` zawiera pliki zaszyfrowane DPAPI – odszyfrowanie możliwe tylko na tym koncie Windows.
* Paczka: tylko pliki śledzone w git + EXE + Python z NuGet (hash) + opcjonalnie koła z `--require-hashes`; skan sekretów
  `build_release.scan`. EXE nie jest podpisany certyfikatem – SmartScreen może ostrzec przy pierwszym uruchomieniu.

## 7. Budowanie

```
go install github.com/tc-hib/go-winres@v0.3.3      # zasoby EXE (ikona Pepe, manifest DPI, wersja)
python tools/build_desktop.py                      # release/PepeMarketWizard_DESKTOP_<wersja>.zip (~35 MB)
python tools/build_desktop.py --offline            # + runtime\wheels (~150 MB, pierwszy start bez internetu)
```
Skrypt: testy jednostkowe Go, `go vet` dla Windows, kompilacja `GOOS=windows GOARCH=amd64 CGO_ENABLED=0 -H windowsgui`, kontrola
nagłówka MZ, Python z NuGet (weryfikacja SHA-256), ZIP + `MANIFEST_DESKTOP_SHA256.txt` + `.sha256`.
Testy: `cd desktop && go test ./...`; integracyjny z prawdziwym silnikiem: `PMW_IT_PYTHON=<python z zależnościami> go test -run Engine`.
Tryb bez okna (rozwój): `PepeMarketWizardDesktop -headless` (z `PMW_APP_DIR`, `PMW_PYTHON`, `PMW_HOME`, `PMW_SKIP_PYENV=1`).

## 8. Co wykonano i sprawdzono

| Element | Sprawdzenie |
|---|---|
| Układ folderów, tryb przenośny, nadpisania env | test Go |
| Argumenty pip (hash, tylko koła, offline), folder zależności per requirements | test Go |
| Import danych (kopiowanie, źródło nietknięte, odmowa nadpisania, AUTO→PAPER), kopia przed aktualizacją | test Go |
| Decyzja importu / start od zera / błędny folder | test Go |
| Start, podłączenie do działającego, restart po awarii, restart na żądanie, zatrzymanie | test integracyjny Go z prawdziwym silnikiem (Linux) |
| Tryb bez okna: start, kopia przed aktualizacją, zatrzymanie Ctrl+C, zwolnienie portu | uruchomienie ręczne (Linux) |
| Endpointy `/api/v1/desktop*` + CSRF/Origin | `tests/test_desktop_app.py` (prawdziwy proces serwera) |
| Kompilacja Windows x64 GUI, zasoby (ikona, manifest per-monitor DPI v2, wersja) | `go vet` (GOOS=windows), build, odczyt PE |

## 9. Niewykonane – wymaga Windows

Nie uruchomiono: okna WebView2, zasobnika, okna dialogowego zamykania, mutexu pojedynczej kopii, Job Object, rejestru Run,
instalacji zależności z PyPI na Windows, połączenia z terminalem MT5. Lista kontrolna pierwszego uruchomienia na Windows 10/11 x64:

1. Rozpakuj ZIP do nowego folderu (np. `C:\PepeMarketWizard_Desktop`), uruchom `PepeMarketWizardDesktop.exe`
   (SmartScreen: „Więcej informacji → Uruchom mimo to”, EXE niepodpisany).
2. Ekran startowy → import starej instalacji albo start od zera → instalacja składników (kilka minut) → panel.
3. Sprawdź tryb (PAPER/SIGNALS), stan MT5 w nagłówku, `%LOCALAPPDATA%\PepeMarketWizard\desktop.log`.
4. Zamknij okno: pytanie Tak/Nie/Anuluj; „Tak” → ikona przy zegarze; menu ikony → „Zamknij aplikację”.
5. Centrum sterowania → Praca aplikacji: autostart włącz/wyłącz (sprawdź `HKCU\…\Run`), uruchom ponownie silnik.
6. Menedżer zadań: zakończ `PepeMarketWizardDesktop.exe` → `python.exe` silnika też musi zniknąć.
