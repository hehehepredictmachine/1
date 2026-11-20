# S1 – Architektura i pliki

## 1. Stan bazowy 1.41.0 (POTWIERDZONE w kodzie)

| Element | Gdzie | Rola dziś |
|---|---|---|
| Launcher „JOIN THE CULT” (przeglądarka) | `frontend/src/features/cult/Launcher.tsx`, `launcher.css`; bramka w `App.tsx` (`launcherNeeded()`, `NEED_LAUNCHER`) | pierwszy ekran sesji w przeglądarce |
| Launcher okna Windows | `desktop/splash.html` (go:embed w `desktop/app_windows.go`, akcja `join`) | małe okno startowe, czeka na JOIN THE CULT, potem otwiera panel z `?pmw_joined=1` |
| Boot intro 1.39 | `frontend/src/features/galaxy/BootScreen.tsx`, `boot.css`; montowany w `main.tsx` | 8,5 s intro „$PEPEMARKET WIZARD” |
| Menu główne Galaxy V2 | `features/galaxy/GalaxyMenu.tsx`, `galaxyEngine.ts`, `galaxyMarkup.ts`, `galaxy.css`; trasa `#/menu` w `CULT_PAGE_IDS` | 7 planet, edytor „Projektuj” |
| Routing | `frontend/src/router.ts` (hash, `parse()`, `navigate()`, `Page`, `PAGES`, `*_PAGE_IDS`, `SCREEN_MAP`) | 2. segment ścieżki tylko dla `warunki`; reszta przez `params` |
| Dane | `frontend/src/api.ts` (`apiGet`, `apiSend`), `store.tsx` (jeden WebSocket: `quote`, `bar`, `bar_closed`, …) | |
| Wykresy | `lightweight-charts 5.2.1`, `components/ChartPanel.tsx`, `ChartToolbar.tsx`, `chartprefs.ts`, `features/towers/WtcTower.tsx` | |
| Serwowanie | backend: `/assets/{path}` → `frontend/dist/assets` (dowolny typ pliku, cache immutable); `/static/` tylko obrazy | |
| CSP | `default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:` | `media-src` dziedziczy `'self'`, więc **wideo w data: URI nie zadziała** |

## 2. Docelowa struktura (PROPOZYCJA, nazwy możesz dopasować do konwencji projektu)

```
frontend/public/assets/cinematic/intro.mp4          ← z update_1_42/zasoby/cinematic/intro.mp4 (bez zmian)
frontend/src/features/cinematic/
  CinematicMenu.tsx        komponent trasy #/menu: intro + menu 3 planet + ekran „Tryb w przygotowaniu” (CRYPTO/OTC)
  menuEngine.ts            port skryptu REF_A: mountMenu(root, opts) → dispose(); WebGL + renderer CPU
  menuShaders.ts           GLSL z REF_A 1:1 (vertexShared, particleFrag, meshFrag, starVert/Frag, streakVert/Frag)
  introGate.ts             kiedy grać intro (raz na sesję, pominięcie, powtórka, reduced motion, webdriver)
  cinematic.css            style z REF_A (masthead, .mode, #tools, #cinema, #selected…)
frontend/src/features/forex/
  ForexScene.tsx           JEDEN komponent dla #/forex i #/forex?s=…: canvas WebGL + warstwy DOM; nie remontuje się przy zmianie s
  engine/
    forexEngine.ts         stan S, fazy (menu → dive → forex → surface), pętla tick, resize, dispose, contextlost
    shaders.ts             GLSL z REF_B 1:1 (SHAPE, PART_*, OSTREAK_*, STAR_*, SSTREAK_*, QUAD_V, SOLID_F, COMP_F, HSV, RING_V,
                           SPRITE_F, VOR_*, DYN_V, FX_F, DARK_F, PLANET_V, HOLE_F, HALO_F, MW_*)
    panels.ts              MODEL A (RING_V – kolumna warstw), MODEL B (VOR_V – wir z planetą), statusy, impulsy
    planets.ts             4 planety (PLANET_V/HOLE_F/HALO_F), layoutPlanets, przeciąganie, hover, wybór
    milkyWay.ts            MW_V/MW_F, layoutMilkyWay, catmull
    subscreens.ts          rejestr ekranów {inMs,outMs,planet(cms),draw(cms,dt)}, subOpen/subClose – jak SCREENS w REF_B
  screens/
    charts/  ChartsScreen.tsx, chartsCanvas.ts, chartsData.ts
    signals/ SignalsScreen.tsx, signalsCosmos.ts, signalsData.ts
    models/  ModelsScreen.tsx, modelsObservatory.ts, modelsData.ts
    roi/     RoiScreen.tsx, roiVortex.ts, roiData.ts
  forex.css                style ekranów z REF_B (przeniesione 1:1, z prefiksami klas jak w REF_B: ch-, sg-, mb-, ro-)
frontend/src/features/system/
  SystemDrawer.tsx, SettingsPanel.tsx, ModePanel.tsx, StopPanel.tsx, DiagnosticsPanel.tsx, ExecStatus.tsx, system.css   (S6)
frontend/src/core/        logika wydzielona ze starego UI, której używa nowe (wskaźniki, warstwy wykresu, formatowanie, pomocnicze z dialogów)
archive/ui_1_41/          cały stary interfejs (poza buildem i paczkami)
```

### Mapa wzorca REF_B → moduły (gdzie szukać w pliku referencyjnym)

| Sekcja REF_B (komentarz w kodzie) | Funkcje / stałe | Moduł docelowy |
|---|---|---|
| `/* shadery */` | stałe GLSL | `engine/shaders.ts` |
| `/* stan */`, `/* fazy */`, `/* oś czasu przejścia */`, `/* tło: cykl 66 s */` | `S`, `CFG`, `setPhase`, `startDive`, `surface`, `timeline`, `bgPhase`, `cores` | `engine/forexEngine.ts` |
| `/* efekty paneli */` | `panels`, `STATUS`, `updatePanel`, `drawPanel`, `triggerResult`, `spawnChain`, `fx`, `dark` | `engine/panels.ts` |
| planety, droga mleczna | `planets`, `layoutPlanets`, `drawPlanets`, `pose`, `choosePlanet`, `layoutMilkyWay`, `drawMilkyWay`, `catmull` | `planets.ts`, `milkyWay.ts` |
| `/* pętla */` | `tick`, `wake` | `forexEngine.ts` |
| CHARTS | `CH`, `L`, `computeAll`, `drawMain`, `drawKronos`, `placeCard`, `renderOpts`, `chartsPlanet` | `screens/charts/*` (**`genBars`, `loadSeries`, `loadKronos` NIE – zastąp API**) |
| SIGNALS | `SG`, `MODEL_REG`, `KIND_PL`, `renderSignalsUI`, `renderDetail`, `renderGates`, `drawSignals`, `signalsPlanet` | `screens/signals/*` (**`genSignals`, `evalModels` NIE – zastąp API**) |
| MODELS & BACKTEST | `MB`, `MB_STATE`, `renderModelsUI`, `renderModelDetail`, `renderMbCenter`, `svgBars`, `svgRel`, `drawModels`, `modelsPlanet`, `mbIntro` | `screens/models/*` (**`genModels` NIE**) |
| ROI | `RO`, `roAgg`, `renderRoiUI`, `renderRoiTable`, `drawRoi`, `drawRoiEquity`, `roiPlanet`, `roStars`, `roIntro` | `screens/roi/*` (**`genRoi` NIE**; `roAgg` tylko jako formatowanie – agregaty liczy backend) |
| `SCREENS`, `subOpen`, `subClose` | rejestr i przejścia | `engine/subscreens.ts` |
| `PMW_PREVIEW._seek/_charts/_signals/_models/_roi` | haki testowe | zostaw podobne haki **tylko w trybie testowym** (np. `window.__PMW_TEST__`), bez wpływu na produkcję |

## 3. Zasady implementacji

1. **React jako rama, renderer jako moduł imperatywny.** Komponent montuje silnik w `useEffect` (`const dispose = mountX(el, opts); return dispose;`), tak jak robi to dziś `GalaxyMenu` z `mountGalaxy`. Panele z danymi (listy, tabele, szczegóły) są w React. Canvasy 2D/WebGL rysują tylko grafikę.
2. **Jeden kontekst WebGL na ekran.** `ForexScene` trzyma jeden canvas dla tła, planet, paneli i drogi mlecznej. Ekrany CHARTS/SIGNALS/MODELS/ROI mają własne canvasy 2D (jak w REF_B). Ich wykresy cenowe mogą używać `lightweight-charts` (patrz E3).
3. **Shadery 1:1.** Kopiujesz stałe tekstowe GLSL bez zmian matematyki. Wolno zmienić tylko nazwy uniformów/atrybutów, jeśli wymaga tego wspólny moduł, i trzeba to opisać w raporcie.
4. **Typy danych**: dla każdego ekranu `xxxData.ts` zawiera typy odpowiedzi API, adapter `toViewModel()` (czysta funkcja, testowalna) i hook `useXxx()` (polling GET lub zdarzenia store). Komponenty widoku nie wołają `fetch` bezpośrednio.
5. **Cykl życia**:
   - pauza RAF przy `document.hidden`;
   - `webglcontextlost` / `restored` jak w REF_A (komunikat i ponowna inicjalizacja);
   - `dispose` usuwa bufory, programy i nasłuchy (`AbortController`).
   - Nie zostawiaj wiszących `setTimeout`/`setInterval` po odmontowaniu.
6. **Renderer CPU** (fallback bez WebGL) jest obowiązkowy tylko dla menu (REF_A ma go gotowego). Ekran FOREX bez WebGL pokazuje statyczny, czytelny układ: czarne tło, 4 przyciski-planety z podpisami i działające ekrany danych bez efektów. To ZAŁOŻENIE, bo REF_B nie ma renderera CPU.
7. **Wydajność**: liczby cząsteczek jak we wzorcach (menu 110k/94k/66k, kula FOREX `CFG.orbCount` 110k, panele 16k/22k). Przy `frameAvg > 28 ms` przez 3 s obniż DPR do 1 (jak `quality` w REF_A). Raportuj średni czas klatki na zrzutach z E8.
