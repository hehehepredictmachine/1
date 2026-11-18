# K3 – Strategie bota w koszykach, sygnały na wykresie, karta PLAN BOTA

**Wzorzec (`charts.js`):** `BK_ORDER`, `BK_INFO`, `BK_COL`, `BASKET_OF`, `SMETA`, `STR`, `RES_PL`, `resPL`, `idxOf`, `stratAvail`, `botIndex`, `sigVisible`, `pickPlan`, `drawBotLayers` (część sygnałów i poziomów), `hitSignal`, `placeCard`, `renderOpts` (zakładki STRATEGIE i PLAN · MODELE).
**Zrzuty:** `S04_charts.png`, `S04b_charts_zakladka_strategie.png`, `S04e_charts_m15_plan_bota.png`.

## Powiadomienia o sygnałach (1:1, bez nowych elementów)

**ZAŁOŻENIE:** „powiadomienie o sygnale” to dokładnie to, co pokazuje wzorzec:
1. **marker ▲ / ▼** przy świecy sygnału w kolorze koszyka (`BK_COL`) z identyfikatorem strategii;
2. **etykieta wejścia** przy cenie (np. „S03 LONG · WEJŚCIE 4055.88”) i znacznik SL;
3. **poziomy planu** (wejście, SL, TP1–TP3 z R, unieważnienie) w trybie OSTATNI / WYBRANY / WSZYSTKIE;
4. **karta „PLAN BOTA”** (`#sig-card`) przy cenie: nagłówek z strategią, kierunkiem i TF, chip wyniku (`resPL`), tabela poziomów, sekcja reguły (koszyk / S01–S12 / SH), szanse modeli, notka; klik w nagłówek zwija / rozwija;
5. klik w marker (`hitSignal`) wybiera plan; nowy sygnał z API pojawia się jako nowy marker, a karta przełącza się na niego według `pickPlan` (ostatni OTWARTY, jeśli nic nie wybrano);
6. komunikat `aria-live`: „Nowy sygnał <strategia> <kierunek> <TF>” (nie częściej niż co 5 s).
Żadnych dodatkowych okienek, dźwięków ani powiadomień systemowych.

## Zakres

1. **Katalog i kolejność koszyków:** `FX_SMC` (10), `FX_SCALP` (10), `FX_HEDGE` (10), `S01–S12`, `SH` (SCALPING / HEDGING). Katalog z `GET /api/v1/baskets/catalog` + opis strategii S01–S12 z istniejącego API strategii (`registry.describe()`), SH z konfiguracji `sh`. Mapowanie na `SMETA` – D1 §3.4.

2. **Sygnały** (filtr instrumentu i TF w UI):

   | Grupa | Endpoint | `src` |
   |---|---|---|
   | koszyki | `GET /api/v1/baskets/signals?basket=&limit=` | `BASKET` |
   | S01–S12 | `GET /api/v1/bot-signals?symbol=&limit=` (+ `/api/v1/setups`, jeśli etapy WATCH/EARLY są włączone) | `LEGACY` |
   | SH | `GET /api/v1/sh/signals?strategy=&tf=&symbol=&limit=` | `SH` |

   Każda strategia pokazuje sygnały **tylko na swoim TF sygnału** (`botIndex`); inny TF → wiersz z przyciskiem „→ M5”. SH oceniany co M1, pokazywany na TF ≤ M15.

3. **Wynik sygnału** (`res`, `hit`, `et`) – **tylko ze stanu w API** (cykl życia sygnału / planu). Jeśli API nie podaje wyniku, chip pokazuje stan z API (np. OTWARTY / WYGASŁY), a `hit` jest pusty. **Nie liczysz wyniku po stronie UI z przebiegu świec.**

4. **TP:** z planu strategii. `FX_*` i S01–S12 → TP1–TP2, w karcie TP3 „brak w kontrakcie strategii”. SH → TP1–TP3 z udziałami i BE.

5. **Stany niedostępności** (`stratAvail`) zamiast pustki: `FX_HEDGE` – plan ochrony, bez sygnałów wejścia; S01–S12 na BTC – `UNSUPPORTED_ASSET`; SH na BTC – status z konfiguracji SH; brak danych wejściowych – powód z API.

6. **Szanse modeli w karcie:** `GET /api/v1/models/predictions?instrument=` → wiersze `win` (Legacy ML) i `tp2` (SH tp_model) jak we wzorcu. Procent tylko przy `unit=probability` + `calibration` `CALIBRATED_*`; inaczej „—” i stan (NIEWYTRENOWANY / WYŁĄCZONY / NIEAKTUALNY / BŁĄD / niekalibrowany).

7. **Notka karty (produkcja):** zamiast tekstu podglądu: „Sygnał i plan z API bota. Wynik „<stan>” według cyklu życia sygnału w bocie. Szanse modeli: <źródło / stan kalibracji>.” – w tym samym elemencie `.note` i tym samym stylu. W trybie testowym: `fx.test_texts.cardNote`.

8. **Włączniki 1:1:** cały koszyk, pojedyncza strategia, „Sygnały strategii bota”, „Poziomy planu”, „Karta planu”, tryb poziomów OSTATNI / WYBRANY (domyślnie) / WSZYSTKIE. Ustawienia zapamiętywane lokalnie (`localStorage` w try/catch), bez zapisu w backendzie.

9. **Usunięte z wzorca jako demo, nie przenosisz:** „Pepe Scalp Plan”, „Pepe Hedge Plan”, sygnał S07 z atrapy, historia sygnałów z atrapy, „Poziomy AI”, jeśli nie mają źródła w API (wtedy wiersz „NIEDOSTĘPNE” jak `UNAVAIL`).

## Kryteria K3
- [ ] Scenariusze 1:1 `K1`, `K2`, `K5`, `K7`, `K8` przechodzą w całości (z kartą planu i markerami).
- [ ] Każda strategia ma wiersz w swoim koszyku ze stanem; TP3 tylko tam, gdzie strategia go definiuje.
- [ ] Klik w marker wybiera plan, klik w nagłówek karty zwija ją – zrzuty w raporcie obok wzorca.
- [ ] W ruchu sieciowym ekranu tylko GET.
