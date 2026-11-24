# PepeMarketWizard 1.39 – LIVE od startu, GARCH, intro, menu Galaxy V2, WTC PEPE 2.1

## 1. Tryb LIVE od startu (polecenie użytkownika)
| | 1.38 | 1.39 |
|---|---|---|
| Tryb po starcie | ostatni zapisany (domyślnie SIGNALS) | `execution.start_mode = "AUTO_LIVE"` (z prawdziwym terminalem) |
| Potwierdzenie rachunku | ręczne (podsumowanie w panelu) | `execution.live_autobind`: pierwsza decyzja na rachunku REAL wiąże LIVE (`LIVE_AUTOBIND`) |
| VALIDATED wariantów SC/HG | wymagane w AUTO_LIVE | ostrzeżenie w planie |
| Skalibrowany model zdarzeń | wymagany | ostrzeżenie |
| Znana prowizja | wymagana | ostrzeżenie (koszt jako scenariusz) |
| REDUCE na NETTING bez walidacji | blokada | dozwolone z ostrzeżeniem |
| STOP, limity ryzyka, spread, deduplikacja, uzgadnianie MT5, rachunek REAL, ścieżka główna | aktywne | **bez zmian – aktywne** |

Symulator (`--demo`, dane syntetyczne) nigdy nie przechodzi w LIVE. Wyłączenie: STOP / `start_mode: "SIGNALS"` / ROLLBACK.md 0d.

## 2. GARCH w PMW_HG09
`volatility_method`: `STD_LOGRET_60_M5` (domyślnie) albo `VOL_GARCH` (aktywny, zatwierdzony model rodziny VOL_GARCH – omega / alpha / beta
z artefaktu, sigma następnej świecy liczona przyczynowo na procentowych log-zwrotach M5). Bez gotowego modelu: `NO_DATA` / `GARCH_NOT_READY`.
Przełącznik: Strategie → Pakiet 20 strategii → „PMW_HG09 – zmienność”. Test: `tests/test_sh_pack.py::TestGarchHG09` (filtr = prognoza rodziny,
brak cichego zastępstwa, serwis czyta tylko zatwierdzony artefakt).

## 3. Migracja menu (paczka PepeMarketWizard_ALL_IN_ONE_UPDATE)
| Element | Przed (1.36–1.38) | Po (1.39) |
|---|---|---|
| `#/menu` | Neural City (stół neuronowy, 8 wież) | **Galaxy V2** – 7 planet, pełna sieć 21/21, edytor „Projektuj” |
| Neural City | `#/menu` | `#/neural-city` (przycisk „Neural City” w edytorze „Projektuj” Galaxy) |
| Intro | intro Neural City po JOIN THE CULT (`?intro=1`) | intro startowe `$PEPEMARKET WIZARD` (8,5 s) raz na sesję; JOIN THE CULT → Galaxy |
| Powrót z wież (logo / „← Galaxy”) | stół neuronowy | Galaxy |

Planeta → ekran: WTC PEPE → `#/pepe-wtc`, Brain Signal → `#/pepe-signal`, PEPE$BANK → `#/lightning`, PEPE$ROI → `#/profits`, Models → `#/modele`,
Signals → `#/sygnal`, Settings → `#/ustawienia`. Planeta bez sekcji: „Niepołączony moduł” (bez makiet). Układ: `localStorage["PMW_GALAXY_LIVE_V1"]`
(klucz referencji – projekty wyeksportowane z HTML referencji importują się bez zmian; nieznana trasa jest odrzucana).
Status w pasku: z backendu (`connection.state`, `synthetic`, tryb) – MT5 ONLINE · tryb / DEMO SIM · BEZ MT5 / MT5 OFFLINE / UNKNOWN.
Licencje: nie dotyczy (system licencji usunięty w 1.30).

Zasoby referencji w `frontend/public/galaxy/` (planety i tła WebP, `side_models.mp4`, GIF-y intro). Efekty są wizualne – nie czytają wyników modeli.
Testy: `tests/test_ui_galaxy.py` (intro: fazy 1,5 / 3,7 / 6,0 / 7,8 s, pomijanie, ponowne odtworzenie, ograniczone animacje; menu: 7 planet,
21/21, trasy, edytor, eksport / import, 1366×768 / 1440×900 / 1920×1080, brak błędów JS, brak zleceń).

## 4. WTC PEPE 2.1 – Chart Lab + Session Volume Profile
Sekcja „CHART LAB 2.1” pod wykresem głównym WTC PEPE; przycisk „⚙ CUSTOMIZE CHART” w pasku. Dane: `/api/v1/candles` (te same świece MT5 co
inne wykresy), biblioteka Lightweight Charts. Obliczenia (`chartlab/calc.ts`) są przyczynowe; SVP rozkłada wolumen (real / tick) równo na
High–Low świecy – przybliżenie OHLC, nie footprint; kierunek histogramu to proxy świec wzrostowych / spadkowych. Sesje w stałych godzinach UTC
(Asia 00–09, London 07–16, New York 12–21; bez czasu letniego). Impuls = największa |zmiana ceny| w oknie 3 / 5 / 8 / 12 świec (nie order flow).
Wizualizacja nie zasila silnika i nie składa zleceń. Testy: `tests/test_chartlab_calc.py`, `tests/test_ui_wtc_chartlab.py`.
Z paczki WTC 2.0/2.1 nie przeniesiono elementów opartych na danych syntetycznych (heatmapa płynności, ROI, korelacje, newsy) – bot ma
dla nich własne ekrany na prawdziwych danych albo ich nie ma.
