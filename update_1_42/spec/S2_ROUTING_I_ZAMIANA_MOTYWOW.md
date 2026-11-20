# S2 – Routing i pełne zastąpienie starego interfejsu

## 0. Decyzje użytkownika (POTWIERDZONE w rozmowie)

1. **Stary interfejs aplikacji usuwamy w całości**, czyli wszystkie 41 ekranów. Zostaje wyłącznie nowy interfejs:
   - cinematic z filmem;
   - menu FOREX / CRYPTO / OTC;
   - kula FOREX z CHARTS, SIGNALS, MODELS & BACKTEST i ROI;
   - **panele systemowe w nowym stylu**: Ustawienia (w tym połączenie z MT5), Tryb pracy + STOP, Diagnostyka (`spec/S6_PANELE_SYSTEMOWE.md`).
2. **Animacją startu zostaje film intro** z menu 1.1.0.
3. **Aplikację przebudowujemy w pełni**:
   - frontend (`dist`);
   - okno Windows (`PepeMarketWizardDesktop.exe` z nowym `splash.html`);
   - paczki wydania `tools/build_release.py` i `tools/build_desktop.py`, wersja 1.42.0.

Nie usuwamy niczego po stronie silnika:
- backend, strategie, modele, API, baza i testy silnika zostają;
- **wskaźniki i moduły MQL5 w MetaTraderze** (`mql5/`) zostają, bo to część silnika, a nie interfejs aplikacji.

## 1. Nowy przepływ

```
[Windows] okno startowe (nowy splash: postęp startu silnika) → „WEJDŹ” → panel ?pmw_joined=1#/menu
[Przeglądarka] adres bez hasha → #/menu

#/menu  →  film intro (raz na sesję; „PRZEJDŹ DO MENU”, ESC, ograniczenie ruchu = od razu menu)
        →  menu: PEPEMARKETWIZARD TEAM + 01 FOREX · 02 CRYPTO · 03 OTC + pasek narzędzi
              FOREX   → planeta na środek → przelot → #/forex
              CRYPTO / OTC → „tryb w przygotowaniu” → POWRÓT DO MENU (bez zmiany profilu bota)
#/forex                 ekran FOREX
#/forex?s=charts | signals | models | roi
#/system?p=settings | mode | diagnostics     panele systemowe (S6) – także jako szuflada nad każdym ekranem
```

- **Wstecz**:
  - ekran planety → ekran FOREX;
  - ekran FOREX → menu (wynurzenie);
  - panel systemowy → ekran, z którego go otwarto.
- **Router**: w `Page` zostają tylko `"menu" | "forex" | "system"`. Ekrany FOREX wybiera parametr `s`, panele systemowe parametr `p`.
  - `parse()` może zostać, ale bez specjalnego przypadku `warunki`.
  - Usuń `GROUPS`, `TOWER_*`, `WIZARD_*`, `TERMINAL_*`, `CULT_PAGE_IDS`.
  - `SCREEN_MAP` zamień na `LEGACY_REDIRECTS` (tabela §3).
- **Ramka aplikacji**: `App.tsx` renderuje tylko `app-cinematic`. `AppShell`, menu boczne, `BackgroundLayer` i stare dialogi w starym stylu znikają. Znacznik **SYNTETYCZNE** przy `s.synthetic` widać na każdym ekranie w rogu.
- **Pierwsze uruchomienie** (`s.first_run_completed === false`): po intro otwiera się panel Ustawienia (S6), tak jak dziś otwiera się `SettingsModal`.

## 2. Co usuwamy (przenosimy do `archive/ui_1_41/`, poza build)

| Obszar | Ścieżki |
|---|---|
| Start i menu | `features/cult/Launcher.tsx`, `launcher.css`, `features/galaxy/*` (BootScreen, Galaxy V2), `features/neural-city/*` |
| Wieże i widoki | `features/cult/*` (Lightning, Wind, Control, Strategy Lab, CultShell, kit, data, assets, cult.css), `features/towers/*` (PEPE$WTC, PEPE$SIGNAL), `features/wizard/*` (Precision, Dyscypline, Profits), `features/shell/*`, `features/trading-intelligence/*`, `features/ai-neural-lab/*`, `features/system-control/*`, `features/market-zones/*`, `features/training-center/*`, `features/pmw133/*`, `nc/*` |
| Strony i komponenty | `pages/*`, `components/*` (poza tym, co S1 wskaże jako reużyte: najpewniej `ChartPanel`/`chartview`/`chartprefs`/`zones.ts` dla CHARTS, `ErrorBoundary`), `components/layout/*`, `components/ThemeDialog.tsx`, `appearance.tsx`, `theme.tsx` (jeśli nieużywane) |
| Zasoby | `public/assets/cult`, `galaxy`, `neural`, `towers`, `wizard`, `wtc21`, `masterquo` (o ile nic z nowego UI ich nie używa), `src/assets/pepe-wizard.webp`, `public/header_art.webp` |
| Okno Windows | stary wygląd `desktop/splash.html` (obraz Pepe, JOIN THE CULT); protokół zostaje (S6 §5) |

Zasady przenoszenia:
1. **Przenoś do archiwum, nie kasuj.** `archive/ui_1_41/` nie wchodzi do buildu ani do paczki wydania. Sprawdź listę plików `build_release.py` i dodaj wykluczenie, jeśli trzeba.
2. **Moduły współdzielone** (`api.ts`, `store.tsx`, `util.ts`, `telemetry.ts`, obliczenia wskaźników, `chartprefs`, `zones.ts`, `ai.ts`) zostają, jeśli używa ich nowe UI. Logikę potrzebną w nowym UI, która siedzi w usuwanym pliku (np. warstwy WtcTower, obliczenia z `pages/*`), **wydziel** do `frontend/src/core/` bez zmiany zachowania i opisz w raporcie.
3. **Studio** (`studio.html`, `frontend/src/studio/*`, `PepeTrainingStudio.exe`) to osobny program, który dziś nie jest częścią interfejsu panelu. DO WERYFIKACJI: zapytaj użytkownika w E0. Domyślnie zostaje bez zmian.
4. Po przeniesieniu `tsc -b` i `npm run build` muszą przejść. Martwe importy usuń. Niczego nie zastępuj atrapą.

## 3. Przekierowania starych adresów (`LEGACY_REDIRECTS`)

Stare zakładki i linki nie mogą prowadzić w próżnię. Każdy stary hash przekierowuje (`replace`) na najbliższe nowe miejsce:

| Stare hashe | Nowe miejsce |
|---|---|
| `#/menu` (Galaxy), `#/neural-city`, `#/galaxy`, `#/lightning`, `#/wind`, `#/control`, `#/strategy-lab`, `#/nc` | `#/menu` |
| `#/pepe-wtc`, `#/wtc`, `#/wykresy`, `#/precision`, `#/strefy`, `#/scalp-mtf`, `#/indykatory`, `#/dxy`, `#/svp`, `#/kontekst`, `#/market-news`, `#/trading-intelligence` | `#/forex?s=charts` |
| `#/pepe-signal`, `#/signal`, `#/brain-signal`, `#/sygnal`, `#/setupy`, `#/warunki/*`, `#/strategie`, `#/ai`, `#/formacje`, `#/dyscypline`, `#/decyzje` | `#/forex?s=signals` |
| `#/modele`, `#/trening`, `#/training-lab`, `#/neural`, `#/struktura`, `#/testy`, `#/badania`, `#/ai-neural-lab` | `#/forex?s=models` |
| `#/profits`, `#/pepe-roi`, `#/leaderboard`, `#/pozycje`, `#/dziennik`, `#/pulpit`, `#/pepe-bank` | `#/forex?s=roi` |
| `#/ustawienia`, `#/settings`, `#/licencje`, `#/dane` | `#/system?p=settings` |
| `#/system-control` | `#/system?p=mode` |
| `#/diagnostyka` | `#/system?p=diagnostics` |
| każdy inny nieznany hash | `#/menu` |

Okno Windows otwiera panel z „ostatnim ekranem” (`app_windows.go`, komentarz „no intro: ?pmw_joined=1 and the last screen”). Zapamiętany stary hash przejdzie przez tę tabelę. Sprawdź to w E9.

## 4. Relacja do profili rynku

Profile `FOREX_MT5`, `CRYPTO_FOMO_PERPS`, `OTC_GOLD_POCKETOPTION` (`baskets/service.py`, POTWIERDZONE).
**Wybór planety w menu to nawigacja, nie przełączenie profilu.** Nie wywołuj `PUT /api/v1/baskets/settings`.
Ekran FOREX pokazuje aktywny profil. Gdy ≠ `FOREX_MT5`, pokazuje ostrzeżenie: „Aktywny profil bota: … – ten ekran pokazuje dane FOREX/MT5”.
Zmiana trybu pracy jest możliwa wyłącznie w panelu **Tryb pracy** (S6), tymi samymi wywołaniami i potwierdzeniami co dziś.
