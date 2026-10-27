# CLAUDE CODE — PEPEMARKETWIZARD DESKTOP: WDROŻENIE

## Twoje zadanie

Pracujesz w katalogu głównym istniejącego projektu **PepeMarketWizard** dostarczonego w tej paczce. Użytkownik zaakceptował trzy kierunki projektu w `CLAUDE_DESKTOP_HANDOFF/01_WIDOKI/` i zleca Ci wykonanie rzeczywistych zmian w kodzie: uporządkowanie całego systemu, przeniesienie go do aplikacji Windows z własnym oknem i klientem EXE, wdrożenie paneli, wyłączenie Execution Lock oraz uproszczenie nadmiernie blokujących warunków w strategiach.

Najpierw przeczytaj `CLAUDE_DESKTOP_HANDOFF/04_DOKUMENTACJA/01_ZATWIERDZONY_PROJEKT.md`, mapę projektu i instrukcję w katalogu głównym. Obejrzyj trzy podglądy HTML; ich edytowalne fragmenty i grafika Pepe są dołączone. Użyj ich jako wzorca wyglądu i zachowania. **To makiety, nie działający frontend, źródło cen ani potwierdzenie integracji.**

Masz wdrożyć projekt w istniejącym systemie, a nie tylko przedstawić plan. Wykonuj pracę etapowo, zachowuj punkty kontrolne i po każdym etapie podawaj zmienione pliki, wykonane testy i problemy. Użytkownik zaakceptował przedstawione panele i zlecił implementację, więc kontynuuj kolejne odwracalne etapy bez zatrzymywania się wyłącznie po potwierdzenie. Jeśli konkretna decyzja jest niezbędna, a nie da się jej ustalić z projektu, pokaż dostępne warianty; niezależne prace kontynuuj.

**Priorytet aktualnych instrukcji:** użytkownik zdecydował o wyłączeniu Execution Lock. Starsze dokumenty w repozytorium lub wcześniejsze prompty mogą nakazywać jego zachowanie. W tym konflikcie stosuj aktualną decyzję użytkownika; zachowaj pozostałe wymogi, które nie stoją z nią w sprzeczności.

## 1. Zasady pracy i audyt

1. Sprawdź instrukcje repozytorium, aktualny branch, commit oraz niezapisane zmiany, jeżeli repozytorium jest w Git. Jeśli katalog nie jest repozytorium Git, nie twierdź, że masz historię wersji — utwórz bezpieczny punkt powrotu. Nie resetuj repozytorium ani nie nadpisuj cudzych zmian.
2. Przeanalizuj faktyczną wersję backendu, frontendu, konfiguracji, MQL5, buildów, testów, baz, danych, modeli i skryptów. Sprawdź przepływ: **MT5 → świece/ticki → analiza → setup → wybór strategii → ryzyko → tryb → wykonanie → prowadzenie pozycji → statystyki/panel/Telegram**.
3. Dla każdej ważnej funkcji podaj `POTWIERDZONA`, `W_KODZIE_NIEZWERYFIKOWANA`, `BRAKUJE` lub `WYMAGA_DANYCH`. Rozróżnij działające ścieżki decyzyjne, PAPER, SHADOW, prototypy i kod nieuruchamiany. Dokumentacja może opisywać starszą wersję; weryfikuj ją w kodzie.
4. Zmapuj warunki blokujące sygnał i zlecenie, dwa silniki ACTIVE i SCALPING/HEDGING, konfigurację i wszystkie wywołania MT5. Zapisz dowód: plik, funkcja, przyczyna, konsekwencja i test lub sposób jej sprawdzenia. Nie ujawniaj tokenów, haseł ani danych uwierzytelniających.
5. Nie usuwaj modułów, danych, modeli ani funkcji bez udokumentowanej analizy. Duplikaty usuwaj lub scalaj tylko po udowodnieniu równoważności i zachowaniu migracji. Bez danych nie wymyślaj skuteczności, wyników treningu, integracji ani statusów.
6. Nie łącz się z prawdziwym rachunkiem LIVE w celu testów i nie wysyłaj rzeczywistych zleceń testowych. Stosuj mock/symulator; testy na rachunku DEMO przeprowadzaj po uzgodnieniu z użytkownikiem. Nie proś użytkownika o wklejenie hasła, tokenu czy klucza w rozmowie.

Wskazówki do sprawdzenia w bieżącym kodzie: `backend/masterquo/runtime.py`, `mt5/bridge.py`, `mt5/worker.py`, `execution/`, `engine/`, `strategies/`, `risk/`, `sh/`, `api/app.py`, `frontend/src/features/`, `frontend/src/store.tsx`, `frontend/src/api.ts`, `frontend/src/router.ts`, `frontend/src/nc/`, `config/`, `mql5/`, `tests/`. Istniejący `PepeMarketWizard.exe` w paczce jest wcześniejszym launcherem; nie traktuj go jako ukończonej nowej aplikacji desktop.

## 2. Aplikacja Windows i klient EXE

- Zbuduj aplikację dla Windows 10/11 x64 uruchamianą z EXE, która otwiera **własne okno** i własny panel bez konieczności otwierania zwykłej przeglądarki. Istniejący React można osadzić w WebView, jeżeli to najlepiej pasuje do architektury.
- Najpierw porównaj opcje zgodne z rzeczywistymi zależnościami, np. Python + WebView2/pywebview i pakowanie Pythona albo Tauri z lokalnym silnikiem. Wybierz rozwiązanie i uzasadnij je. Nie przepisuj działającego silnika tylko dla zmiany technologii.
- Przygotuj rzeczywiste pliki budowania EXE i instalatora/pakietu: ikony, zasoby, backend i wymagane procesy pomocnicze. Użytkownik nie ma ręcznie instalować Pythona ani Node.js. MT5 pozostaje osobnym wymaganym programem; wyjaśnij wymagania WebView2 i opcjonalnych komponentów treningowych.
- Jasno określ, czy rezultat to jeden plik, czy instalator z EXE i katalogiem. Zadbaj o kompatybilność bibliotek ML oraz rozdzielenie ciężkich, opcjonalnych środowisk treningowych, jeżeli jest potrzebne.
- Silnik uruchamia się i zamyka w kontrolowany sposób; żadnych przypadkowych duplikatów. Obsłuż reconnect, awarię procesu, status i logi. Zamknięcie okna: opcja pracy w tle lub zamknięcia aplikacji. Autostart z Windows ma być wybieralny, a nie włączany po cichu.
- Lokalne API/IPC ma być dostępne tylko lokalnie, zabezpieczone przed przypadkowym użyciem przez inne strony i procesy; nie wystawiaj sterowania w sieci bez decyzji użytkownika. Stosuj ochronę poświadczeń i aktualny mechanizm Windows/DPAPI po weryfikacji kodu. Nie zapisuj tokenów w logach.
- Zaprojektuj bezpieczną migrację ustawień, baz, historii i modeli, kopię danych, aktualizację i rollback. Nie nadpisuj wersji źródłowej użytkownika. Instalacja/migracja nie może niejawnie uruchomić LIVE.
- Zbuduj i sprawdź EXE/instalator na rzeczywistym Windows, jeśli środowisko to umożliwia. Jeśli nie, wykonaj wszystkie możliwe części i przygotuj dokładny skrypt builda oraz instrukcję, ale oznacz EXE i test Windows jako niewykonane. **Nie nazywaj starego launchera nowym EXE.**

## 3. Zatwierdzone panele

Wprowadź wspólną nawigację, globalny wybór XAUUSD/BTC, źródło i czas danych, tryb DEMO/LIVE/PAPER/SIGNALS, status MT5, stany błędów i ustawienia wyglądu. Statusy wynikają z backendu; przy braku danych pokazuj `N/A`, `NIEZNANY` lub `NIEAKTUALNE`. Zachowaj spójną identyfikację Pepe Czarodzieja i uzgodniony ciemny motyw; zapewnij pełną paletę akcentu, tła, panelu i tekstu, wielkość tekstu oraz kontrolę animacji i kontrastu. Zachowaj możliwość włączenia ograniczenia ruchu.

### 3.1 Trading Intelligence

- Uruchom rzeczywiste wykresy świec MT5, domyślnie M5/M15/H1/H4. Układy 1/4/6, zmienny interwał każdego wykresu, powiększanie, tryb skupienia oraz zapisywanie układu i wyglądu. Dołącz M1/M30/D1, gdy dostępne. Przełącznik instrumentu synchronizuje źródło wszystkich wykresów.
- Pokaż setupy/kierunki, status, warunki spełnione i brakujące, trigger, unieważnienie, uzasadnienie, ewentualne konflikty modeli, wejście/SL/TP i czas. Wyniki modeli pokazuj tylko z prawdziwych źródeł. Oddziel **powód braku sygnału** od **powodu niewysłania zlecenia**.
- Pokaż bilans, equity, wynik otwartych i zamkniętych pozycji, ROI oraz win rate ze sprawdzonym źródłem i okresem. Nie traktuj nieznanej wartości jako zera ani heurystycznej oceny jako prawdopodobieństwa.
- Zapewnij podgląd planu i możliwość wygodnego wyboru setupu. Samo otwarcie podglądu nie wysyła zlecenia. Ręczne zlecenie wymaga jawnego potwierdzenia i walidacji backendu; automatyczne zlecenia działają wyłącznie w świadomie wybranym trybie.

### 3.2 AI Neural Lab

- Zrealizuj widoki **Neural Universe, Trening, Walidacja, Wdrożenia** zgodne z makietą. Wizualizacje MLP, Random Forest, XGBoost i Monte Carlo mają odrębne kształty oraz wybór elementów, obrót, zoom, pauzę, przepływ i replay. Modele rzeczywiście dostępne ustal na podstawie kodu i artefaktów.
- Jeśli rzeczywista struktura lub telemetria nie jest dostępna, oznacz widok jako **ilustracyjny**. Nie pokazuj animacji jako faktycznych aktywacji, nie wymyślaj metryk, wersji ani dat treningu. Gdy dostępne są prawdziwe drzewa/sieci, kształt i ścieżka muszą odpowiadać danym modelu.
- Obsłuż trening na danych użytkownika, podział chronologiczny, walidację poza próbą, wersjonowanie, porównanie i rollback tam, gdzie istnieją możliwości backendu. Uruchomienie treningu nie może automatycznie podmienić modelu LIVE. Replay bez danych z przyszłości.

### 3.3 System Control Center

- Zapewnij przegląd stanu silnika, MT5, rachunku, aktualności danych i konfiguracji; szczegóły połączenia, `terminal64.exe`, symbole, koszty, diagnostykę, ryzyko, powiadomienia Telegram oraz preferencje pracy w tle/autostartu.
- Zapewnij świadomy wybór `SIGNALS`, `PAPER`, `AUTO_DEMO`, `AUTO_LIVE` z jednoznacznym rachunkiem i podsumowaniem przed pierwszym uruchomieniem LIVE. Nie zmieniaj typu rachunku po stronie brokera. Dźwignię i typ hedging/netting odczytuj z MT5.
- STOP użytkownika zatrzymuje **nowe wejścia**. Zarządzanie istniejącymi pozycjami i zamykanie ryzyka działają zgodnie z wybranym projektem, dostępnym MT5 i warunkami brokera; po rozłączeniu pokaż rzeczywisty status. Nie twórz drugiej blokady wykonania pod inną nazwą.

## 4. Execution Lock — wyłączyć zgodnie z decyzją użytkownika

Wykonaj pełne wyszukanie i przegląd, a następnie zmień kod, konfigurację, migrację, API, panel i testy. Sprawdź szczególnie `config.py`, `runtime.py`, `mt5/worker.py` (`_LockedTerminal` / `lock_fn`), `execution/gateway.py`, `execution/manager.py`, `execution/manual.py`, `execution/modes.py`, `sh/executor.py`, `sh/service.py`, `api/app.py` oraz komponenty frontendu i testy.

- Stan starego `execution.lock=LOCKED` po migracji **nie może blokować** `order_send`, modyfikacji i zamykania pozycji przez żadne wejście systemu. Usuń lub wycofaj wpływ Execution Lock spójnie, bez zachowania go jako ukrytej nowej blokady i bez osobnej frazy odblokowującej.
- Zachowaj sens wybranego trybu, jawny STOP nowych wejść, uprawnienia/warunki brokera, kontrolę poprawności danych oraz limity ustawione przez użytkownika. Nowa instalacja startuje w PAPER albo SIGNALS; nie aktywuj po cichu LIVE. Pierwszy wybór rzeczywistego AUTO LIVE ma być świadomy i powiązany z rachunkiem, ale **nie może być powtarzanym odblokowaniem Execution Lock przy każdym starcie**.
- `order_send`, zamknięcia, częściowe zamknięcia i modyfikacje muszą przechodzić przez właściwe wspólne kontrakty/gateway. Zapobiegaj ponownemu wysłaniu zlecenia o nieznanym wyniku: najpierw sprawdź stan brokera, idempotency i pojedynczą własność pozycji. Nie obchodź samego worker/serializacji MT5.
- Sprawdź istniejącą bezwarunkową odmowę AUTO LIVE ścieżki SH. Przebuduj ją świadomie w ramach uzgodnionego trybu, prawidłowego rachunku, rzeczywistej walidacji ścieżki i testów DEMO/mock. Jeśli nie możesz bezpiecznie ukończyć obsługi, opisz dokładnie brakujące elementy i nie przedstawiaj LIVE jako gotowego. Nie ukrywaj odmowy i nie sugeruj wyłączenia wszelkiego zarządzania ryzykiem.
- Test na mocku musi potwierdzać zarówno brak wpływu starego locka, jak i poprawność trybu, STOP oraz możliwości zarządzania otwartą pozycją. Nigdy nie przeprowadzaj tego testu na prawdziwym rachunku.

## 5. Strategie — ograniczyć zbędne blokowanie

Zrób inwentaryzację warunków obu ścieżek ACTIVE/S01–S12 i SCALPING/HEDGING: wymagane dane, progi, VETO, wybór ścieżki głównej, limity, koszty, blokady modeli i konflikty. Pokaż, które warunki generują `WAIT`, które obniżają ocenę, a które uniemożliwiają zlecenie. Nie wymyślaj częstości bez danych.

- Usuń powtórzone, sprzeczne lub nieuzasadnione globalne bramki. Brak klucza AI, niewytrenowanego modelu lub opcjonalnego wskaźnika powinien obniżać kompletność analizy i być widoczny; sam w sobie nie ma domyślnie blokować całej analizy i wszystkich zleceń.
- Zachowaj podstawowe warunki wybranego setupu i rzeczywiste wymagania wykonania: tryb i prawidłowy rachunek, dostępność handlu u brokera, aktualną cenę, prawidłowy symbol/wolumen/poziomy, STOP oraz ryzyko ustawione przez użytkownika. Pokazuj wszystkie powody jasno, bez ukrytych filtrów. Analiza i sygnał nie są tym samym co realizacja.
- Sprawdź i uporządkuj mechanizm wyboru głównej ścieżki, tak aby nie powodował niezrozumiałej utraty okazji. Koordynuj łączną ekspozycję i własność pozycji wszystkich silników, z uwzględnieniem kont NETTING/HEDGING, bez niejawnego otwierania sprzecznych lub zduplikowanych pozycji.
- Scalping XAUUSD: uwzględnij wcześniej podane poziomy zmiany ceny 2,5 / 3 / 5 USD oraz break-even po potwierdzeniu TP2, z zarządzaniem częściami i wymaganiami wolumenu brokera. **Ruch ceny nie jest zyskiem rachunku**: pokaż kontrakt, lot, walutę, koszty i metodę obliczeń. Nie kopiuj tych wartości automatycznie na BTC.
- Odczytuj rzeczywisty Bid/Ask, spread, prowizję i poślizg. Profil rachunku Zero nie dowodzi, że wszystkie koszty wynoszą zero. Użytkownik używa `XAUUSD-`; BTC wybierz po weryfikacji metadanych symbolu brokera, bez zgadywania.
- Porównaj przed/po na tym samym okresie i instrumentach: liczbę setupów, przyczyny odrzuceń, liczbę transakcji, net P/L po kosztach, drawdown i wyniki poza próbką. Uwzględnij spread, prowizję, poślizg, brak danych, sesje i rodzaj rachunku. Nie optymalizuj pod liczbę sygnałów lub jeden historyczny zakres; nie obiecuj rentowności.

## 6. Integracja danych, modeli i powiadomień

Głównym źródłem świec i ceny jest MT5 bridge — **bez screenshotów**. Praca wielointerwałowa ma używać rzeczywistych danych terminala, timestamps i statusu świeżości. TradingView może pełnić funkcję pomocniczą, jeśli jest faktycznie dostępne.

Utrzymaj mapę `ekran → komponent → istniejące API/event → schemat → źródło → obsługa błędu → test`. Rozszerzaj istniejące API, store i WebSocket zgodnie z kodem, zamiast tworzyć równoległe silniki. Dla XAUUSD i BTC uczciwie pokaż, które strategie i modele faktycznie działają oraz które są tylko SHADOW lub niewytrenowane. Nie przenoś modelu do decyzji LIVE bez walidacji i wyboru użytkownika.

W konfiguratorze Telegram użytkownik może bezpiecznie podać token i identyfikator kanału, a powiadomienia o otwarciu/zamknięciu i statystyki korzystają z rzeczywistego MT5. Jeśli wcześniejsza implementacja Telegrama jest poza tą paczką, oznacz brak, zaproponuj i zaimplementuj zgodny adapter w zakresie możliwym do sprawdzenia; nie udawaj działającego połączenia. Jeżeli wykorzystywane są dwujęzyczne powiadomienia, zachowaj angielski + chiński uproszczony.

## 7. Kolejność realizacji i kontrola jakości

1. Audyt i bezpieczny punkt powrotu; mapa zależności, warunków i rzeczywistego stanu paneli.
2. Architektura desktop, procesy i instalator; zapewnienie działania istniejącego silnika i zachowania danych.
3. Wspólny wygląd i nawigacja; Trading Intelligence; AI Neural Lab; System Control Center, kolejno z prawdziwymi źródłami.
4. Spójne wycofanie Execution Lock i dostosowanie starych konfiguracji/testów; STOP i tryby pozostają poprawne.
5. Refaktoryzacja strategii, koordynacja ścieżek, diagnostyka przyczyn, walidacja historyczna i koszty.
6. Testy całego przepływu, Windows build/instalator, migracja, instrukcja i raport.

Uruchom testy odpowiednie do zmian i nie pisz, że coś zostało przetestowane, jeśli tego nie uruchomiono. Obowiązkowe scenariusze: stara konfiguracja `LOCKED`; PAPER i SIGNALS bez wysyłki do MT5; poprawne konta DEMO/LIVE na mockach; STOP tylko nowych wejść; modyfikacja/zamknięcie istniejącej pozycji; rozłączenie i reconnect; niejednoznaczne wyniki wysyłki i duplikaty; hedging/netting; brak modelu/klucza AI; poprawne komunikaty przyczyn; XAUUSD-/mapowanie BTC; rozliczenie kosztów; regresja starego UI i API; przełączanie instrumentów i interwałów; puste/nieaktualne dane; responsywność/klawiatura; ustawienia wyglądu; instalacja, migracja, backup i rollback.

Dla modeli sprawdź brak wycieku danych z przyszłości, pochodzenie metryk i artefaktów oraz zgodność wizualizacji z faktyczną strukturą. Dla GUI: czytelność 100–200% skalowania, wolniejsze komputery, zamykanie procesów i brak wycieku zasobów. Nie twórz fałszywych placeholderów jako danych produkcyjnych.

## 8. Raport końcowy dla użytkownika

Po wykonaniu podaj po polsku:

1. co rzeczywiście działa i które pliki zmieniono;
2. jak zmieniono Execution Lock, tryby, STOP oraz najważniejsze filtry strategii;
3. jak podłączyć MT5 i Telegram, uruchomić klienta EXE oraz trenować modele;
4. wyniki faktycznie wykonanych testów, wyniki porównania strategii oraz ograniczenia;
5. co wymaga Windows, zalogowanego MT5, danych brokera, testowego rachunku lub dodatkowej decyzji;
6. lokalizację nowego EXE/instalatora, tylko jeśli faktycznie powstał, oraz instrukcję rollbacku.

Rozpocznij od audytu i punktu powrotu, następnie wykonuj kolejne uzgodnione etapy. Nie kończ pracy po samym opisie planu, jeśli masz możliwość bezpiecznie zaimplementować i sprawdzić dalsze zmiany.
