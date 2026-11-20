# E1 – Cinematic startowy (film) i menu główne 3 planet

**Wzorzec:** `referencje/REF_A_menu_glowne_v1_1.html`. Plik jest kompletny i działa, więc otwórz go w przeglądarce i porównuj na bieżąco.
**Zrzuty:** `A1_menu_glowne_3_planety.png`, `A2_menu_wybor_trybu.png`.
**Decyzja użytkownika (POTWIERDZONE):** animacją startu bota jest **film intro** z REF_A, bez zmian treści.

## Zakres
1. `features/cinematic/menuShaders.ts`: przenieś 1:1 stałe GLSL z REF_A (`vertexShared` z planetami FOREX/CRYPTO/OTC, `particleFrag`, `meshFrag`, `starVert/starFrag`, `streakVert/streakFrag`).
2. `features/cinematic/menuEngine.ts`: port skryptu REF_A do modułu TS.
   - API: `mountMenu(root: HTMLElement, opts: { onChoose(mode: "FOREX"|"CRYPTO"|"OTC"): void; onForexReady(pose): void; reduced: boolean; playIntro: boolean; onSettings(): void }) => () => void`.
   - Zachowaj: fazy `boot → enter → menu → selecting → selected → returning`, renderer CPU (`setupSoftware`, `swPlanet`, `swDepthMesh`), przeciąganie, hover, klawiaturę, `webglcontextlost/restored`, `visibilitychange`, `dispose` z `AbortController`.
   - Usuń: wideo jako `data:` URI. Źródło to `<video src="/assets/cinematic/intro.mp4" preload="auto" playsinline muted>`.
   - `PMW_PREVIEW` zastąp hakiem testowym dostępnym tylko w trybie testów (S1 §2).
3. `features/cinematic/CinematicMenu.tsx`: komponent trasy `#/menu`. Markup z REF_A jako JSX (masthead, 3 przyciski `.mode`, `#menu-hint`, `#selected`, `#tools`, `#cinema` z wideo, `#skip`, `#video-start`, `#notice`, `#announcer`, `#renderer-error`) i style z REF_A w `cinematic.css` (prefiks `.cin-` albo zakres `.app-cinematic`, żeby nie kolidowały z resztą aplikacji).
4. `features/cinematic/introGate.ts`, czyli kiedy grać intro:
   - grać raz na sesję przeglądarki (`sessionStorage "pmw.cinematic.seen"`);
   - nie grać przy `navigator.webdriver`, chyba że `localStorage "pmw.cinematic.force"="1"` (jak dotychczasowy BootScreen, żeby testy UI nie czekały);
   - przy ograniczeniu ruchu przejść od razu do menu;
   - „Odtwórz intro”, klawisz R i Ctrl+Alt+B grają je ponownie.
5. Wybór trybu:
   - **FOREX**: faza `selecting` z REF_A, potem wywołanie `onForexReady(pose)`. Trasa `#/forex` (E2) przejmuje scenę i rusza przelot. Do czasu E2 tymczasowo pokaż ekran `selected` z napisem FOREX.
   - **CRYPTO / OTC**: ekran `selected` z REF_A, opis „Tryb w przygotowaniu – ten tryb pracy bota nie ma jeszcze ekranu.” i przycisk „POWRÓT DO MENU”. **Żadnych wywołań API.**
6. `App.tsx` i `router.ts`:
   - `#/menu` renderuje `CinematicMenu` w kontenerze `app-cinematic` (S2 §1);
   - bramki `Launcher` i `BootScreen` **jeszcze nie usuwaj** (to robi E8). Na czas E1–E7 wyłącz je flagą `CINEMATIC_START = true`, żeby nie dublowały intro.
7. Ikony paneli systemowych w `#tools`: do E7 otwierają istniejące dialogi, od E7 nowe panele (S6).

## Kryteria odbioru E1
- S5 A1–A6.
- Zrzut menu porównany z `A1_menu_glowne_3_planety.png`: układ, wielkości, pierścień FOREX przechodzi przed planetą, łańcuch CRYPTO, powłoka OTC.
- Konsola bez błędów, brak naruszeń CSP, 10× wejście/wyjście z `#/menu` bez wzrostu liczby kontekstów WebGL.
