# PROMPT – PepeMarketWizard: nowa animacja startowa 3D

Jesteś głównym inżynierem PepeMarketWizard Desktop (frontend React 19 + TypeScript + Vite, backend FastAPI, okno Windows Go + WebView2).
Wprowadzasz **nową animację startową bota** opisaną w folderze `update_intro3d/`.
Pracujesz po polsku (raporty i komentarze), identyfikatory po angielsku. Statusy: **POTWIERDZONE / ZAŁOŻENIE / PROPOZYCJA / DO WERYFIKACJI**.

## Cel (decyzja użytkownika – POTWIERDZONE)

Animacja startu bota wygląda tak:
1. Z głębokiej czerni, **w galaktyce**, wyłaniają się **trzy męskie postacie 3D o ludzkiej sylwetce, w garniturach** (czarny garnitur, biała koszula, czarny krawat, rękawice, buty).
2. **Środkowa ma na twarzy czerwoną kominiarkę** (boczne – czarne).
   Chód wzorowany na animacji od użytkownika (`referencje/wzor_chodu_od_uzytkownika.gif`).
3. Idą w kierunku widza siedzącego przed ekranem i **zatrzymują się w połowie drogi**.
4. Pojawiają się **3 małe planety** (FOREX, CRYPTO, OTC – te same motywy co w menu).
5. **Środkowa postać kładzie na nie rękę.**
6. **Przejście do menu głównego.**

Wzorzec: `referencje/REF_C_intro_3d_i_menu.html` – działająca scena 3D w czasie rzeczywistym (three.js) połączona z menu głównym. Kod źródłowy wzorca: `referencje/kod/intro3d/src/` (`intro.js`, `figure2.js`, `motion.js`, `planets.js`, `galaxy.js`, `textures.js`), bryła postaci `src/assets/body.bin.gz` + `skeleton.json` i jej generator `tools/build_body.mjs`.
Animacja ma w aplikacji wyglądać **1:1 jak wzorzec** – pilnuje tego test klatek `narzedzia/intro_1do1/` (9 chwil osi czasu). Wzorzec porównany sam ze sobą daje 0 % różnicy, a zmiana jasności jednego światła o 11 % daje już błąd.

**ZAŁOŻENIE:** nowa animacja **zastępuje film intro** (`intro.mp4`). Film trafia do archiwum i nie wchodzi do wydania.

## Twarde zasady

1. **Przeniesienie kodu wzorca 1:1.** Moduły `referencje/kod/intro3d/src/*.js` przenosisz do TypeScript bez zmian liczb, kolejności operacji, shaderów, czasów osi, kolorów i świateł. Wolno: typy, nazwy importów, podział plików, `dispose`. Nie wolno: „poprawiać” wyglądu.
2. **three.js `0.187.0`** i **fflate `0.8.2`** (dokładnie, jak we wzorcu – `package.wzorzec.json`), z npm, w bundlu Vite. Żadnych CDN (CSP `default-src 'self'`). Bryłę postaci (`body.bin.gz`) **kopiujesz bajt w bajt** – nie generujesz jej ponownie.
3. **Deterministyczność:** każda klatka jest funkcją czasu `t` (`seek(t)` zawsze daje ten sam obraz). Bez `Math.random()` w czasie działania, bez `Date.now()` w scenie.
4. **Bez danych rynkowych i bez wywołań API** w animacji. Animacja nie składa zleceń i nie zapisuje niczego w backendzie.
5. **Bez dźwięku** (wzorzec go nie ma). Przycisk dźwięku z menu ukryty.
6. **Ograniczenie ruchu** (`prefers-reduced-motion`): animacja pomijana, od razu menu (jak dotąd).
7. **Cykl życia:** `dispose()` zwalnia geometrie, materiały, tekstury, render targety i kontekst WebGL; pauza przy ukrytej karcie; po wejściu do menu intro nie renderuje.
8. **Brak WebGL / utrata kontekstu:** komunikat jak w menu i przejście do menu. Aplikacja nie może utknąć na czarnym ekranie.
9. **Zero regresji** reszty aplikacji. Wszystkie testy przechodzą.
10. **Nie dodawaj elementów spoza scenariusza** (napisów, dźwięków, efektów, logo).

## Kolejność pracy

| Etap | Plik | Wynik |
|---|---|---|
| I0 | `etapy/I0_PRZYGOTOWANIE.md` | wariant bazy, kopia, test 1:1 uruchomiony na wzorcu |
| I1 | `etapy/I1_MODUL_INTRO_3D.md` | moduł `features/intro3d/` 1:1 z wzorcem |
| I2 | `etapy/I2_WPIECIE_W_MENU.md` | intro zamiast filmu, przejście do menu, pominięcie, powtórka |
| I3 | `etapy/I3_WYDAJNOSC_I_ODPORNOSC.md` | poziomy jakości, brak WebGL, pamięć, WebView2 |
| I4 | `etapy/I4_TEST_1DO1_I_ODBIOR.md` | test klatek 9/9, kryteria odbioru |
| I5 | `etapy/I5_WERSJA_I_PRZEBUDOWA.md` | wersja, CHANGELOG, przebudowa aplikacji i .exe |

Po każdym etapie: raport w `update_intro3d/raport/Ix.md` (co zrobione, pliki, statusy, zrzut), potem **zatrzymaj się i czekaj na „dalej”**.

## Dokumenty
- `spec/SC1_SCENARIUSZ_I_OS_CZASU.md` – oś czasu, kamera, światła, postprocessing.
- `spec/SC2_POSTACIE_I_PLANETY.md` – postacie (szkielet, ubiór, ruch, sięgnięcie) i planety.
- `spec/SC3_INTEGRACJA.md` – API modułu, wpięcie w menu, tryb testowy.
- `spec/O1_KRYTERIA_ODBIORU.md`.

## Warunki zatrzymania (pytasz użytkownika, maks. 3 pytania naraz)
- wariant bazy inny niż opisany w I0;
- test 1:1 nie przechodzi z przyczyn środowiska (nie kodu);
- średni czas klatki na docelowym komputerze > 33 ms także na najniższym poziomie jakości;
- każda decyzja usuwająca coś więcej niż film intro.
