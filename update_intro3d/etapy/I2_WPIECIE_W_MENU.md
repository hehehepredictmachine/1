# I2 – Wpięcie w menu główne

**Wzorzec:** REF_C (menu v1.2 z intro 3D), SC3 §3–5.

## Kroki
1. Markup `#cinema`: `<canvas id="intro" role="img" aria-label="…">` zamiast `<video>` (tekst aria z REF_C).
2. Silnik menu: obiekt intro = `new Intro3D(canvas)` (jak `video=new PMW_Intro3D($('#intro'))` w REF_C). Faza `boot` → `playIntro()` → `ended` → `enter()` → menu – bez zmian logiki.
3. Ukryj przycisk dźwięku; usuń kod `video.muted`-zależny od audio tylko jeśli nie ma innego użycia (zostaw `muted` jako właściwość no-op).
4. `introGate` bez zmian (raz na sesję, webdriver, ograniczenie ruchu).
5. `dispose` menu wywołuje `intro.dispose()`; przy odmontowaniu trasy `#/menu` kontekst intro jest zwalniany. Powtórka intro („Odtwórz intro”) – ponowne `play()` od `currentTime = 0` na tej samej instancji (jak wzorzec).
6. Film: `frontend/public/assets/cinematic/intro.mp4` → `archive/cinematic/intro.mp4`. Usuń odwołania do pliku z kodu i z testów/kryteriów pełnego pakietu (S1, S4, S5 – dopisz notkę w raporcie, że A1 dotyczy teraz intro 3D).
7. Tryb testowy `window.__PMW_TEST__.intro.seek(t)` (SC3 §5).

## Kryteria I2
- [ ] Pełny przebieg: start → intro 13,8 s → menu; „PRZEJDŹ DO MENU” w dowolnej chwili → menu.
- [ ] Zrzuty: klatka 10,6 s i menu po wejściu obok REF_C.
- [ ] Brak `intro.mp4` w `frontend/dist`.
