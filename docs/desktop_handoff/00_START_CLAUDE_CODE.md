# PepeMarketWizard Desktop — start dla Claude Code

Ta paczka zawiera **oryginalny projekt PepeMarketWizard 1.23.0**, trzy zaakceptowane projekty paneli, grafikę Pepe Czarodzieja oraz instrukcję wdrożeniową. Kod bota nie został jeszcze przebudowany. Dołączony stary `PepeMarketWizard.exe` jest wcześniejszym launcherem, a nie nową aplikacją desktop.

1. Rozpakuj paczkę do **nowego, pustego folderu**. Nie nadpisuj swojej obecnej wersji ani jej danych.
2. Otwórz w Claude Code folder `PepeMarketWizard`, w którym znajduje się ten plik. Jeżeli korzystasz z nowszej lub zmodyfikowanej wersji projektu, przekaż Claude ten katalog jako materiał referencyjny i każ mu ostrożnie przenieść projekt do swojej aktualnej wersji bez nadpisywania zmian.
3. Przekaż Claude Code plik `CLAUDE_DESKTOP_HANDOFF/00_PROMPT_WYKONAWCZY.md`. Możesz wkleić poniższe zdanie:

   **„Przeczytaj i wykonaj `CLAUDE_DESKTOP_HANDOFF/00_PROMPT_WYKONAWCZY.md`, korzystając z załączonych makiet i grafiki. Pracuj w tym projekcie.”**

4. Podglądy paneli znajdują się w `CLAUDE_DESKTOP_HANDOFF/01_WIDOKI/`. Otwórz je dwukrotnym kliknięciem w przeglądarce, aby obejrzeć projekt. Nie są połączone z MT5 ani rachunkiem.
5. Claude powinien zapisać raport rzeczywistych zmian i testów. Nowy EXE powstanie dopiero po wdrożeniu i zbudowaniu na Windows; nie oczekuj, że jest już gotowy w tej paczce.

## Zawartość

- `CLAUDE_DESKTOP_HANDOFF/00_PROMPT_WYKONAWCZY.md` — główne polecenie dla Claude Code.
- `CLAUDE_DESKTOP_HANDOFF/01_WIDOKI/` — trzy samodzielne podglądy zatwierdzonych paneli.
- `CLAUDE_DESKTOP_HANDOFF/02_ZRODLA_WIDOKOW/` — źródła interaktywnych makiet do analizy i przeniesienia wyglądu.
- `CLAUDE_DESKTOP_HANDOFF/03_GRAFIKA/` — ilustracja Pepe Czarodzieja w oryginale i wersji podglądowej.
- `CLAUDE_DESKTOP_HANDOFF/04_DOKUMENTACJA/` — ustalenia, mapa kodu i informacje o paczce źródłowej.

Podglądy zawierają wyłącznie dane przykładowe. Ich zapamiętywanie wyglądu może być ograniczone przez przeglądarkę lub izolację podglądu; docelowy klient ma zapisywać ustawienia lokalnie. Nie wpisuj haseł ani tokenów w makietach.
