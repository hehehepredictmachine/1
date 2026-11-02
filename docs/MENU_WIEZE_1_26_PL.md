# PepeMarketWizard 1.26 – menu główne „trzy wieże” i widoki Precision / Dyscypline / Profits

Wersja: **1.26.0**. Ten dokument realizuje specyfikację „PEPEMARKETWIZARD — NEURO MAGIC CYBERPUNK”. Zawiera:
- architekturę i konfigurację zasobów;
- instrukcję uruchomienia;
- wykonane kontrole (z wynikami uruchomień);
- zrzuty działających widoków;
- listę rzeczywistych luk integracji.

## 1. Audyt punktu wyjścia (co było i z czym się łączy)

| Obszar | Stan przed 1.26 | Jak nowe menu z tego korzysta |
|---|---|---|
| Routing | hash (`#/strona?param=…`), `router.ts`, ostatnia strona w `localStorage` | nowe strony `menu`, `precision`, `dyscypline`, `profits`; pierwszy start = `#/menu`; Back / Forward / odświeżenie działają jak dotąd |
| Stan i dane na żywo | jeden `LiveSocket` (`/api/v1/ws`) w `store.tsx` – kwotowania, świece, decyzje, konto, tryb, SH, sygnały | bez drugiego połączenia: mapy boczne dostają te same zdarzenia przez szynę `telemetry.ts` (podpięta w `store.tsx`) |
| Dane MT5 | wyłącznie terminal użytkownika (MarketBridge); symulator `--demo` oznaczony `SYNTHETIC` | widoki pokazują źródło („symulator terminala” / rachunek DEMO / REAL) i czas ostatniej aktualizacji |
| Rejestr modeli | `GET /api/v1/sh/models` (rejestr SH: modele, role w SCALPING/HEDGING, status treningu) | prawa mapa: węzły = wiersze rejestru, krawędzie = rzeczywisty udział w strategii |
| Dane rachunku i wyniki | `GET /api/v1/stats` (konto MT5, ROI zmodyfikowaną metodą Dietza, statystyki silników/strategii), krzywa equity | widok Profits |
| Ryzyko / tryb | tryby SIGNALS / PAPER / AUTO DEMO / AUTO LIVE, STOP nowych wejść, ścieżka główna, limity użytkownika, bramki backendu | pasek ryzyka w Dyscypline (tylko odczyt) |
| Execution Lock | **wycofany w 1.24 na Twoją decyzję** | nie przywrócony i nie zastąpiony ukrytą blokadą – pasek pisze to wprost (patrz „Luki”) |

## 2. Co powstało

### Menu główne (`#/menu`)
- **Logo** Pepe-czarodziej w runicznym medalionie (lewy górny róg). Kliknięcie zawsze wraca do menu.
- **Górny pasek** (dane z aplikacji): zakładki Precision / Dyscypline / Profits, przełącznik instrumentu, stan MT5, świeżość danych,
  tryb bota z rodzajem rachunku. Na symulatorze pasek pisze „SYMULATOR (dane syntetyczne)”. **„LIVE” nie pojawia się nigdy na danych
  demonstracyjnych ani nieaktualnych.** Rachunek REAL ma etykietę „RACHUNEK REAL” tylko wtedy, gdy terminal to potwierdził.
- **Tło:** wieża z fioletowymi błyskawicami (załącznik `8c995888….gif`), kadrowana bez deformacji.
  - Warstwa renderowana na żywo nad obrazem: parallax za kursorem, mgła, pył, proceduralne błyskawice z rozbłyskiem, światło kursora
    w kolorze wskazanej wieży.
  - Przy wskazaniu wieży zmienia się poświata, przy przejściu – nastrój.
  - Statyczny fallback, gdy ograniczono animacje.
  - Warstwy dekoracyjne mają `pointer-events: none`: nigdy nie przejmują kliknięć.
- **Trzy wieże 3D (three.js, geometria proceduralna):**

  | Wieża | Rola | Kolory | Bryła |
  |---|---|---|---|
  | **Precision** | wykresy | cyjan i chłodny fiolet | smukłe obserwatorium z kryształem i obracającymi się pierścieniami pomiarowymi |
  | **Dyscypline** | setupy i sygnały | ametyst i szmaragd | masywna cytadela z runami i bramą energii (shader portalu) |
  | **Profits** | wyniki i historia | złoto i szmaragd | wieża-skarbiec z kulą energii, złotymi detalami i orbitującymi cząstkami (instancing) |

  - Wspólna platforma z magicznym kręgiem.
  - Etykiety to przyciski HTML (dostępne z klawiatury i czytników ekranu), zakotwiczone w rzucie wieży.
  - Interakcje:
    - wskazanie: poświata, przybliżenie, runy;
    - fokus klawiatury i strzałki ←/→;
    - Enter / klik / dotknięcie: ruch kamery i portal (~0,56 s), potem widok wieży;
    - krótki opis pod sceną.
  - **Kliknięcie wieży wyłącznie nawiguje** – test potwierdza brak żądań zleceń i niezmieniony tryb.
- **Boczne „mapy przepływu modeli”:**
  - lewa – dane i analizy: terminal MT5 → kwotowania / zegar / rachunek / świece 7 interwałów → jakość danych → 10 modułów analiz → rdzeń;
  - prawa – modele, agregacja i decyzje: modele z rejestru → SCALPING / HEDGING oraz węzły drzewa decyzji silnika S01–S12 → rdzeń „Decyzje”.

  Warstwy i interakcje:
  - warstwa dekoracyjna (pył, obrót, rdzeń-oko) jest oddzielona od warstwy telemetrii;
  - **impulsy biegną tylko po rzeczywistym zdarzeniu z WebSocket** (np. zamknięta świeca M5 → impuls MT5 → M5 → jakość danych);
  - kolor = stan: aktywny / oczekujący / błąd / nieaktywny-niewytrenowany / offline;
  - offline (brak łącza z botem): brak impulsów, szare węzły, napis OFFLINE;
  - tooltip pokazuje nazwę, stan, opis i ostatnią pracę;
  - kliknięcie lub „Lista modułów” otwiera szczegóły z metrykami;
  - przeciągnięcie obraca, kółko przybliża;
  - filtry: wszystkie / aktywne / błędy-offline / SCALPING / HEDGING / S01–S12.

### Widok Precision (`#/precision`) – tło: obserwatorium, nocne niebo, cyjan
- Wykresy świecowe z MT5: istniejące `MarketCharts` / `ChartPanel` (świece z `/api/v1/candles` i bary na żywo z jedynego WebSocket).
  - wybór interwału, jeden wykres albo siatka;
  - zoom, przesuwanie, krzyż celowniczy;
  - przycisk „Warstwy analizy”: strefy H/L, FVG/OB, BOS/CHoCH, walls, sesje, SAR, RSI/MACD.
- Panel boczny:
  - notowanie (Bid / Ask / spread / wiek);
  - reżim rynku per interwał (z silnika, zamknięte świece);
  - stan mapy stref: najbliższe wsparcie i opór jako tekst; konfluencja to ocena, nie prawdopodobieństwo.
- XAUUSD i BTC – symbole brokera z rejestru aktywów; przełącznik w górnym pasku.

### Widok Dyscypline (`#/dyscypline`) – tło: wnętrze cytadeli, portal, fiolet i szmaragd
- Lista setupów i sygnałów z czterech źródeł: aktualny setup silnika, ranking kandydatów AUTO, SCALPING / HEDGING z serwisu SH,
  sygnały bota ze wszystkich rynków. Dla każdego: instrument, strategia, interwał, BUY/SELL albo brak.
- Stany i filtry według stanów backendu:

  | Stan UI | Znaczenie |
  |---|---|
  | obserwacja | setup obserwowany |
  | setup formujący się | warunki jeszcze się zbierają |
  | setup gotowy | warunki spełnione, czeka na wejście |
  | sygnał aktywny | jest sygnał wejścia |
  | setup unieważniony | setup przestał obowiązywać |
  | wygasły | minął czas ważności |
  | zakończony | zamknięty (tylko sygnały bota z wynikiem) |

- Szczegóły (klik; wybór zapisany w adresie `?setup=…`, więc odświeżenie i Back działają):
  - czas powstania i świeżość, ważność („za X min” / „X min temu”);
  - wejście / SL / TP, trigger, unieważnienie;
  - lista warunków spełnionych i brakujących;
  - uzasadnienie i potwierdzenia, przeciwwskazania;
  - **sprzeczności między modelami**;
  - ryzyko (bramka, zgoda na wykonanie, brakujące limity);
  - wykres interwału setupu.
- **„Ocena setupu” to heurystyka 0–100 – nigdy nie jest pokazywana jako prawdopodobieństwo.** Prawdopodobieństwo pojawia się
  wyłącznie, gdy model ML ma status kalibracji `CALIBRATED`. W przeciwnym razie: „brak skalibrowanego modelu – nie pokazuję”.
- Pasek ryzyka: tryb, nowe wejścia (aktywne / STOP), ścieżka główna, stan Execution Lock, link do Centrum sterowania.
  **Widok niczego nie zleca**; ręczne akcje są w dotychczasowych widokach planu (z potwierdzeniem i ponowną kontrolą w backendzie).

### Widok Profits (`#/profits`) – tło: skarbiec, szmaragdowe kryształy, złote światło
- Rachunek i wyniki:
  - saldo i equity z MT5;
  - wynik otwartych pozycji, zrealizowany wynik netto bota;
  - ROI rachunku z okresem i metodą (zmodyfikowany Dietz);
  - win rate z W / L / BE;
  - prowizje i swapy.
- Wpłaty i wypłaty są pokazane osobno, z dopiskiem **„nie są zyskiem”**.
- Obsunięcie – tylko z krzywej zrealizowanych wyników albo zapisanych snapshotów equity, **nigdy z samego bieżącego salda**.
- Deale MT5 a transakcje: liczba deali, zamkniętych transakcji, częściowo zamkniętych i nierozliczonych – osobno.
- Krzywa kapitału (equity + saldo), historia transakcji bota.
- Porównania:
  - ścieżki wykonania (silnik S01–S12 / SCALPING / HEDGING);
  - strategie, instrumenty (nowe `per_symbol`), miesiące.
- Przełącznik PAPER / AUTO DEMO / AUTO LIVE wybiera **zakres statystyk**, nie tryb handlu. Filtr okresu.
- Brak danych jest napisany wprost („brak danych”, „Brak zamkniętych transakcji…”).

## 3. Konfiguracja zasobów (plik → przeznaczenie)
Jedno miejsce: `frontend/src/features/wizard/assets.ts` (`WIZARD_ASSETS`, `TOWERS`). Pliki: `frontend/public/assets/wizard/`.
Budowane skryptem `tools/wizard_assets.py`:
- kadrowanie bez deformacji;
- korekta barwna;
- WebP q84;
- tło Profits renderowane z `tools/wizard_backgrounds/profits_vault.html`.

| Plik | Przeznaczenie | Pochodzenie |
|---|---|---|
| `menu-tower-lightning.webp` | tło menu głównego | załącznik `8c995888….gif` (dostarczony jako jedna klatka) – animację dodaje warstwa na żywo |
| `menu-tower-lightning-source.webp` | statyczny fallback / oryginalna klatka | ten sam załącznik bez obróbki |
| `precision-observatory.webp` | tło Precision | załącznik (wieża pod niebieskim księżycem), kadr 1920×1080 + chłodny cyjan |
| `dyscypline-citadel.webp` | tło Dyscypline | załącznik (oko nad cytadelą z kręgiem portalu), kadr 1920×1080 + szmaragdowy akcent |
| `profits-vault.webp` | tło Profits | grafika proceduralna – żaden załącznik nie przedstawiał skarbca |
| `src/assets/pepe-wizard.webp` | logo | istniejący zasób panelu |

Modele 3D wież, mapy boczne i efekty są proceduralne (brak plików modeli). Pozostałe załączniki (sieci neuronowe, oczy, film z
rotującym grafem) posłużyły jako inspiracja (`WIZARD_REFERENCES`) – nie są dołączone jako pliki.

**Ponowne wygenerowanie zasobów** (np. po podmianie grafik):
`python tools/wizard_assets.py --menu <plik tła menu> --precision <obraz> --dyscypline <obraz>` – wymaga `pillow` i (dla tła Profits)
Playwright z Chromium.

## 4. Uruchomienie
- Paczka klienta / aplikacja Windows: bez zmian w sposobie startu.
  - Uruchom `PepeMarketWizardDesktop.exe` albo `03_START_MASTERQUO.bat`.
  - Panel otwiera się na menu z trzema wieżami.
  - Dotychczasowe widoki zostają: link „pełny terminal” i „dotychczasowe menu” w stopce, sekcja „Wieże” w pasku terminala.
- Podgląd bez MT5: `07_START_DEMO_DANE_SYNTETYCZNE.bat` (symulator – oznaczony „DANE SYNTETYCZNE” w każdym widoku).
- Słaby komputer albo brak WebGL:
  - menu samo przełącza się na przyciski z rysunkami wież (także gdy 3D rysuje się poniżej 5 kl./s);
  - wymuszenie przycisków: `#/menu?webgl=0`;
  - wymuszenie 3D: `#/menu?webgl=1`.
- Ograniczenie animacji w systemie (`prefers-reduced-motion`): bez ruchu kamery, portalu, błyskawic i impulsów; tło statyczne;
  scena 3D rysowana tylko przy zmianie (wskazanie, fokus, zmiana rozmiaru), mapy boczne odświeżane 2× na sekundę.
- Deweloper: `cd frontend && npm install && npm run build` (wynik w `frontend/dist`, serwowany przez backend).

## 5. Wydajność i dostępność (co zrobiono, co zmierzono)
- **Optymalizacje:**
  - three.js w osobnym, leniwie ładowanym pliku (~0,56 MB);
  - wspólne geometrie i materiały, instancing cząstek;
  - 6 świateł, bez cieni;
  - adaptacyjna rozdzielczość renderu (DPR);
  - pauza, gdy karta lub scena są niewidoczne (`visibilitychange` + `IntersectionObserver`);
  - zwalnianie zasobów przy wyjściu z menu (`dispose`);
  - utrata kontekstu WebGL albo zbyt wolne renderowanie → przyciski bez 3D.
- **FPS – zmierzony, nie obiecany:**
  - Środowisko: headless Chromium z programowym rendererem **SwiftShader (CPU, bez karty graficznej)** przy 1920×1080.
  - Wynik: **0,7–1,2 klatki/s** w sześciu uruchomieniach, po automatycznym obniżeniu rozdzielczości renderu do 0,75 (plik
    `data/logs/ui_wizard/fps.json` z testu).
  - To skrajnie wolny przypadek. Na komputerze z GPU wartość będzie wyższa, ale **nie była tu mierzona**.
- **Automatyczne wyłączenie 3D na zbyt wolnym komputerze:** scena mierzy klatki co ~3 s albo co 90 klatek. Jeśli przy najniższej
  rozdzielczości dwa razy z rzędu ma mniej niż 5 kl./s (typowe dla renderowania programowego, np. maszyna wirtualna albo pulpit zdalny):
  - menu samo przechodzi na przyciski z rysunkami wież;
  - pokazuje zmierzoną wartość (bot na tym samym komputerze potrzebuje procesora);
  - wymuszenie 3D mimo to: `#/menu?webgl=1`.
- **Dostępność:**
  - wieże to przyciski HTML, strzałki ←/→, widoczny fokus;
  - link „Przejdź do treści”;
  - tekst na pełnych panelach, nie na ruchomej grafice;
  - mapy boczne mają opis tekstowy (liczba węzłów według stanu) i listę modułów;
  - na wąskich ekranach mapy chowają się do rozwijanych paneli, a przyciski wież są pod sceną.

## 6. Kontrole wykonane w tym środowisku
Test przeglądarkowy `tests/test_ui_wizard.py`: Chromium + WebGL SwiftShader + backend demo na symulatorze. Wynik ostatniego
uruchomienia na końcowej wersji: **12 / 12 OK** (277 s).

W trakcie prac testy znalazły i pomogły naprawić:
- setup znikający z listy przy kolejnej ocenie – teraz zostaje ostatni znany stan z oznaczeniem „nieaktualny”, także po odświeżeniu;
- brak pomiaru FPS przy bardzo wolnym renderowaniu – pomiar co ~3 s;
- przewijanie wewnętrznego pudełka zamiast strony na telefonie;
- karta wpłat / wypłat chwilowo „brak danych” do następnego odświeżenia statystyk (co 20 s) – to prawdziwy stan, test teraz czeka
  na dane zamiast czytać je raz;
- przy ograniczonych animacjach scena 3D nadal rysowała się bez przerwy – na rendererze programowym blokowało to stronę na tyle długo,
  że połączenie WebSocket przekraczało czas powitania; teraz scena jest statyczna i rysowana tylko przy zmianie.

Pozostałe uruchomione testy:

| Test | Wynik |
|---|---|
| `test_telemetry_api` (aktywność magistrali, wpłaty ≠ zysk, `GET /api/v1/telemetry`: kształt, sesja, tylko odczyt) | 4 / 4 OK |
| `test_stats_definitions`, `test_arch_fixes`, `test_evaluation`, `test_finish_plan` | 53 / 53 OK |
| `test_sh_api`, `test_risk_execution`, `test_agent`, `test_ml` | 59 / 59 OK |
| `test_ui_pages` (pierwszy start = menu, nawigacja, jedno WebSocket) | 8 / 8 OK |
| `test_ui_analytics` | 4 / 4 OK |
| `test_ui_terminal_shell` (pasek terminala z sekcją „Wieże”) | 13 / 13 OK |

Pełnego zestawu wszystkich testów repozytorium w tej rundzie nie uruchamiano – tylko testy powiązane ze zmienionymi plikami (powyżej).

| Kryterium | Sprawdzone przez |
|---|---|
| GIF jako podstawa tła, reaktywne tło | `test_01` (zasób tła, obraz załadowany, reakcja na wskazanie wieży) + zrzuty |
| Trzy różne wieże 3D, dokładne nazwy | `test_01` (WebGL `on`, nazwy `Precision` / `Dyscypline` / `Profits`) |
| Każda wieża otwiera swój widok z własnym tłem | `test_02` (klik, Enter, strzałki; trzy różne pliki tła; Back, odświeżenie, logo) |
| Kliknięcie tylko nawiguje | `test_03` (żadnego żądania zlecenia / trybu; tryb i STOP bez zmian) |
| Treść Precision / Dyscypline / Profits | `test_04`, `test_05`, `test_06` |
| Mapy reagują na mysz i backend | `test_07` (tooltip, lista, szczegóły, filtry; impulsy z prawdziwych zdarzeń WS) |
| Brak połączenia widoczny, brak impulsów offline | `test_09` (odcięty WebSocket → „Backend … ponowne łączenie”, „brak łącza”, OFFLINE, licznik impulsów stoi; potem ponowne połączenie) |
| Brak danych widoczny | `test_06` („brak danych” zamiast zer), `test_04` (stan stref) |
| Nawigacja bez WebGL, klawiaturą, dotykiem | `test_10` (`?webgl=0`, dotknięcie na telefonie, ograniczone animacje) i `test_02` (klawiatura) |
| Brak mnożenia subskrypcji | `test_08` (3× przejście przez wszystkie widoki: jedno połączenie WebSocket, liczba subskrybentów szyny bez zmian) |
| Ryzyko / Execution Lock | `test_05` (pasek ryzyka: tryb, nowe wejścia, ścieżka główna, Execution Lock) |
| 1920×1080, 1366×768, 390 px | `test_01`, `test_10` (bez poziomego przewijania; wszystkie wieże i etykiety bez przewijania na desktopie) |
| FPS | `test_11` (pomiar, zapis do `fps.json`) |
| Za wolne 3D → przyciski | `test_12` (na SwiftShader menu samo przechodzi na przyciski, z notą i zmierzoną wartością) |

Pozostałe uruchomione testy są wymienione w CHANGELOG.

## 7. Zrzuty działających widoków
W `docs/zrzuty_1_26/` (JPEG, zmniejszone do 1600 px szerokości). Pochodzą z testu `test_ui_wizard`: działająca aplikacja, backend demo na
symulatorze, Chromium; wieże w WebGL (SwiftShader).

| Plik | Co pokazuje |
|---|---|
| `menu_1920_wskazana_wieza.jpg` | menu 1920×1080, wskazana wieża Dyscypline (poświata, opis) |
| `menu_1920_mapy.jpg` | menu z mapami przepływu po bokach |
| `menu_1366.jpg` | menu 1366×768 – trzy wieże i etykiety bez przewijania |
| `menu_390.jpg` | telefon 390 px – przyciski wież pod sceną, mapy zwinięte |
| `menu_1366_bez_webgl.jpg` | menu bez WebGL (`?webgl=0`) |
| `menu_1920_auto_bez_3d.jpg` | automatyczne wyłączenie 3D przy renderowaniu poniżej 5 kl./s |
| `menu_1920_offline.jpg` | backend zatrzymany: „brak łącza”, „Backend CLOSED”, mapy OFFLINE bez impulsów |
| `profits_1920_offline.jpg` | widok Profits przy zatrzymanym backendzie |
| `precision_1920.jpg` | Precision: wykresy, notowanie, reżim per interwał, strefy |
| `precision_390.jpg` | Precision na telefonie |
| `dyscypline_1920_szczegoly.jpg` | Dyscypline: lista setupów, szczegóły z warunkami, ryzykiem i wykresem |
| `dyscypline_390.jpg` | Dyscypline na telefonie |
| `profits_1920.jpg` | Profits: rachunek, ROI z metodą, wpłaty/wypłaty, krzywa kapitału, porównania |
| `profits_390.jpg` | Profits na telefonie |

## 8. Rzeczywiste luki integracji (do decyzji / dalszej pracy)
1. **Execution Lock nie wrócił.** Specyfikacja wymaga, aby „Execution Lock pozostał skuteczny”, ale w 1.24 wycofano go na Twoją
   wyraźną decyzję („nie przywracaj go ani nie zastępuj ukrytą blokadą”).
   - Zlecenia nadal chronią: wybór trybu, STOP nowych wejść, ścieżka główna, Twoje limity ryzyka, bramki backendu i wymagania brokera.
   - Pasek w Dyscypline pisze to jawnie.
   - Przywrócenie wymaga Twojej decyzji.
2. **Tło menu z GIF to jedna klatka.** Załącznik dotarł jako pojedyncza klatka, więc animację błyskawic, mgły i światła rysuje warstwa
   na żywo. Jeśli masz pełny animowany GIF/wideo, podmiana pliku w `assets.ts` wystarczy (warstwy na żywo zostają).
3. **Prawa do grafik.** Tła Precision / Dyscypline i tło menu to Twoje załączniki. Przed udostępnianiem paczki innym osobom upewnij się,
   że możesz je rozpowszechniać. Tło Profits i wieże są wygenerowane w projekcie.
4. **Modele bez zdarzeń na żywo** (np. modele trenowane bez inferencji w bieżącym cyklu):
   - w mapie mają stan z rejestru (`/api/v1/telemetry` co 15 s);
   - impulsu nie mają, bo backend nie publikuje dla nich zdarzenia;
   - „ostatnia praca” = ostatnie zdarzenie tematu albo „—”.
5. **Obsunięcie** liczone z zapisanych snapshotów equity (co 60 s od pierwszego uruchomienia z rachunkiem) i z krzywej zrealizowanych
   wyników bota. Historia rachunku sprzed pierwszego uruchomienia nie jest odtwarzana – wtedy widok pisze „brak danych”.
6. **ROI rachunku obejmuje także transakcje ręczne** (opisane w widoku). ROI samego bota: tabele ścieżek i strategii (wynik netto
   z kosztami).
7. **Prawdopodobieństwo** pojawi się w Dyscypline dopiero, gdy model ML przejdzie kalibrację na Twoich danych. W tym środowisku
   kalibracji nie było, więc widok go nie pokazuje.
8. **Przełącznik instrumentu w górnym pasku** to istniejąca funkcja, która zmienia aktywny instrument bota. Nie jest nawigacją, a widoki
   wież go nie wywołują automatycznie.
9. **Nie wykonano w tym środowisku:**
   - uruchomienia na Windows i z prawdziwym MT5 (wszystkie zrzuty z symulatora);
   - pomiaru FPS na GPU;
   - testu czytnikiem ekranu.
