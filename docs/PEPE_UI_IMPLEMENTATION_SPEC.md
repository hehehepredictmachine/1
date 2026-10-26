# PEPE MARKET WIZARD
## Master Implementation Specification for Claude Code
### Trading Intelligence + AI Neural Lab + Full Existing-System Integration

**Cel:** rozbudować istniejący projekt Pepe Market Wizard o dwa nowe, w pełni zintegrowane panele, zachowując działający system, modele, API, integrację MT5 i zabezpieczenia. Ten dokument jest instrukcją wykonawczą dla Claude Code, uruchomionego w katalogu głównym repozytorium.

---

# 0. Zasady nadrzędne

Jesteś głównym inżynierem full-stack, architektem oprogramowania, specjalistą integracji AI i projektantem interfejsów do systemu tradingowego.

Budujesz nowe panele w **istniejącym Pepe Market Wizard**, a nie niezależną aplikację. Najpierw poznaj repozytorium, potem wykorzystuj istniejące moduły. Nie zakładaj, że funkcja działa tylko dlatego, że istnieje plik lub klasa.

## Obowiązkowy tryb pracy

1. Pracuj w istniejącym repozytorium i respektuj jego aktualne konwencje.
2. Zacznij od audytu. Przed pierwszą zmianą pokaż plan plików i ryzyka.
3. Zachowaj bieżący interfejs jako działający punkt odniesienia. Nowe widoki dodawaj równolegle pod nowymi trasami.
4. Nie usuwaj ani nie przepisuj działających modeli, API, modułów risk management ani wykonania zleceń bez udokumentowanej konieczności i osobnej akceptacji.
5. Nie resetuj repozytorium, nie używaj destrukcyjnych poleceń git i nie nadpisuj niezapisanej pracy użytkownika.
6. Nie twórz fikcyjnych danych, fikcyjnych wyników AI, pozornych statusów MT5 ani fałszywych endpointów.
7. Brak danych nie oznacza zera. Dane nieaktualne muszą być oznaczone jako stale.
8. Nie wykonuj realnych transakcji podczas developmentu i testów. Testy egzekucji muszą korzystać z mocków lub środowiska DEMO.
9. Po każdym etapie: uruchom adekwatne testy, podsumuj pliki, wyniki, ryzyka i pozostałe problemy, a następnie **zatrzymaj się i poproś o akceptację**.
10. Nie przechodź do kolejnego etapu bez akceptacji użytkownika.
11. Jeśli nie da się czegoś bezpiecznie zintegrować, pokaż dokładnie, czego brakuje, zamiast udawać pełną integrację.
12. Nie ujawniaj sekretów, tokenów, haseł ani danych uwierzytelniających w logach, raportach lub zrzutach ekranu.

# 1. Audyt przed implementacją

Przeprowadź audyt całego repozytorium i zapisz wyniki w `docs/PEPE_UI_AUDIT.md`.

Sprawdź:

- branch, commit, status git i niezapisane zmiany;
- strukturę frontend/backend, wersje runtime i zależności;
- instrukcje uruchomienia, builda, testów i lintowania;
- routing, AppShell, wspólne komponenty, globalny store i obsługę błędów;
- REST API, WebSocket, schematy danych, uwierzytelnianie i autoryzację;
- źródła OHLC, instrumenty, ticki, wolumen, sesje i strefy rynkowe;
- silnik sygnałów, statusy sygnałów, wyniki modeli i konsensus;
- implementacje Random Forest, XGBoost, MLP/neural network, Monte Carlo i innych modeli rzeczywiście obecnych w repo;
- pipeline treningu, walidację, rejestr wersji i deployment;
- MT5 bridge/worker, status połączenia, rachunek DEMO/LIVE, gateway wykonawczy i risk management;
- historię transakcji, pozycje, statystyki, bazę danych i migracje;
- logi, metryki, health checks, testy i sposób odzyskiwania po awarii;
- istniejące komponenty 3D i biblioteki wykresowe;
- potencjalne problemy wydajności, zależności i kompatybilności.

Dla każdego wymagania oznacz stan jako:
- `EXISTS_VERIFIED` — potwierdzone w kodzie i testach;
- `EXISTS_UNVERIFIED` — kod istnieje, ale działanie nie zostało potwierdzone;
- `MISSING` — brak implementacji;
- `BLOCKED` — wymaga decyzji, danych lub infrastruktury.

Nie opisuj funkcji jako gotowej integracji, dopóki nie zostanie wskazany rzeczywisty moduł/API i test potwierdzający działanie.

# 2. Docelowa architektura

Dodaj dwa główne obszary:

1. `Trading Intelligence`
2. `AI Neural Lab`

Dodaj lub rozszerz `System Control Center`, jeśli istniejąca aplikacja nie ma równoważnej funkcjonalności.

Wykorzystuj aktualny router, store, klienta API, WebSocket i wzorce komponentów. Nie twórz drugiego niezależnego store ani drugiego połączenia WebSocket, jeżeli istniejący mechanizm można rozszerzyć.

Wspólny kontekst aplikacji powinien obejmować, zgodnie z istniejącymi możliwościami:
- instrument: `XAUUSD` lub `BTCUSDT`;
- status środowiska: `LIVE`, `DEMO`, `HISTORY` albo nieznany;
- status połączenia MT5;
- świeżość i czas danych;
- aktywny sygnał;
- wybrany interwał;
- status źródeł danych;
- ostrzeżenia systemowe.

Nie wprowadzaj fałszywych statusów. Jeśli backend nie potwierdza stanu, wyświetl `UNKNOWN` lub `DISCONNECTED`.

# 3. Design system i wspólny shell

## Styl

- premium dark terminal;
- tło czarne/grafitowe;
- szmaragdowe akcenty, cienkie obramowania i oszczędne poświaty;
- wysoka czytelność danych i profesjonalna hierarchia;
- subtelne przejścia; efekty 3D nie mogą blokować interakcji;
- stany `loading`, `empty`, `error`, `stale`, `disconnected`, `permission denied`;
- obsługa klawiatury, widoczny focus i kontrast;
- responsywność dla desktopu oraz mniejszych ekranów.

## Nawigacja

Sidebar ma być stały i zwijany. Powinien prowadzić do:
- Trading Intelligence;
- AI Neural Lab;
- System Control Center;
- istniejących widoków, które pozostają aktywne.

Nie usuwaj starych tras. Dodaj nowe trasy zgodnie z konwencją repozytorium, np. `/trading-intelligence` i `/ai-neural-lab`, ale najpierw sprawdź rzeczywisty router.

## Globalny nagłówek

- branding Pepe Market Wizard;
- środowisko LIVE/DEMO/HISTORY;
- status MT5 i szczegóły połączenia;
- status świeżości danych;
- wybór instrumentu;
- powiadomienia i diagnostyka;
- dostęp do ustawień.

---

# 4. Panel Trading Intelligence

## 4.1 Market Overview

Domyślny pulpit: cztery wykresy w układzie 2×2:
- M5;
- M15;
- H1;
- H4.

Globalny wybór instrumentu synchronizuje wszystkie cztery wykresy. Wykorzystaj istniejącą bibliotekę wykresów i istniejący serwis danych, jeżeli spełniają wymagania.

Dostępne warstwy, tylko gdy backend udostępnia rzeczywiste dane:
- świece OHLC;
- wolumen;
- high/low;
- sesje;
- strefy płynności;
- wsparcie/opór;
- poziomy wejścia, SL i TP;
- znaczniki sygnałów;
- metadane czasu i źródła.

Nie obliczaj pozornie „prawdziwych” stref płynności, jeśli źródła nie zawierają danych potrzebnych do ich wyznaczenia. Wyraźnie rozdziel dane obliczone, dane zewnętrzne i elementy koncepcyjne.

## 4.2 Signal Intelligence

Po prawej stronie pulpitów umieść listę sygnałów. Każdy sygnał powinien pokazywać, jeśli dane są dostępne:
- instrument i interwał;
- kierunek i timestamp;
- status;
- argumentację;
- wynik każdego modelu;
- konsensus modeli;
- konflikty modeli;
- ocenę ryzyka;
- cenę wejścia i SL/TP;
- źródło danych i ich świeżość.

Statusy powinny wynikać z istniejącego modelu domenowego. Jeśli nie istnieje, zaproponuj kontrakt i uzgodnij mapowanie przed jego wdrożeniem. Przykładowe stany prezentacyjne: `NEW`, `ANALYZING`, `VALIDATED`, `WARNING`, `REJECTED`, `EXPIRED`, `EXECUTED`, `UNKNOWN`.

Nie przedstawiaj confidence, accuracy ani prawdopodobieństwa jako równoważnych miar. Wyświetlaj źródło, definicję i zakres metryki.

## 4.3 Risk & Performance

Dodaj widoki:
- otwarte pozycje;
- ekspozycja;
- equity/balance;
- drawdown;
- dziennik transakcji;
- ROI i statystyki;
- filtry zakresu dat i instrumentu.

Używaj istniejących źródeł danych. Nie utożsamiaj niezrealizowanego PnL z wynikiem zamkniętym. Zawsze prezentuj walutę, okres i metodę obliczeń, jeśli są dostępne.

## 4.4 Order Preview

Przepływ:
1. Użytkownik wybiera sygnał.
2. Backend waliduje uprawnienia, ryzyko, limity, instrument, wolumen, cenę i SL/TP.
3. UI wyświetla podsumowanie i wynik walidacji.
4. Użytkownik jawnie potwierdza wysłanie.
5. Backend ponownie sprawdza aktualne warunki bezpośrednio przed wykonaniem.
6. UI pokazuje wynik po otrzymaniu potwierdzenia backendu.

Frontend nigdy nie może być jedyną warstwą zabezpieczenia. Nie wysyłaj zlecenia z samego otwarcia podglądu. Nie ponawiaj automatycznie żądania o nieznanym wyniku, dopóki backend nie sprawdzi, czy zlecenie zostało przyjęte. Użyj idempotency key, jeśli backend obsługuje takie rozwiązanie.

---

# 5. Panel AI Neural Lab

## 5.1 Neural Network 3D — ekran domyślny

Styl wizualny inspirowany przesłanym przez użytkownika GIF-em:
- czarne tło;
- organiczne, rozgałęziające się świetliste struktury;
- punkty/węzły połączone cienkimi liniami;
- cząsteczki i animowane impulsy;
- perspektywa 3D, orbit controls, zoom i wybór węzłów;
- regulowana intensywność animacji;
- tryb automatyczny i ręczny;
- pauza/wznowienie;
- redukcja ruchu i ograniczenia wydajności.

Preferowana technologia: Three.js + React Three Fiber, ale najpierw sprawdź obecne zależności i istniejące komponenty. Dodawaj biblioteki dopiero po ocenie kompatybilności, bundle size i wydajności.

Wykorzystaj instancing i ograniczenie liczby renderowanych połączeń dla dużych grafów. Scena musi zwalniać zasoby GPU i event listenery po odmontowaniu.

## 5.2 Każdy model ma własną formę

### Random Forest — Neural Forest
Wizualizuj wiele drzew decyzyjnych. Każde drzewo ma korzeń, węzły podziału, gałęzie i liście. Użytkownik może:
- wybierać poszczególne drzewa;
- eksplorować podziały;
- podświetlić ścieżkę decyzyjną;
- zobaczyć wynik drzewa i udział w agregacji, jeśli model to udostępnia.

Wizualizacja może stylistycznie przypominać sieć neuronową, ale struktura musi odpowiadać prawdziwemu drzewu decyzyjnemu, a nie udawać warstw neuronowych.

### MLP / Neural Network — Neural Constellation
Pokaż warstwy, neurony i połączenia zgodne z rzeczywistą architekturą. Jeśli model udostępnia aktywacje, pokaż je podczas inferencji. Jeśli nie, pokaż tylko strukturę i oznacz brak telemetrii.

### XGBoost — Boosting Cascade
Pokaż sekwencję drzew i ich wkład w predykcję, jeśli dostępne są odpowiednie dane. Umożliw zatrzymanie animacji i eksplorację pojedynczego drzewa.

### Monte Carlo — Probability Nebula
Pokaż rozkład scenariuszy, trajektorie, przedziały i niepewność. Liczba symulacji oraz statystyki muszą pochodzić z rzeczywistego wykonania.

### Inne modele
Decision Tree lub inne modele pokazuj wyłącznie, jeżeli istnieją i zostały zweryfikowane w audycie.

## 5.3 Interakcje 3D

- obrót sceny;
- zoom i przesuwanie;
- wybór węzła, drzewa lub grupy;
- panel szczegółów wybranego elementu;
- tryby `Structure`, `Data Flow`, `Decision Path`;
- intensywność animacji;
- automatyczne i ręczne odtwarzanie;
- zatrzymanie i wznowienie;
- krok po kroku w Replay Mode;
- filtry i izolowanie fragmentów grafu.

Animacje mają odzwierciedlać realną telemetrię, jeśli istnieje. Jeśli jest to tylko dekoracyjna animacja, wyraźnie oznacz ją jako `Illustrative visualization`. Nie sugeruj, że oglądane impulsy są rzeczywistymi aktywacjami.

## 5.4 Metryki i szczegóły

Widok kompaktowy z możliwością rozwinięcia:
- model i wersja;
- stan;
- ostatni trening;
- wynik walidacji;
- metryki i definicje;
- czas inferencji;
- źródło danych;
- liczba przykładów;
- status modelu produkcyjnego.

Nie pokazuj metryk jako zerowych, jeśli są nieznane. Stosuj `N/A`/`Unavailable`.

## 5.5 Training & Deployment

Przepływ:
`Training → Validation → Results Preview → Test Environment → Manual LIVE Approval`.

Automatyczne wdrożenie do środowiska testowego może być włączone wyłącznie wtedy, gdy obecny backend rzeczywiście obsługuje taki proces i testy to potwierdzają. Wdrożenie LIVE wymaga ręcznej akceptacji.

Wersjonuj artefakty. Zapisuj wynik walidacji, parametry, źródło danych, wersję kodu/modelu i wynik wdrożenia. Nie pozwalaj na automatyczne zastąpienie modelu produkcyjnego przez nowy trening. Uwzględnij możliwość rollbacku, jeżeli architektura backendu ją wspiera.

---

# 6. System Control Center

Wymagania zatwierdzone przez użytkownika:

## LIVE
Osobne potwierdzenie aktywacji LIVE z podsumowaniem rachunku, środowiska, statusu MT5, ryzyka i stanu zabezpieczeń. UI nie może samodzielnie nadawać uprawnień, jeśli backend nie potwierdza zmiany.

## MT5
Status połączenia w nagłówku oraz stale widoczny panel szczegółów. Pokazuj stan, ostatni heartbeat, opóźnienie i ostatni błąd, jeżeli dane są dostępne.

## Wdrożenia modeli
Automatyczne wdrożenie do środowiska testowego, ręczna akceptacja dla LIVE. Jeśli pipeline nie obsługuje takiego trybu, najpierw dodaj kontrakt i backendową implementację po osobnej akceptacji.

## Błędy i rozłączenia
Blokuj nowe operacje, oznaczaj dane jako nieaktualne i wymagaj ponownej walidacji po odzyskaniu połączenia. Zachowaj diagnostykę. Nie odblokowuj operacji tylko na podstawie lokalnego stanu UI.

---

# 7. Kontrakty integracyjne

Najpierw zmapuj istniejące kontrakty. Rozszerzaj je kompatybilnie. Nie twórz endpointów „na oko”.

Dla każdego panelu przygotuj tabelę:
- funkcja UI;
- istniejący endpoint/event;
- typ danych;
- właściciel źródła danych;
- status integracji;
- obsługa błędu;
- test integracyjny.

Jeżeli potrzebne są nowe endpointy, zaproponuj kontrakt wraz z:
- metodą i trasą;
- schematem request/response;
- autoryzacją;
- walidacją;
- obsługą timeoutów;
- kodami błędów;
- testami;
- kompatybilnością ze starszym UI.

WebSocket: wykorzystuj istniejące połączenie i mechanizmy reconnect, jeśli są dostępne. Dodaj walidację wiadomości, obsługę braku danych i status stale. Unikaj tworzenia nowego połączenia dla każdego komponentu.

---

# 8. Proponowana organizacja kodu

Dostosuj do realnej struktury repozytorium; poniższa mapa jest propozycją, nie wymogiem zmiany wszystkich ścieżek.

Frontend:
- `features/trading-intelligence/`
  - `pages/`
  - `components/`
  - `hooks/`
  - `services/`
  - `types/`
- `features/ai-neural-lab/`
  - `pages/`
  - `components/`
  - `visualization/`
  - `hooks/`
  - `services/`
  - `types/`
- `features/system-control/`
- wspólne komponenty shell i design system w istniejących lokalizacjach projektu.

Backend:
- najpierw wykorzystaj istniejące serwisy;
- nowe API i serwisy dodawaj wyłącznie, gdy brak funkcjonalności;
- oddziel logikę domenową od warstwy transportowej;
- nie duplikuj MT5 gateway, risk engine ani silników modeli.

Dodaj dokumentację:
- `docs/PEPE_UI_AUDIT.md`
- `docs/PEPE_UI_IMPLEMENTATION_PLAN.md`
- `docs/PEPE_UI_API_MAP.md`
- `docs/PEPE_UI_TEST_PLAN.md`

---

# 9. Plan wdrożenia z bramkami akceptacji

## Etap 0 — Audyt
Tylko analiza i dokumentacja. Nie zmieniaj kodu funkcjonalnego.
**Bramka:** raport i plan do zatwierdzenia.

## Etap 1 — Nowy szkielet aplikacji
Dodaj nowy AppShell/temat, sidebar, header, routing i puste widoki obu paneli. Zachowaj stare trasy.
Nie implementuj jeszcze realnej egzekucji zleceń ani nowych endpointów, jeśli nie są potrzebne dla shell.
**Bramka:** build, lint, testy istniejące i przegląd UI.

## Etap 2 — Trading Intelligence
Podłącz rzeczywiste źródła wykresów i sygnałów, następnie pozycje i statystyki. Dodaj Order Preview, korzystając z istniejących zabezpieczeń backendu.
**Bramka:** testy integracji i scenariusze ryzyka.

## Etap 3 — AI Neural Lab
Dodaj wizualizacje struktur modeli, interakcje 3D, telemetrię i Replay Mode. Najpierw wersja z rzeczywistymi strukturami dostępnych modeli; braki oznaczaj jawnie.
**Bramka:** testy struktury, wydajności, cleanup i zgodności z danymi.

## Etap 4 — System Control Center
Podłącz status MT5, tryby LIVE/DEMO, diagnostykę, bezpieczne odzyskiwanie po błędach i przepływ deploymentu modeli.
**Bramka:** testy backendowe i integracyjne; żadnych realnych zleceń testowych.

## Etap 5 — Regresja i stabilizacja
Przetestuj wszystkie nowe i stare trasy, build produkcyjny, WebSocket, obsługę błędów, responsywność, dostępność oraz wydajność.

Po każdym etapie zatrzymaj się i poproś użytkownika o akceptację.

---

# 10. Wymagane testy

Dostosuj narzędzia do istniejącego projektu. Nie wprowadzaj nowego frameworka testowego bez potrzeby.

## Frontend
- build i typecheck;
- lint;
- testy komponentów;
- routing starych i nowych widoków;
- stan loading/empty/error/stale/disconnected;
- zmiana instrumentu aktualizuje wszystkie cztery wykresy;
- poprawne wyświetlanie nieznanych wartości;
- obsługa reconnect i duplikowanych eventów;
- klawiatura, focus, responsywność;
- cleanup animacji, WebGL i event listenerów.

## Integracja
- kontrakty REST;
- kontrakty WebSocket;
- walidacja payloadów;
- timeouty, błędne odpowiedzi i brak uprawnień;
- zgodność danych i timestampów;
- prawidłowe rozróżnienie LIVE/DEMO/HISTORY;
- brak fikcyjnych wartości w produkcyjnym UI.

## AI Neural Lab
- struktury wizualne zgodne z rzeczywistymi modelami;
- poprawne mapowanie drzew Random Forest i XGBoost;
- brak fałszywych aktywacji;
- Replay Mode nie odtwarza danych przyszłych;
- obsługa braku telemetrii;
- ograniczenia liczby węzłów i stabilność pamięci;
- automatyczne zwalnianie zasobów GPU;
- wyniki treningu i walidacji mają potwierdzone źródło.

## Ryzyko i egzekucja
- UI nie może ominąć backendowej walidacji;
- LIVE wymaga osobnego potwierdzenia;
- utrata MT5 blokuje nowe operacje;
- reconnect wymaga ponownej walidacji;
- niejednoznaczny wynik zlecenia nie powoduje bezwarunkowego ponowienia;
- testy używają mocków/DEMO, nigdy rzeczywistego rachunku LIVE;
- błędy i decyzje są logowane bez sekretów;
- trening nie wdraża modelu LIVE bez zatwierdzenia.

## Regresja
- istniejące trasy i podstawowe funkcje nadal działają;
- niezmienione kontrakty nie ulegają przypadkowej zmianie;
- migracje są kompatybilne i przetestowane;
- stary UI można nadal otworzyć;
- możliwy jest rollback nowej warstwy UI.

---

# 11. Kryteria ukończenia

Panel nie jest ukończony, dopóki:
- korzysta z rzeczywistych źródeł danych albo jawnie wskazuje brak integracji;
- nie pokazuje wymyślonych statusów ani wyników;
- obsługuje błędy, reconnect i nieaktualne dane;
- zachowuje zabezpieczenia backendu;
- ma testy i przechodzi build;
- nie psuje starego UI;
- jego zależności i koszty wydajności są ocenione;
- dokumentacja odzwierciedla rzeczywisty stan implementacji.

Na koniec przygotuj raport:
- wykonane funkcje;
- zmienione pliki;
- integracje potwierdzone;
- integracje niekompletne;
- wyniki komend testowych;
- znane ograniczenia;
- sposób uruchomienia;
- sposób powrotu do poprzedniej wersji.

Nie deklaruj testu jako zaliczonego, jeśli go nie uruchomiłeś.

---

# 12. Pierwsza instrukcja do wykonania teraz

**Rozpocznij wyłącznie Etap 0 — Audyt.**

Przeanalizuj repozytorium, utwórz `docs/PEPE_UI_AUDIT.md`, `docs/PEPE_UI_IMPLEMENTATION_PLAN.md`, `docs/PEPE_UI_API_MAP.md` i `docs/PEPE_UI_TEST_PLAN.md`, o ile ich utworzenie nie nadpisze istniejącej pracy. Jeśli dokumenty już istnieją, przeczytaj je i aktualizuj ostrożnie.

Następnie przedstaw:
1. podsumowanie aktualnej architektury;
2. mapę rzeczywistych modułów do nowych paneli;
3. funkcje gotowe, niezweryfikowane i brakujące;
4. ryzyka oraz wymagane zależności;
5. proponowaną listę plików dla Etapu 1;
6. komendy testowe, które będą użyte.

**Zatrzymaj się i czekaj na akceptację użytkownika. Nie pisz jeszcze kodu funkcjonalnego.**
