# RAPORT 1.42.0 – odbiór (E9)

Środowisko: kontener Linux, demo na terminalu SYNTETYCZNYM (`serve --demo`), Chromium + SwiftShader (WebGL programowy), 1600×900, DPR 1.
MT5 i Windows nie są tu dostępne – punkty wymagające prawdziwego okna Windows oznaczone ⚠️.

## Wyniki S5

### A. Start i menu
| | Wynik | Dowód |
|---|---|---|
| A1 | ✅ | `/assets/cinematic/intro.mp4` 200 `video/mp4` (E0), bez błędów CSP; `E1_intro.png` |
| A2 | ✅ | „PRZEJDŹ DO MENU” / ESC → menu; `E1_menu_3_planety.png` |
| A3 | ✅ | `sessionStorage pmw.cinematic.seen`; Ctrl+Alt+B / R odtwarza (E1_RAPORT) |
| A4 | ✅ | `E1_menu_3_planety.png`, `E1_menu_hover_forex.png` |
| A5 | ✅ | `test_ui_142.test_a_…`: CRYPTO/OTC → „w przygotowaniu” → powrót, **0 żądań nie-GET** |
| A6 | ✅ | `#/menu?renderer=cpu` → `E1_menu_cpu.png` |
| A7 | ✅ | 116 plików frontu + 26 starych testów UI w `archive/ui_1_41/`; archiwum wykluczone z `build_release` (skan paczek: 0 plików `archive/`, 0 starych zasobów); wszystkie wiersze S2 §3 – `test_ui_142.test_d_legacy_redirects` |
| A8 | ✅ | `desktop/splash.html` – WEJDŹ, protokół bez zmian; `E8_splash_progress/ready/error.png`; `desktop_test.go` OK |

### B. Kula FOREX
| | Wynik | Dowód |
|---|---|---|
| B1 | ✅ | `E2_przelot_1/2.png`, `E2_ekran_forex.png` |
| B2 | ✅ | MODEL A z `/models/predictions` (15 s), MODEL B z WebSocket `bar_closed` + `/bot-signals` (10 s); impuls tylko przy nowszym `data_time` / nowym `signal_id` |
| B3 | ✅ | `E2_ekran_forex.png` |
| B4 | ✅ | `forex-back` → `#/menu` bez intro (e2e) |
| B5 | ✅ | `fx-profile-warn` gdy `active_profile ≠ FOREX_MT5` |

### C. Ekrany planet
| | Wynik | Dowód |
|---|---|---|
| C1 | ✅ | `E3_6_charts.png`; TF z `/api/v1/timeframes`, okno Kronos z `forecast.*`, wybór TF Kronosa → `PUT /api/v1/kronos/settings` po potwierdzeniu |
| C2 | ✅ | `E3_6_signals.png` – 3 źródła, ocena 59 modeli z katalogu, „SZANSA – brak skalibrowanego modelu” |
| C3 | ✅ | `E3_6_models.png`, `E5_models_train/bt/mc.png`; NOT_RUN tam, gdzie brak raportu |
| C4 | ✅ | `E3_6_roi.png` – BRAK DANYCH w PAPER, „ROI rachunku: nie dotyczy” |
| C5 | ✅ | `test_ui_142.test_b_…`: każdy ekran otwiera `[data-testid=forex-*]`, `?s=` w adresie, powrót do `#/forex` |

### D. Uczciwość danych
| | Wynik | Dowód |
|---|---|---|
| D1 | ✅ | grep → 0 (generator cząsteczek przemianowany z `seeded` na `prng` – to geometria, nie dane) |
| D2 | ✅ | CHARTS: BID/ASK/SPREAD ← `/api/v1/state.quote`; SIGNALS: „34 sygnałów · 13 aktywnych” ← `/bot-signals` + `/sh/signals`, score 63 ← `scores.setup_score`; MODELS: 59/23/21 ← `/models/catalog`; ROI: saldo/equity 10 000 ← `/api/v1/stats?mode=PAPER.account` |
| D3 | ✅ | e2e i `test_ui_142`: przy otwieraniu ekranów i paneli **0** żądań POST/PUT |

### F. Panele systemowe
| | Wynik | Dowód |
|---|---|---|
| F1 | ✅ | `test_ui_142.test_c_…` – z menu i z FOREX, `#/system?p=…`, ESC zamyka i wraca na ekran źródłowy |
| F2 | ✅ | Panele osadzają te same komponenty 1.41 (`SettingsModal`, `ModeDialog`, `PowerDialog`) – identyczne żądania |
| F3 | ✅ | `stop-button`, `chip-exec`, `chip-mode` na każdym ekranie (test) |
| F4 | ✅ | `E1_pierwsze_uruchomienie_ustawienia.png` (Ustawienia po intro) |

### G. Przebudowa
| | Wynik | Dowód |
|---|---|---|
| G1 | ✅ | `release/PepeMarketWizard_1_42_0.zip` (1364 pliki, sha256 `0b422f94…`), `release/PepeMarketWizard_DESKTOP_1_42_0.zip` (sha256 `08cc2d07…`); `verify_release.py --all` OK |
| G2 | ⚠️ | exe zbudowane (zasób wersji 1.42.0, splash z WEJDŹ wbudowany); uruchomienia na Windows nie da się wykonać w tym kontenerze – DO WERYFIKACJI u użytkownika |
| G3 | ✅ | skan paczek: brak `archive/`, `update_1_42/`, `.venv*`, starych zasobów UI; skan sekretów build_release OK |
| G4 | ✅ | `go test` + `GOOS=windows go vet` OK |

### E. Jakość
| | Wynik | Dowód |
|---|---|---|
| E1 | ✅ | `tsc -b` / `npm run build` bez błędów; 106 plików testów – wszystkie OK (uruchamiane plik po pliku) |
| E2 | ✅ | konsola bez błędów (testy); po 10 cyklach menu ↔ FOREX: **1** żywy kontekst WebGL (22 utworzone i zwolnione przez `WEBGL_lose_context`) |
| E3 | ✅ | `pmw.motion = reduced` – menu od razu, przelot skrócony (S4 §5) |
| E4 | ✅ | planety i przyciski są `<button>` w kolejności tabulacji, ESC = wstecz |
| E5 | ⚠️ | średni czas klatki na SwiftShader (CPU, nie GPU): menu 200 ms, FOREX 432 ms, CHARTS 254, SIGNALS 300, MODELS 393, ROI 285 ms. Wartości dotyczą renderera programowego kontenera; na GPU DO WERYFIKACJI |
| E6 | ✅ | 1.42.0 w `version.py`, `build_release.py`, `make_manuals.py`, `winres.json`, `CHANGELOG.md` |

Rozmiar `frontend/dist`: 1.41.0 = 9 070 KB → 1.42.0 = 1 496 KB (w tym film 650 KB).

## Zdjęcie ograniczeń (decyzja użytkownika: „Modele: OBSERVE → ASSIST, 90 strategii: zlecenia FOREX”)
* Jednorazowa migracja `data/upgrade/1.42.0.json`: Chronos-2 / Granite TTM / TiRex-2 × ACTIVE / SCALPING / HEDGING oraz Kronos × SCALPING / HEDGING
  → ASSIST (DIRECT_USER_REQUEST, bez wymyślonego raportu; REQUIRED użytkownika zostaje). W demie: 11 zmian, 0 błędów.
* Koszyki FX → istniejąca ścieżka SH (`sh/service.py`: `basket_setups`, `basket_su`, `basket_profile`). W demie (PAPER, ścieżka główna SH):
  sygnał `FX_SCALP_10` SELL M1 → plan `PL-BK01f2…` **OPEN** w PAPER, poziomy wejścia/SL/TP z planu koszyka; wpis w `executions`.
* Testy: `test_pmw142_models.py`, rozszerzony `test_pmw141.TestBasketService`, zaktualizowany `test_tsfm_bot.py`.
* Bez zmian: tryb wykonania rachunku, STOP, limity ryzyka, dźwignia, SL; CRYPTO / OTC ręcznie.

## Pliki
* Dodane: `frontend/src/features/{cinematic,forex,system}/…`, `frontend/public/assets/cinematic/intro.mp4`, `tests/test_ui_142.py`,
  `tests/test_forex_format.py`, `tests/js/forex_format.test.mjs`, `tests/test_pmw142_models.py`, `tests/_demo_server.py`, `docs/AKTUALIZACJA_1_42_PL.md`.
* Zmienione: `App.tsx`, `main.tsx`, `router.ts`, `components/Dialogs.tsx`, `desktop/splash.html` (+ komentarze Go), `backend/masterquo/api/app.py`
  (raport MC), `baskets/{service,catalog}.py`, `sh/service.py`, `kronos/{settings,predictions,service}.py`, `tsfm/{settings,predictions}.py`,
  `upgrade/migrate.py`, `runtime.py`, `tools/build_release.py`, wersje.
* Przeniesione: stary UI i jego zasoby → `archive/ui_1_41/frontend_src|frontend_public`; 26 testów UI + `test_nc_panel`, `test_chartlab_calc`
  (+ js), część przeglądarkowa `test_sh_api` → `archive/ui_1_41/tests/`.

## Odstępstwa
* Zakładka „Wygląd” (motywy 1.41) usunięta z Ustawień – motywy dotyczyły starego UI. Endpoint `/api/v1/appearance/*` zostaje (zwraca `NONE` dla
  wbudowanych GIF-ów 1.41).
* Plany FX_HEDGE wchodzą do SH jako rodzina SCALPING (bez nogi hedge SH) – hedging koszyka pozostaje w planerach hedge koszyków.

## DO WERYFIKACJI
* G2: start exe na Windows (okno startowe → WEJDŹ → intro → menu → FOREX → STOP).
* E5: czasy klatki na GPU.
* Nowe wejścia z koszyków FX wymagają w panelu Tryb pracy ścieżki głównej SCALPING / HEDGING i trybu z wykonaniem.

## Wycofanie
Paczka 1.41.0 w `release/` (dane zostają). Same role modeli → OBSERVE w panelu MODELS/API; same zlecenia koszyków →
`baskets/settings.json: profiles.FOREX_MT5.execution = "SIGNALS_ONLY"`. Kod 1.41 UI: `archive/ui_1_41/` albo commit sprzed 1.42 na gałęzi.
