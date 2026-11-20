# SC3 – Integracja z aplikacją

## 1. Moduł
```
frontend/src/features/intro3d/
  intro3d.ts      ← intro.js (klasa Intro3D, TL)
  figure.ts       ← figure2.js
  galaxy.ts       ← galaxy.js
  assets/body.bin.gz, assets/skeleton.json  ← bajt w bajt z wzorca
  motion.ts       ← motion.js
  planets.ts      ← planets.js
  textures.ts     ← textures.js
  index.ts        ← eksport: Intro3D, INTRO_DURATION
```
Zależności: `three@0.187.0`, `fflate@0.8.2` (dokładnie). `body.bin.gz` dołączasz jako dane binarne (import binarny w bundlu albo `fetch` z `'self'`; przy `fetch` `readyState` = 4 dopiero po zbudowaniu sceny, a `play()` czeka). Importy dodatków z `three/examples/jsm/...` (lub `three/addons/...` – ta sama wersja).

## 2. API (jak w wzorcu – zgodne z `<video>`)
`new Intro3D(canvas, { pixelRatioCap = 1.65, shadows = true, reflections = true })`
- `play(): Promise<void>`, `pause()`, `currentTime` (get/set → ustawienie rysuje klatkę), `duration` (13,8), `paused`, `muted` (zawsze true), `readyState` (4 po zbudowaniu sceny), `style` (styl płótna);
- zdarzenia: `ended`, `error` (emituj `error`, gdy budowa sceny lub kontekst WebGL zawiedzie);
- `seek(t)`, `resize()`, `dispose()`.

## 3. Wpięcie w menu główne
Menu (z pełnego pakietu: `features/cinematic/menuEngine.ts`, wzorzec REF_A) używa obiektu wideo przez: `play`, `pause`, `currentTime`, `duration`, `muted`, `readyState`, `style.transform/filter`, zdarzenia `ended`/`error`. Intro3D ma ten sam kontrakt, więc:
- `#cinema` zawiera `<canvas id="intro">` zamiast `<video>` (aria-label jak w REF_C);
- w silniku menu `video = new Intro3D(canvasEl)` (dokładnie jak w REF_C: `video=new PMW_Intro3D($('#intro'))`);
- faza `enter` menu bez zmian (przyciemnia, powiększa i rozmywa płótno intro, wprowadza planety menu);
- przycisk „Dźwięk oryginalnego intro” ukryty; „Odtwórz intro”, klawisz R, Ctrl+Alt+B, „PRZEJDŹ DO MENU”, Esc – bez zmian;
- bramka intro (`introGate`): raz na sesję, pomijane przy `navigator.webdriver` (chyba że `pmw.cinematic.force=1`) i przy ograniczeniu ruchu – bez zmian;
- `intro.mp4` → `archive/` (nie w `frontend/public`, nie w `dist`).

## 4. Okno Windows (WebView2)
Ekran powitalny `desktop/splash.html` (przycisk „WEJDŹ”) bez zmian. Intro gra w panelu po wejściu (`?pmw_joined=1`), jak dotąd film. DO WERYFIKACJI: WebGL2 w WebView2 na komputerze użytkownika (raport I3).

## 5. Tryb testowy
Tylko w trybie testów (`import.meta.env.MODE === 'test'` lub `?pmw_test=1` w buildzie deweloperskim; w produkcji nie istnieje):
```ts
window.__PMW_TEST__.intro = { seek(t: number): Promise<void> }  // wstrzymuje odtwarzanie, rysuje klatkę t, rozwiązuje po narysowaniu
```
Strona testowa ma pokazywać menu w fazie `boot` z intro na pełnym ekranie, jak REF_C po otwarciu (elementy nakładki menu – etykieta, „PRZEJDŹ DO MENU”, narzędzia – są w obu, więc porównanie obejmuje cały ekran).
