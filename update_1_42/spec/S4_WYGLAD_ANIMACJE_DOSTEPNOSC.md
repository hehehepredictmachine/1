# S4 – Wygląd, animacje, dostępność

Obraz docelowy jest w `referencje/zrzuty/`. Wartości poniżej są wzięte z plików referencyjnych. W razie rozbieżności rozstrzyga kod referencyjny.

## 1. Tokeny

| Token | Wartość |
|---|---|
| Tło | `#000` (czarna głębia), winieta jak `#vignette` w REF_A |
| Tekst główny / przygaszony / opisy | `#f2f2ef` / `#c9cbd1` / `#9aa0aa`, etykiety `#777d87` |
| Srebro cząsteczek | `vec3(.77,.80,.87)` → `vec3(.98,.985,1.)` (światło + rim) |
| Akcent fioletowy (pierścienie, challenger, impulsy) | `#b5a8ff`, `#7d70d0`, w GLSL `vec3(.70,.66,1.)` |
| Plus / minus | `#cfe8da` / `#e0b3b3` |
| Ostrzeżenie (mała próba, wpłata, DEMO/SYNTETYCZNE) | `#d9c99a` / `#b7a77a` |
| Ramki okien | `.cs-win` z narożnikami `.corner` (REF_B), tło `rgba(6,9,20,.84)` → `rgba(3,3,8,.86)` |
| Typografia | `"Helvetica Neue",Helvetica,Arial,sans-serif`; nagłówki z dużym rozstrzeleniem (`letter-spacing .22–.36em`), liczby `font-variant-numeric: tabular-nums`, grube liczby `font-weight 200–300` |

## 2. Menu główne (REF_A)

| Element | Wartość |
|---|---|
| Intro | `/assets/cinematic/intro.mp4`, `object-fit: contain`, wyciszone domyślnie, pasek postępu 1 px na dole, etykieta lewy górny róg |
| Wejście do menu (`entrySeconds`) | 3,0 s: film skaluje się do 2,25× i rozmywa do 9 px, gwiazdy z rozmyciem ruchu (`warp`), FOREX wyłania się z centrum, CRYPTO/OTC z małych punktów |
| Planety | FOREX (pierścień + 4 księżyce, 110k cz.), CRYPTO (bloki + łańcuch, 94k), OTC (rdzeń + powłoka, 66k); okluzja siatką dla wszystkich |
| Układ | desktop: FOREX `(.5w,.369h)`, CRYPTO `(.767w,.654h)`, OTC `(.233w,.654h)`; wąski ekran wg `resize()` w REF_A |
| Interakcja | hover (zafalowanie przy kursorze, rozstrzelenie nazwy), przeciąganie obraca kulę (pierścień i księżyce nie obracają się), strzałki zmieniają fokus, klik = wybór |
| Wybór (`selectSeconds`) | 1,85 s: pozostałe planety gasną i rozpraszają się, wybrana jedzie do `(.5w,.43h)` |
| Powrót (`returnSeconds`) | 1,35 s |
| **FOREX → przelot** | po wyborze FOREX: planeta na środku → przejście do `ForexScene` w tej samej pozycji i skali (pozę startową kuli w REF_B dopasuj do `selectPose` z REF_A), przenikanie ≤ 150 ms bez widocznego skoku, potem przelot |
| Narzędzia | odtwórz intro (R), dźwięk, ogranicz ruch, pełny ekran, ustawienia (otwiera `SettingsModal`) |

## 3. Kula FOREX i ekran FOREX (REF_B)

| Element | Wartość |
|---|---|
| Kula w menu | ten sam kształt planety FOREX co w REF_A (`SHAPE` w REF_B = wersja z menu v1.1) |
| Przelot (`CFG.diveMs`) | 3200 ms: kamera wlatuje w cząsteczki, smugi, przejście cząsteczek kuli w tło; wynurzenie (`surfaceMs`) 1600 ms |
| Tło | cykl 66 s (`bgCycle`), dalekie i przygaszone („bardziej w tle”) |
| Panele modeli | górne rogi, rozciągnięte w dół (`--pw`, `--edge-x/y`), MODEL A = kolumna 7 pierścieni z impulsem w dół, MODEL B = wir z kropkowaną planetą w rdzeniu i łańcuchami cząsteczek do rdzenia; statusy ANALIZA / OCZEKUJE / BŁĄD zmieniają prędkość, jasność, nasycenie (`STATUS`) |
| Planety | 01 CHARTS góra-środek (między panelami), 02 SIGNALS środek, 03 MODELS & BACKTEST lewy dół, 04 ROI prawy dół (`layoutPlanets`) + podpisy |
| Droga mleczna | między planetami (`layoutMilkyWay`, `MW_V/MW_F`) |
| Wejście na ekran planety | CHARTS 2400 ms, SIGNALS 2600, MODELS 2600, ROI 2700; wyjście 1500 ms (`SCREENS`) |
| Przejścia | CHARTS: pasy planety → siatka wykresu; SIGNALS: powłoki sygnału → konstelacja; MODELS: siatka planety → eliptyczny tunel + przelot księżyca → obserwatorium; ROI: przelot przez wir → galaktyka spiralna z okiem |

## 4. Ekrany planet – elementy ruchu (obowiązkowe)

- **CHARTS**: rysowanie linii po przejściu (bez wczesnego blasku), karta planu bota przy cenie, drugi wykres Kronos z wachlarzem niepewności.
- **SIGNALS**: konstelacja sygnałów obracająca się wokół ceny, filtry, szczegóły z mini-wykresem SVG, ocena prognozy wszystkich modeli.
- **MODELS & BACKTEST**:
  - lewy panel animowany:
    - wiersze wjeżdżają po kolei (28 ms), liczniki liczą od zera;
    - kropki stanów migoczą, paski skill wypełniają się, a pasek treningu płynie;
    - po etykiecie CHAMPION przechodzi błysk, zaznaczony wiersz ma świecącą belkę;
    - najechanie na wiersz daje smugę światła i pierścień wokół gwiazdy w obserwatorium;
  - obserwatorium z rdzeniem „CENTRUM TRENINGU” i orbitą postępu zadania.
- **ROI**: wir galaktyki (differential rotation), oko z ROI i licznikiem od zera, 3 księżyce ścieżek z podpowiedzią, krzywa kapitału rysowana od lewej z pulsującą głowicą, słupki miesięcy rosnące po kolei, tabela z błyskiem wiersza po kliknięciu księżyca.

## 5. Dostępność

- Każda planeta, panel i kafel to prawdziwy `<button>` z `aria-label` i `aria-pressed`. Fokus jest widoczny (`outline 1px #dfe3eb`). Kolejność Tab zgodna z układem.
- Region `aria-live="polite"` ogłasza: wybór trybu, wejście na ekran, zmianę statusu paneli (nie częściej niż co 5 s).
- Ekran niewidoczny dostaje `inert`, a ekran aktywny dostaje fokus na pierwszy element (`focus` z `SCREENS`).
- Ograniczenie ruchu (system i przełącznik):
  - bez obrotów, przelotu i smug;
  - przejścia trwają ≤ 300 ms (`reducedMs`);
  - liczniki pokazują od razu wartość końcową;
  - animacje CSS są wyłączone (jak w `@media (prefers-reduced-motion)` w REF_B).
- Kontrast tekstu ≥ 4,5:1 dla treści, ≥ 3:1 dla dużych liczb i etykiet dekoracyjnych.
- Nie ma dźwięku bez zgody (intro jest domyślnie wyciszone).
