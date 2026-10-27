# PEPE MARKET WIZARD — COMPLETE CLAUDE CODE INTEGRATION PROMPT

## Cel
W istniejącym repozytorium Pepe Market Wizard zaimplementuj i w pełni zintegruj dwa nowe panele:
1. **Trading Intelligence** — wykresy, sygnały, modele, ryzyko, pozycje, wyniki i podgląd zleceń.
2. **AI Neural Lab** — interaktywne wizualizacje 3D modeli, metryki, inferencja, replay, trening, walidacja i wdrożenia.
3. Wspólny **System Control Center** — MT5, LIVE/DEMO, diagnostyka, stan danych i kontrola wdrożeń.

To jest zadanie implementacyjne, nie tylko projekt makiety. Pracuj w istniejącej aplikacji, wykorzystując jej backend, modele, REST, WebSocket, bazę danych i integrację MT5. Nie twórz drugiej aplikacji ani duplikatów silników.

## Bezwzględne zasady
- Najpierw audytuj faktyczne repozytorium; nie zgaduj nazw plików, endpointów ani możliwości modułów.
- Zachowaj stary UI jako działający punkt odniesienia. Dodawaj nowe trasy równolegle.
- Nie resetuj repozytorium i nie nadpisuj niezapisanej pracy.
- Wykorzystuj istniejący router, store, klienta API, WebSocket, wykresy, backend, bazę i silniki AI.
- Nie twórz fikcyjnych danych, wyników modeli, metryk treningowych ani statusów MT5. Brak danych oznaczaj `N/A`/`UNKNOWN`; stare dane oznaczaj jako `STALE`.
- Frontend nie może omijać backendowego risk management, Execution Lock ani walidacji zleceń.
- Nie wykonuj rzeczywistych transakcji w trakcie implementacji i testów. Egzekucję testuj na mockach lub DEMO.
- Po każdym etapie uruchom dostępne testy, przedstaw zmienione pliki i wyniki, po czym zatrzymaj się po akceptację użytkownika. Nie kontynuuj bez zgody.
- Jeśli funkcja nie istnieje, opisz brak i zaproponuj minimalną implementację kompatybilną z architekturą. Nie udawaj integracji.

## Etap 0 — audyt przed zmianami
Sprawdź:
- branch, commit, niezapisane zmiany i możliwość rollbacku;
- frontend, backend, zależności, build, lint i testy;
- router, AppShell, globalny store, komponenty i style;
- REST, WebSocket, schematy danych, uwierzytelnianie i autoryzację;
- źródła OHLC, wolumenu, instrumentów, sesji, sygnałów i pozycji;
- rzeczywiście zaimplementowane modele, ich wersje, inferencję i telemetrię;
- trening, walidację, rejestr modeli i deployment;
- MT5 bridge/worker, execution gateway, risk engine i stan LIVE/DEMO;
- bazę danych, migracje, logowanie i diagnostykę;
- istniejące biblioteki wykresów i 3D.

Dla każdej funkcji użyj statusu: `EXISTS_VERIFIED`, `EXISTS_UNVERIFIED`, `MISSING`, `BLOCKED`.

Przygotuj dokumenty:
- `docs/PEPE_UI_AUDIT.md`
- `docs/PEPE_UI_API_MAP.md`
- `docs/PEPE_UI_IMPLEMENTATION_PLAN.md`
- `docs/PEPE_UI_TEST_PLAN.md`

Nie zmieniaj jeszcze kodu funkcjonalnego. Pokaż raport, proponowane pliki Etapu 1 i testy, a następnie zatrzymaj się po akceptację.

## Etap 1 — nowy szkielet i system wizualny
Po akceptacji audytu:
- dodaj nowy AppShell, zwijany sidebar, globalny header i routing;
- dodaj puste, ale poprawnie zbudowane widoki obu paneli;
- zachowaj wszystkie istniejące trasy;
- przygotuj wspólne stany loading, empty, error, stale i disconnected;
- zastosuj responsywny premium dark terminal: czerń/grafit, szmaragdowe akcenty, czytelne typografie, subtelne obramowania;
- izoluj style nowych ekranów, nie psuj starego UI.

Header pokazuje status `LIVE`/`DEMO`/`HISTORY`/`UNKNOWN`, stan MT5, świeżość danych, globalny wybór instrumentu `XAUUSD`/`BTCUSDT` i diagnostykę. Status musi pochodzić z backendu, nie ze stałej w UI.

Po etapie uruchom build, typecheck, lint i dostępne testy. Zatrzymaj się po akceptację.

## Etap 2 — Trading Intelligence
### Market Overview
Cztery wykresy w układzie 2×2: M5, M15, H1, H4. Globalny wybór instrumentu synchronizuje wszystkie cztery. Wykorzystaj istniejący komponent wykresowy i prawdziwe źródła danych.

Pokaż tylko dane, które istnieją: OHLC, wolumen, high/low, sesje, strefy, sygnały, entry, SL i TP. Dodaj timestamp i świeżość. Nie wymyślaj wolumenu ani stref płynności.

### Signal Intelligence
Lista sygnałów po prawej stronie. Gdy dane są dostępne, pokaż instrument, interwał, kierunek, czas, status, argumentację, wyniki poszczególnych modeli, konsensus, konflikty, ocenę ryzyka, entry/SL/TP i źródło danych. Dopasuj statusy do rzeczywistych typów backendu. Nie utożsamiaj confidence, accuracy i probability.

### Performance & Journal
Pozycje, ekspozycja, equity/balance, drawdown, PnL, historia, dziennik, ROI i filtry dat/instrumentów. Rozdziel PnL zamknięty od niezrealizowanego. Każda metryka musi mieć wiarygodne źródło.

### Order Preview
Przepływ: wybór sygnału → backendowa walidacja → podsumowanie → jawne potwierdzenie użytkownika → ponowna walidacja backendu → wynik potwierdzony przez backend. Samo otwarcie preview nie wysyła zlecenia. Po timeout nie ponawiaj ślepo żądania; najpierw sprawdź status. Użyj idempotency key, jeśli obsługiwany. Nigdy nie obchodź istniejących zabezpieczeń.

## Etap 3 — AI Neural Lab
### Neural Universe 3D
Styl na podstawie GIF-a użytkownika: czarne tło, organiczne świetliste gałęzie, węzły, cienkie połączenia, cząsteczki i impulsy, przestrzeń 3D, orbit/zoom, wybór elementów, regulowana intensywność oraz tryb automatyczny/ręczny.

Najpierw sprawdź istniejący stack. Preferuj Three.js + React Three Fiber, jeśli są kompatybilne i uzasadnione. Użyj instancing/LOD dla dużych grafów. Zwalniaj zasoby GPU, animacje i event listenery po odmontowaniu.

### Osobne kształty modeli
- **Random Forest — Neural Forest:** wiele drzew decyzyjnych z korzeniem, rozgałęzieniami i liśćmi. Użytkownik może wybrać drzewo, obejrzeć podziały i ścieżkę decyzji. Kształt ma estetykę sieci neuronowej, ale odwzorowuje prawdziwe drzewa.
- **MLP / Neural Network — Neural Constellation:** warstwy i połączenia zgodne z architekturą modelu. Aktywacje tylko, gdy dostępna jest telemetria.
- **XGBoost — Boosting Cascade:** sekwencja drzew i wkład etapów, jeśli model udostępnia te dane.
- **Monte Carlo — Probability Nebula:** trajektorie, rozkłady i niepewność z prawdziwych symulacji.
- Inne modele pokazuj tylko, jeśli audyt potwierdzi ich implementację.

Dodaj tryby Structure, Data Flow i Decision Path; wybór węzła/drzewa; panel szczegółów; pauzę; replay krok po kroku; intensywność animacji. Wyraźnie oznacz wizualizacje ilustracyjne. Nigdy nie udawaj, że animacja jest realną aktywacją modelu. Replay nie może używać danych przyszłych.

### Metryki, trening i wdrożenia
Widok kompaktowy z rozwijanymi szczegółami: wersja, status, czas treningu, walidacja, metryki, inferencja, liczba próbek i źródło. Brak danych to `N/A`.

Workflow: `Training → Validation → Results Preview → Test Environment → Manual LIVE Approval`. Automatyczne wdrożenie do testów tylko, jeśli backend obsługuje ten proces. Wdrożenie LIVE zawsze wymaga ręcznej akceptacji. Zapisuj wersję, parametry, wyniki walidacji i status wdrożenia. Zapewnij rollback, jeśli wspiera go architektura.

## Etap 4 — System Control Center
Ustawienia zatwierdzone przez użytkownika:
- LIVE: osobne potwierdzenie z podsumowaniem rachunku, środowiska, MT5, ryzyka i zabezpieczeń;
- MT5: status w headerze oraz stale widoczny panel szczegółów;
- modele: automatyczne wdrożenie do testów, ręczna akceptacja LIVE;
- błędy/rozłączenia: blokada nowych operacji, oznaczenie danych jako stale, diagnostyka i ponowna walidacja po reconnect.

Backend jest źródłem prawdy dla trybu, uprawnień i ryzyka. Nie odblokowuj operacji na podstawie samego stanu frontendowego.

## Pełna integracja
Utrzymuj mapę dla każdej funkcji: komponent UI → istniejący moduł → endpoint/event → schemat danych → źródło prawdy → autoryzacja → obsługa błędów → test → status integracji.

Rozszerzaj istniejące API kompatybilnie. Nowe endpointy dodawaj tylko, jeśli brak odpowiedniej funkcji; dokumentuj request/response, walidację, uprawnienia i błędy. Wykorzystuj istniejące połączenie WebSocket i store, jeśli są dostępne. Obsłuż reconnect, duplikaty, opóźnione zdarzenia i stale data. Logika domenowa i zabezpieczenia pozostają w backendzie.

## Etap 5 — testy końcowe
Dostosuj polecenia do repozytorium i podawaj tylko faktycznie wykonane wyniki.

Wymagane obszary:
- build, typecheck, lint, testy frontendowe/backendowe;
- stare i nowe trasy;
- globalna zmiana instrumentu na czterech wykresach;
- loading/empty/error/stale/disconnected;
- REST/WebSocket, timeout, reconnect, brak uprawnień;
- poprawne timestampy i źródła danych;
- struktura RF/XGBoost zgodna z rzeczywistymi drzewami;
- brak fikcyjnych aktywacji i metryk;
- replay bez przyszłych danych;
- cleanup WebGL i kontrola wydajności;
- backendowa walidacja zleceń, potwierdzenie LIVE, disconnect i rewalidacja;
- brak ślepego ponawiania zleceń;
- regresja starego UI i rollback.

## Definition of Done
Panel jest gotowy dopiero, gdy ma rzeczywistą integrację lub jawnie oznaczone braki, wiarygodne źródła danych, obsługę błędów, zachowane zabezpieczenia, testy i build bez błędów oraz nie psuje starego UI.

Po każdym etapie raportuj: funkcje, zmienione pliki, potwierdzone/brakujące integracje, testy i ich wyniki, ryzyka, instrukcję uruchomienia i rollback.

## Polecenie startowe
Rozpocznij teraz od Etapu 0. Przeprowadź audyt i utwórz/uzupełnij cztery dokumenty audytowe. Nie pisz jeszcze kodu funkcjonalnego. Przedstaw raport oraz listę zmian Etapu 1 i zatrzymaj się, czekając na akceptację. Po akceptacji implementuj Etap 1, testuj i znów zatrzymaj się. Kontynuuj wyłącznie po akceptacji każdego etapu.
