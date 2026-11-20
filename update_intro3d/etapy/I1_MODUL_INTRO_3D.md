# I1 – Moduł intro 3D (port 1:1)

**Wzorzec:** `referencje/kod/intro3d/*.js`, specyfikacja SC1, SC2, SC3 §1–2.

## Kroki
1. `npm i three@0.187.0 fflate@0.8.2` (+ `@types/three` zgodne z wersją) w `frontend/`. Dokładne wersje (bez `^`). `isosurface` potrzebuje tylko generator (`tools/`), nie aplikacja.
2. Przenieś pliki do `frontend/src/features/intro3d/` jako TS (SC3 §1):
   - liczby, kolejność wywołań, shadery GLSL, ziarna generatorów, rozmiary tekstur i siatek – **bez zmian**;
   - `window.PMW_Intro3D` z wzorca **nie przenosisz** (eksport ES);
   - `body.bin.gz` i `skeleton.json` kopiujesz bez zmian; generator `tools/build_body.mjs` trafia do `tools/intro3d/` (przyszłe zmiany ubioru tylko za zgodą użytkownika, z nowymi wzorcami testu);
   - `debugCam` / `debugLight` z wzorca – tylko w trybie testowym albo usuń.
3. `dispose()` uzupełnij tak, by zwalniał: render targety `EffectComposer`, `UnrealBloomPass`, `Reflector` (`getRenderTarget().dispose()`), tekstury canvas, mapy cieni świateł (`light.shadow.map?.dispose()`), nasłuch `resize`, a na końcu `renderer.forceContextLoss()`.
4. Dodaj zdarzenie `error`: wyjątek w konstruktorze lub `webglcontextlost` na płótnie → `dispatchEvent(new Event('error'))`.
5. Testy jednostkowe (Vitest, jeśli projekt go ma):
   - `makeTrack` daje te same wartości przy przewijaniu w przód i w tył;
   - `TL.duration === 13.8`;
   - po `seek(13.8)` następuje `ended` przy `play()`.

## Kryteria I1
- [ ] Strona deweloperska z samym Intro3D (pełny ekran) wygląda jak REF_C (zrzuty t = 3, 7, 10,6 obok wzorca).
- [ ] Brak `Math.random`/`Date.now` w module (poza tym, co jest we wzorcu – wzorzec ich nie używa w scenie).
