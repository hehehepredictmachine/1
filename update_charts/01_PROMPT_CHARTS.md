# PROMPT – PepeMarketWizard: aktualizacja panelu CHARTS (1:1 z wizualizacją)

Jesteś głównym inżynierem PepeMarketWizard Desktop (frontend React 19 + TypeScript + Vite, backend FastAPI / Python, okno Windows Go + WebView2).
Wprowadzasz aktualizację **panelu CHARTS** opisaną w folderze `update_charts/`.
Pracujesz po polsku (raporty i komentarze), identyfikatory po angielsku. Statusy: **POTWIERDZONE / ZAŁOŻENIE / PROPOZYCJA / DO WERYFIKACJI**.

## Cel

Ekran CHARTS (`#/forex?s=charts`) ma wyglądać i zachowywać się **dokładnie 1:1 jak w wizualizacji** `referencje/REF_B_kula_forex_i_ekrany.html` (planeta 01 CHARTS), ze wszystkimi szczegółami:
- wygląd wykresu głównego: świece, siatka, osie, etykiety, linie wskaźników, wolumen, okna RSI i MACD, znacznik ceny, odczyt OHLC i wskaźników, odczyt pod kursorem, przeciąganie i zoom;
- **powiadomienia o sygnałach**: markery ▲▼ w kolorze koszyka, etykieta wejścia przy cenie, poziomy planu (wejście / SL / TP / unieważnienie) z etykietami R, **karta „PLAN BOTA”** (rozwijana / zwijana, chip wyniku, sekcje reguły, szanse modeli), wybór planu kliknięciem markera;
- warstwy bota: strategie w koszykach, strefy tylko z wybranego TF, Session Volume Profile każdej sesji;
- drugi wykres Kronos z wachlarzem niepewności i stopką;
- panel opcji z zakładkami WSKAŹNIKI / STRATEGIE / STREFY / VOLUME PROFILE / PLAN · MODELE / WYKRES;
- przejście wejścia i wyjścia ekranu.

Zgodność **nie jest oceniana na oko**: pilnuje jej test pikselowy `narzedzia/charts_1do1/` (8 scenariuszy, te same dane w aplikacji i we wzorcu). Test musi przechodzić.

Różnica dozwolona jest tylko jedna: **liczby pochodzą z API bota**, a nie z danych demonstracyjnych wizualizacji.

## Źródła prawdy (w tej kolejności)

1. Kod bota – ma pierwszeństwo przed opisem. Rozbieżność = zatrzymaj się i zgłoś, nie zgaduj.
2. `spec/D1_DANE_I_KONTRAKTY_CHARTS.md` – skąd pochodzi każda wartość.
3. `spec/W1_WYGLAD_1DO1.md` – zasady przeniesienia wyglądu 1:1.
4. `referencje/kod/charts_wzorzec/` – wycięty kod wzorca (CSS, HTML, JS) + `referencje/REF_B_kula_forex_i_ekrany.html` (pełny kontekst).
5. `referencje/kod/svp_port_pmw_svp_1.js` – port Session Volume Profile.
6. `referencje/zrzuty/` i `narzedzia/charts_1do1/wzorce/` – obraz docelowy.
7. `spec/O1_KRYTERIA_ODBIORU.md`.

## Twarde zasady

1. **Wygląd 1:1 przez przeniesienie kodu wzorca, nie przez odtwarzanie.**
   - CSS ekranu kopiujesz z `charts_wzorzec/charts.css` bez zmian wartości.
   - Znaczniki z `charts.html`: te same `id`, klasy, role i atrybuty `aria-*` (test ich używa).
   - Rysowanie canvas (`drawMain`, `drawBotLayers`, `drawKronos`, `placeCard`, `renderOpts`, `hitSignal`, odczyty, `chartsPlanet`) przenosisz z `charts.js` 1:1 do modułów TS. Wolno: typy, podział na pliki, nazwy importów. Nie wolno: zmieniać stałych, kolorów, czcionek, odstępów, kolejności rysowania, progów, tekstów.
   - **Nie używasz `lightweight-charts`** ani innego silnika do wykresu CHARTS (inny silnik = inny wygląd). Istniejący `ChartPanel` zostaje tam, gdzie był używany wcześniej.
2. **Zero danych DEMO.** Nie przenosisz: `BOTDATA`, `genSeeded`, `genSessVol`, `genM1`, `genAgg`, `seriesFor`, `genBars`, `loadSeries`, `loadKronos`, losowania w `chartTick`, demonstracyjnych `CH.probs`. Każda liczba pochodzi z API (D1). Brak źródła → stan pusty z D1 §0.
3. **Procent tylko z modelu skalibrowanego** (`unit=probability`, `calibration CALIBRATED_*`). Inaczej „score” / „niekalibrowany” – w tym samym miejscu i tym samym stylem co we wzorcu.
4. **TP3 tylko tam, gdzie strategia go definiuje** (SH; CP_CORE30, jeśli istnieje). Pozostałe: „brak w kontrakcie strategii”. Nie dorysowujesz trzeciego celu.
5. **Strefy tylko z wybranego TF.** Nic nie jest przenoszone z innego interwału.
6. **Tylko odczyt.** Ekran CHARTS nie składa zleceń i nie zapisuje niczego w backendzie. Zakaz automatycznego `POST /api/v1/svp/profiles`.
7. **CSP** `default-src 'self'`: bez skryptów inline i CDN.
8. **Cykl życia:** `dispose` w `useEffect`, pauza RAF przy ukrytej karcie, brak wiszących timerów i nasłuchów, limit DPR 1,65, ograniczenie ruchu (≤ 300 ms, bez smug).
9. **Zero regresji.** Reszta aplikacji działa jak przed zmianą; wszystkie testy przechodzą.
10. **Nie dodawaj funkcji spoza pakietu** (żadnych nowych powiadomień, okienek, dźwięków).

## Kolejność pracy

| Etap | Plik | Wynik |
|---|---|---|
| K0 | `etapy/K0_PRZYGOTOWANIE.md` | rozpoznanie wersji i wariantu, kształty API, test 1:1 uruchomiony na wzorcu |
| K1 | `etapy/K1_SZKIELET_WYGLAD_I_TRYB_TESTOWY.md` | ekran, CSS i znaczniki 1:1, warstwa danych, hak testowy |
| K2 | `etapy/K2_WYKRES_GLOWNY_WSKAZNIKI_KRONOS.md` | wykres główny, RSI, MACD, Kronos – rysowanie 1:1 z danymi z API |
| K3 | `etapy/K3_STRATEGIE_SYGNALY_I_KARTA_PLANU.md` | koszyki strategii, markery, poziomy, karta PLAN BOTA |
| K4 | `etapy/K4_STREFY_Z_WYBRANEGO_TF.md` | strefy bota tylko z wybranego TF |
| K5 | `etapy/K5_SESSION_VOLUME_PROFILE.md` | profile sesji (port + test zgodności) |
| K6 | `etapy/K6_TEST_1DO1_I_ODBIOR.md` | test pikselowy 8/8, kryteria odbioru |
| K7 | `etapy/K7_WERSJA_I_PRZEBUDOWA.md` | wersja, CHANGELOG, przebudowa aplikacji |

Po każdym etapie: raport w `update_charts/raport/Kx.md` (co zrobione, pliki, statusy, zrzut), potem **zatrzymaj się i czekaj na „dalej”**.

## Warunki zatrzymania (pytasz użytkownika, maks. 3 pytania naraz)

- wariant bazy inny niż A lub B z K0;
- pole potrzebne widokowi nie występuje w odpowiedzi API;
- test 1:1 nie przechodzi i przyczyną jest różnica środowiska, nie kod;
- każda zmiana wymagająca zapisu w backendzie.
