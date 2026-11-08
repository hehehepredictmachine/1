# 1.34.0 – Menu główne Neural City V7.0 i launcher JOIN THE CULT (TASK 001)

Źródła zadań:
* `PepeMarketWizard_NeuralCity_MainMenu_V7_0_ClaudeCode_12.zip` (SHA-256 `a16e9388…c858b6`): MASTERPROMPT, `tower_registry.json`,
  referencja `neural-city-reference.png`, prototyp 2.5D;
* `Launcher.zip` (SHA-256 `90a53167…c835af`): `Prompt.txt` (TASK 001), grafika Pepe przemawiającego, animacja neuronów (GIF + klatka);
  plik `Animacja.txt` jest pusty.

Zakres zgodnie z poleceniem:
* **zmieniono** tylko menu główne, launcher, nawigację i nazwy;
* **nie zmieniono** wnętrz wież (paneli), strategii, AI, Kronos, ryzyka, wykonania, MT5 ani konfiguracji i bazy bota.

## 1. Mapa wież i tras

| Wieża (nazwa widoczna) | Dawniej | Otwiera istniejący panel | Trasa | Aliasy (stare i nowe) |
|---|---|---|---|---|
| PEPE$WTC | WTC PEPE, TRADING | Trading Intelligence – terminal handlowy | `#/trading-intelligence` | `#/wtc`, `#/wtc-pepe`, `#/trading` |
| PEPE$SIGNAL | BRAIN SIGNAL, BACKTEST | Wind Portal – modele AI, konsensus, ślad decyzji, Monte Carlo | `#/wind` | `#/pepe-signal`, `#/brain-signal`, `#/backtest` |
| PEPE$BANK | AI AGENT | Lightning Tower – sygnały BUY/SELL, plan wejścia, cykl życia | `#/lightning` | `#/pepe-bank`, `#/ai-agent` |
| MARKET NEWS | NEWS | Kontekst rynku – wiadomości i kalendarz makro | `#/kontekst` | `#/market-news`, `#/news` |
| STRATEGIES | – | Strategy Lab | `#/strategy-lab` | `#/strategies` |
| SETTINGS | – | Ustawienia | `#/ustawienia` | `#/settings` |
| PEPE$ROI | LEADERBOARD | Profits – rozliczone pozycje i wynik rachunku | `#/profits` | `#/pepe-roi`, `#/leaderboard` |

Uwagi do mapy:
* Trasy z `tower_registry.json` były sugestiami, a powyższe to rzeczywiste ekrany repozytorium.
* Wszystkie dotychczasowe trasy działają bez zmian.
* Stare nazwy są w podpowiedziach (`title`), w opisie dla czytników ekranu i w panelu ⓘ.
* Zaktualizowane zostały również:
  * etykiety w `router.ts` (tytuł okna, mapa ekranów w Ustawieniach);
  * menu boczne paneli wież (`TOWER_NAV`).
* Poprzednie menu (miasto sześciu wież) zostało zastąpione. Jego panele są nadal dostępne z menu bocznego: Ice Tower → Precision,
  Control Tower → zarządzanie botem.

## 2. Menu główne Neural City (`frontend/src/features/neural-city/`)

**Scena.** To zatwierdzona grafika w oryginalnych pikselach (1672 × 941). Narzędzie `tools/neural_city_assets.py`:
* usunęło z niej stare nazwy wież (tylko biały tekst; neonowe tabliczki zostają);
* usunęło przykładowe wartości 72,8 % / +168,4 % / $1 248 932, nawigację podglądu, znacznik „DANE DEMO”, panel hasła i przyciski podglądu;
* zapisało sumy SHA-256 i obszary inpaintingu w `frontend/public/assets/neural/zrodla.json`.

Nazwy, nawigacja, statystyki, motto i efekty są rysowane na żywo.

**Jeden kontroler.** Ten sam kontroler (`select`) obsługuje kliknięcie wieży, przycisk górnego paska, Enter na wieży i listę na małych
ekranach. Stany: IDLE → SELECTED → STOP_ROTATION → PEPE_REACH → CONTACT → PORTAL → NAVIGATE, a po powrocie do menu RETURN.

| Zachowanie | Działanie |
|---|---|
| Podwójne kliknięcie | jedna nawigacja (debounce) |
| Esc | anuluje sekwencję |
| Powrót z wieży | przywraca fokus na tej wieży |
| Ograniczony ruch systemu, Performance, pauza | bez sekwencji, od razu panel |

**HUD.**
* Winratio i ROI pochodzą z `/api/v1/stats`. ROI liczone jest metodą Dietza, więc wpłaty i wypłaty nie zmieniają wyniku.
* Equity pochodzi z rachunku MT5 terminala.
* Każda wartość ma znacznik źródła: REAL / DEMO / DEMO · symulator / brak danych / nieaktualne / błąd. Bez danych pokazywane jest N/A.
* Nic nie jest liczone w JavaScripcie i nie są potrzebne żadne dane logowania.

**Animacje 2.5D.**
* Pierścienie hologramów u podstawy każdej wieży: niezależne prędkości, spowolnienie przy najechaniu, zatrzymanie po wyborze, błysk przy
  „kontakcie”.
* Cząsteczki neuronowe i impulsy prądu od rdzenia do wież (szybsze do wybranej wieży).
* Rdzeń reaguje na wybór.
* Aura Pepe.
* Świetlna ścieżka gestu od dłoni Pepe do wieży, oznaczona jako efekt stylizowany 2.5D.
* Portal i przelot kamery.
* Paralaksa.
* Intro po JOIN THE CULT: lot przez sieć neuronów (animacja z paczki launchera, w zieleni neonowej), Esc lub kliknięcie pomija.
* Jakość: Cinematic / Balanced / Performance, a także pauza i ustawienia cząsteczek, paralaksy oraz intro (zapamiętywane w przeglądarce).

**Rozdzielczości.**
* Scena zachowuje proporcje: 1920 × 1080 i 1280 × 720 bez przewijania.
* Poniżej 900 px szerokości pod sceną pojawia się lista siedmiu wież (pasek nawigacji jest wtedy ukryty).

**Uczciwy zakres.** To **fallback 2.5D** z MASTERPROMPT, etap 2:
* wieże są pikselami grafiki, a nie geometrią;
* obracają się tylko pierścienie hologramów (bryły się nie obracają);
* Pepe nie ma riga ani IK.

Brakujące zasoby do pełnego 3D:
* modele glTF siedmiu wież (z osobnymi pierścieniami i tabliczkami);
* model Pepe z rigiem i IK dłoni (punkty kontaktu);
* model stołu i rdzenia;
* tekstury emisyjne.

Po ich dostarczeniu scenę można przenieść do Three.js przy tym samym kontrolerze, trasach i HUD.

## 3. Launcher JOIN THE CULT (TASK 001)

**Przeglądarka** (`frontend/src/features/cult/Launcher.tsx`, `launcher.css`):
* dostarczona grafika jest całym tłem: `object-fit: cover`, proporcje zachowane, kadr na Pepe;
* JOIN THE CULT na dole pośrodku: poświata, hover, animacja kliknięcia, fade-in;
* przycisk jest aktywny dopiero przy SYSTEM READY (stan i WebSocket bota);
* przed ukryciem launchera menu wczytuje scenę i ponownie sprawdza połączenie. Jeśli połączenie zostało przerwane, launcher zostaje,
  pokazuje komunikat, a przycisk znów działa;
* gdy silnik w ogóle nie odpowiada, pokazywany jest dotychczasowy ekran błędu z instrukcją (nigdy „SYSTEM READY”);
* panel nie jest montowany przed kliknięciem.

**Okno Windows** (`desktop/splash.html` + `app_windows.go`):
* ta sama grafika (`desktop/assets/launcher-speech.webp`, osadzona w EXE) jest tłem całego okna;
* JOIN THE CULT jest na dole pośrodku;
* wszystkie dotychczasowe funkcje działają bez zmian: postęp pierwszego startu, wybór danych poprzedniej instalacji, błąd + Spróbuj
  ponownie, logi, Zamknij;
* drugie kliknięcie nie wywołuje drugiego `join`;
* gdy aplikacja odrzuci przejście, okno zostaje z komunikatem.

Okno nadal uruchamia jedną instancję i zamienia się w panel dopiero po udanym przejściu.

## 4. Uruchomienie
* **Aplikacja Windows:** `PepeMarketWizardDesktop.exe` – launcher, JOIN THE CULT, intro, Neural City.
* **Przeglądarka:** `03_START_MASTERQUO.bat` → `http://127.0.0.1:8765/` (launcher na początku sesji). Bezpośredni link, np.
  `#/menu`, pomija launcher.
* **Ponowne wygenerowanie grafik:**
  `python tools/neural_city_assets.py --menu <folder PepeMarketWizard_NeuralCity_MainMenu_V7_0> --launcher <folder Launcher>`.

## 5. Zmienione pliki

| Obszar | Pliki |
|---|---|
| Nowe | `features/neural-city/NeuralCityMenu.tsx`, `neural-city.css`, `towers.ts`; `features/cult/launcher.css`; `public/assets/neural/*` (scena, rozmyte tło, launcher, animacja neuronów, klatka, `zrodla.json`); `desktop/assets/launcher-speech.webp`; `tools/neural_city_assets.py`; `tests/test_ui_neural_city.py` |
| Zmienione | `App.tsx` (menu → Neural City); `router.ts` (aliasy, etykiety, mapa ekranów); `features/cult/Launcher.tsx`; `features/cult/CultShell.tsx` (menu boczne); `desktop/splash.html`, `desktop/app_windows.go`, `desktop/desktop_test.go`; `tools/cult_assets.py` (nie kopiuje już starych grafik launchera); `tools/make_manuals.py`; `tests/test_ui_cult.py` (testy launchera i menu przeniesione do `test_ui_neural_city.py`) |
| Usunięte | `features/cult/CultMenu.tsx` (miasto sześciu wież), `desktop/assets/crown.webp`, `desktop/assets/launcher-scene-small.webp` |

## 6. Testy (`tests/test_ui_neural_city.py`, Chromium + serwer demo)

| Test | Zakres |
|---|---|
| 01 | Launcher: <ul><li>bramka sesji, tło = dostarczona grafika 1199 × 675 z `cover`</li><li>JOIN na dole pośrodku, aktywny przy SYSTEM READY, hover</li><li>intro → menu</li><li>po odświeżeniu i przy bezpośrednim linku launcher się nie pokazuje</li></ul> |
| 02 | Silnik nie odpowiada → komunikat startowy, nigdy SYSTEM READY |
| 03 | Okno Windows `splash.html` z atrapą mostka: <ul><li>stany ready / progress / error / wybór danych w 960 × 660 i 716 × 618</li><li>nic nie wystaje poza okno</li><li>JOIN na dole pośrodku</li><li>podwójne kliknięcie = jeden `join`</li></ul> |
| 04 | Dokładnie 7 nazw na tabliczkach i w nawigacji, bez starych nazw w widocznym tekście. Dla każdej wieży: <ul><li>wieża i przycisk paska mają ten sam cel</li><li>tabliczka przyjmuje kliknięcie</li><li>pełna sekwencja stanów, a potem właściwy istniejący panel</li></ul> Bez zleceń i bez zmiany trybu |
| 05 | Klawiatura + Enter; Esc anuluje (bez nawigacji); podwójne kliknięcie = jedna zmiana adresu; powrót = fokus na wieży |
| 06 | HUD: wartości z bota albo N/A, nigdy REAL na symulatorze, bez wartości przykładowych z grafiki |
| 07 | Performance = natychmiastowe przejście; pauza; ograniczony ruch → bez intro, natychmiastowe przejście |
| 08 | 1920 × 1080, 1280 × 720, 390 px bez poziomego przewijania; lista wież na małym ekranie; aliasy starych i nowych tras; jedno gniazdo WebSocket |
| 09 | Zrzut porównawczy z referencją (patrz §7) |

## 7. Porównanie z referencją
Zrzut sceny w 1672 × 941 (`data/logs/ui_neural_city/09_reference_vs_app.png`: u góry referencja, na dole aplikacja). Średnia różnica
pikseli w obszarze stołu i wież (0–255):

| Porównanie | Średnia różnica | Co ją tworzy |
|---|---|---|
| względem oczyszczonej sceny | **4,6** | pierścienie, tabliczki, cząsteczki |
| względem referencji | **8,8** | głównie nowe nazwy na tabliczkach w miejscu starych |

Kompozycja, pozycje wież, Pepe, stół, rdzeń, logo i motto odpowiadają referencji. Inne są:
* pasek nawigacji (siedem nowych nazw zamiast „Trading / Strategies / Analytics / News” z grafiki);
* karty HUD (dane bota zamiast przykładowych).
