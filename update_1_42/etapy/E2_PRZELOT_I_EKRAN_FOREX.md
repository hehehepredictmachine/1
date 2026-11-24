# E2 – Przelot w kulę FOREX i ekran FOREX

**Wzorzec:** `referencje/REF_B_kula_forex_i_ekrany.html`, części: shadery, stan, fazy, oś czasu, tło, efekty paneli, planety, droga mleczna, pętla.
**Zrzuty:** `S01_menu_kula_forex.png`, `S02_przelot_1.png`, `S02_przelot_2.png`, `S03_ekran_forex.png`.

## Zakres
1. `features/forex/engine/shaders.ts`: wszystkie stałe GLSL z REF_B 1:1. `SHAPE` zawiera już kształt planety FOREX z menu v1.1 (pierścień + księżyce). Nie wracaj do starej „membrany”.
2. `engine/forexEngine.ts`: stan `S`, `CFG`, fazy `menu → dive → forex → surface`, `timeline`, `bgPhase`, `tick`, `resize`, `dispose`.
   - Faza `menu` w aplikacji służy tylko jako **punkt startu przelotu**: kula w pozie podanej przez menu (S4 §2), bez podpisu „01 FOREX”, i od razu `startDive()`.
3. `engine/panels.ts`:
   - MODEL A to kolumna pierścieni (`RING_V`, 16k punktów, impuls w dół);
   - MODEL B to wir z planetą (`VOR_V`, 22k, łańcuchy do rdzenia);
   - `STATUS` / `updatePanel` / `drawPanel` / `triggerResult` jak w REF_B;
   - **usuń** demonstracyjne źródło stanu (sekcja „demonstracyjne źródło stanu modeli”) i podłącz dane z S3 §1;
   - `triggerResult` wywołujesz tylko przy prawdziwym zdarzeniu.
4. `engine/planets.ts` + `milkyWay.ts`: 4 planety (shader `PLANET_V` z 4 rodzajami: CHARTS, SIGNALS, MODELS, ROI), `HOLE_F`, `HALO_F`, podpisy (`.plabel`), przeciąganie i obrót, hover, `choosePlanet` → zmiana trasy na `#/forex?s=…` (otwarcie ekranu robi E3–E6; do tego czasu planeta tylko pulsuje i ogłasza „ekran w przygotowaniu”).
5. `ForexScene.tsx`:
   - jeden komponent dla `#/forex` i `#/forex?s=…`;
   - zmiana `s` **nie** remontuje sceny;
   - przycisk wstecz (lewy dół) → `surface` → `#/menu`;
   - ESC działa jak wstecz.
6. Przejście z menu:
   - po `onForexReady` z E1 → `navigate("forex", { params: { from: "menu" } , replace: true })`;
   - `ForexScene` z `from=menu` startuje przelot z pozy kuli, a parametr `from` jest potem usuwany z hasha (`replace`);
   - wejście bez `from` (link bezpośredni) pokazuje ekran FOREX z wejściem paneli, bez przelotu.
7. Nagłówek / informacje:
   - aktywny profil i ostrzeżenie (S2 §4);
   - znacznik SYNTETYCZNE przy `s.synthetic`;
   - żadnych innych napisów na ekranie FOREX poza podpisami planet (decyzja użytkownika: „usuń wszystkie napisy”, potem „podpisz planety i kulę”).

## Kryteria odbioru E2
- S5 B1–B5.
- Zrzuty przelotu i ekranu porównane z S01–S03.
- Panele: w raporcie opisz, jakie zdarzenie z API wywołało ostatni impuls (czas, endpoint).
- Ograniczenie ruchu: przelot zastąpiony przenikaniem ≤ 300 ms.
