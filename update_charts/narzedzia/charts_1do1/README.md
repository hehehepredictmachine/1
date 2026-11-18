# Test 1:1 ekranu CHARTS (aplikacja ↔ wizualizacja)

Aplikacja i wzorzec (`referencje/REF_B_kula_forex_i_ekrany.html`) dostają **te same dane** (`fixtures/*.json`) i są renderowane w tym samym Chromium (Playwright, 1600×900, DPR 1, strefa Europe/Warsaw). Skrypt porównuje zrzuty piksel po pikselu.

## Pliki
| Plik | Rola |
|---|---|
| `scenariusze.json` | 8 scenariuszy (TF, zakładka, instrument, karta zwinięta) |
| `fixtures/*.json` | dane scenariuszy w kształcie modelu widoku (spec D1 §3); **nie zmieniaj** |
| `wzorce/*.png` | zrzuty wzorca (podgląd w pakiecie; przed testem wyrenderuj je na swoim komputerze) |
| `wzorce/*.maski.json` | położenie znacznika źródła danych we wzorcu (jedyny maskowany obszar) |
| `wzorzec_z_ref_b.mjs` | renderuje wzorce (`--tylko-wzorce`) albo odtwarza fixtures z REF_B (bez flagi – tylko na prośbę użytkownika) |
| `porownaj.mjs` | test aplikacji (`--app <adres>`) albo szum wzorca (`--szum`) |
| `progi.json` | ekran ≤ 0,1 %, każdy obszar ≤ 0,3 % różnych pikseli (piksel różny = kanał różni się o > 40) |

## Wymagania
`npm i -D playwright` i `npx playwright install chromium` (w folderze, z którego uruchamiasz `node`).

## Kolejność
```
node update_charts/narzedzia/charts_1do1/wzorzec_z_ref_b.mjs --tylko-wzorce
node update_charts/narzedzia/charts_1do1/porownaj.mjs --szum
node update_charts/narzedzia/charts_1do1/porownaj.mjs --app "http://127.0.0.1:8000/#/forex?s=charts&pmw_test=1"
```
Wyniki: `update_charts/raport/charts_1do1/` (zrzut aplikacji, mapa różnic – czerwone piksele, `wynik.json`). Kod wyjścia 1 = test nie przeszedł.

## Kontrakt trybu testowego aplikacji
`window.__PMW_TEST__.charts.load(fixture)` → `Promise`, rozwiązana po narysowaniu pierwszej klatki:
- ekran CHARTS w stanie po przejściu, API / store / polling odłączone, czas na żywo zamrożony;
- dane z fixture przez ten sam model widoku co w produkcji;
- notka karty planu i znacznik nagłówka z `fixture.test_texts`.
Wzór działania: `PMW_PREVIEW._chartsLoad` w REF_B.

## Kalibracja (wykonana przy tworzeniu pakietu)
- wzorzec ↔ wzorzec: 0 % we wszystkich scenariuszach;
- REF_B jako „aplikacja” przez `__PMW_TEST__`: 0–0,02 % (OK 8/8);
- REF_B z tytułem większym o 0,5 px: nagłówek 3,7 % → BŁĄD 8/8;
- REF_B z kartą planu i zakładkami o 1 px większymi: BŁĄD 7/8 w obszarach karta / zakładki / opcje.

## Zegar wirtualny (1.42.5, decyzja użytkownika: szum = 0 %)
`vclock.mjs` jest wstrzykiwany do każdej strony testu (wzorce `--tylko-wzorce` i aplikacja `--app`): `performance.now`, `Date.now`
i znacznik klatki `requestAnimationFrame` stoją i przesuwają się tylko przez `window.__pmwRun(n)` (n klatek × 100 ms), `Math.random` ma ziarno.
Kroki scenariusza: strona → 15 klatek → (wzorzec: przejście do CHARTS / aplikacja: hak testowy) → 15 klatek → `load(fixture)` → 40 klatek → zrzut.
Wzorzec i aplikacja przechodzą tę samą sekwencję. `__szum.png` to niezależny drugi przebieg (inne opóźnienia rzeczywiste).
Wynik w tym środowisku: szum 0 % w 8/8 scenariuszach (wcześniej 0–0,026 % – pulsowanie znaczników, dobieganie skali osi, tło WebGL).
Wymaganie dla aplikacji: animacje CHARTS liczone z `performance.now()` / znacznika klatki (jak we wzorcu), bez własnych zegarów.
