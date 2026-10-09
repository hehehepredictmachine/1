# MasterQUO AI – START TUTAJ

Lokalna aplikacja Windows: Twój terminal MetaTrader 5 → silnik MasterQUO → agent Claude → ryzyko → monitor w przeglądarce
`http://127.0.0.1:8765`. Domyślnie **READ_ONLY** i **AUTO OFF** – program niczego nie kupuje ani nie sprzedaje, dopóki sam tego nie włączysz.

## Wymagania
* Windows 10/11 64-bit, **Python 3.13 x64** (albo 3.12) z python.org z zaznaczonym „py launcher”.
* MetaTrader 5 zainstalowany, **uruchomiony i zalogowany**, symbol `XAUUSD-` widoczny w „Market Watch”.
* W MT5: Narzędzia → Opcje → Doradcy Expert → „Zezwalaj na handel algorytmiczny” – potrzebne dopiero do trybu DEMO/LIVE.
* Klucz API Anthropic (opcjonalny – bez niego działa wszystko poza agentem Claude).
* Node.js **nie** jest potrzebny (monitor jest już zbudowany).

## Kroki
1. Rozpakuj ZIP do nowego folderu, np. `C:\MasterQUO_AI` (nie nadpisuj starej paczki).
2. Kliknij **`01_INSTALUJ.bat`** – tworzy `.venv` w folderze projektu i instaluje przypięte pakiety. Log: `data\logs\instalacja_*.log`.
3. Kliknij **`02_DIAGNOSTYKA.bat`** – sprawdza Python, pakiety, połączenie z terminalem, symbol, rachunek, czas, klucz Claude.
   Nie składa zleceń. Wynik zapisuje w `data\logs`.
4. Kliknij **`03_START_MASTERQUO.bat`** – serwer startuje w osobnym oknie, przeglądarka otwiera monitor.
5. Przy pierwszym uruchomieniu monitor pokaże kreator: limity ryzyka, koszty (prowizja), klucz Claude i model.
   * Klucz wpisujesz **tylko w monitorze** (pole hasła) albo w oknie konsoli: `.venv\Scripts\python -m masterquo set-key` w folderze `backend`.
     Jest szyfrowany Windows DPAPI w `data\secrets.dpapi.json`. Nie wklejaj go nigdzie indziej.
   * Model: wybierz z listy pobranej z Twojego konta (przycisk „Testuj połączenie”) albo wpisz w `ANTHROPIC_MODEL`.
6. Zamknięcie przeglądarki **nie** zatrzymuje programu. Zatrzymanie: **`04_STOP_MASTERQUO.bat`** (zatrzymuje tylko MasterQUO,
   nie inne programy Pythona ani terminal MT5).

## Pozostałe skróty
* `05_TESTY_OFFLINE.bat` – testy na symulatorze (nie dotyka Twojego MT5); `05_TESTY_OFFLINE.bat --legacy` dodaje testy oryginalnej paczki.
* `06_DIAGNOZA_CZASU_MT5.bat` – surowe czasy ticków/świec i zmierzony offset serwera (uruchom przy otwartym rynku).
* `07_START_DEMO_DANE_SYNTETYCZNE.bat` – pokaz na danych z symulatora (wyraźny napis DANE SYNTETYCZNE, osobna baza).

## Tryby pracy (pasek u góry monitora)
| Tryb | Co robi | Jak włączyć |
|---|---|---|
| READ_ONLY | tylko analiza | domyślny |
| PAPER | wirtualne zlecenia na prawdziwych notowaniach | limity + wpisz `PAPER` |
| DEMO_EXECUTION | zlecenia na rachunku DEMO | rachunek DEMO + wpisz jego numer |
| LIVE_EXECUTION | prawdziwe pieniądze | rachunek REAL + `"allow_live_execution": true` w `data\config.json` + wpisz `LIVE <numer>` |

AUTO TRADING to osobny przełącznik. Restart, zmiana rachunku lub limitów wraca do READ_ONLY. Przycisk **STOP AUTO / KILL** blokuje nowe wejścia natychmiast.

## Jak czytać sygnał
* „Kierunek analizy” (LONG/SHORT/NEUTRAL) ≠ „Decyzja” (BUY/SELL/WAIT/NO_TRADE) ≠ „Uprawnienie” (ALLOWED/BLOCKED).
* Drzewo decyzji pokazuje 7 bramek: dane, rynek, strategia, wyzwalacz, ryzyko, AI, tryb – przy każdej powód blokady.
* „Jakość” to ocena punktowa, **nie** prawdopodobieństwo wygranej.

## Gdy coś nie działa
* „Brak .venv” → uruchom `01_INSTALUJ.bat`.
* „Terminal niepołączony” → uruchom i zaloguj MT5, potem przycisk „Połącz ponownie”.
* „Symbol XAUUSD- niedostępny” → dodaj go w Market Watch; program **nie** zamienia go na inny symbol.
* Czas „UNKNOWN/STORED_UNVERIFIED” → normalne przy zamkniętym rynku; `06_DIAGNOZA_CZASU_MT5.bat` przy otwartym rynku.
* Port 8765 zajęty → zmień `server.port` w `data\config.json`.
* Dokumenty: `ARCHITEKTURA.md`, `MAPA_WYMAGAN.md`, `RAPORT_TESTOW.md`, `ZNANE_OGRANICZENIA.md`, `MIGRACJA_I_ZMIANY.md`, `AUDYT_WEJSCIOWY.md`.

Aplikacja jest narzędziem badawczym. Strategie nie mają zweryfikowanej skuteczności – zacznij od READ_ONLY i PAPER.
