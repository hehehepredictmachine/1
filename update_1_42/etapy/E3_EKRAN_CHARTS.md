# E3 – Ekran 01 CHARTS (`#/forex?s=charts`)

**Wzorzec:** REF_B sekcja „CHARTS” (`CH`, `L`, `computeAll`, `drawMain`, `drawKronos`, `placeCard`, `renderOpts`, `chartsPlanet`). Zrzut: `S04_charts.png`.
**Dane:** `spec/S3_DANE_I_KONTRAKTY.md` §2.

## Zakres
1. Przejście wejścia (2400 ms) i wyjścia (1500 ms) z planety 01 według `chartsPlanet` i `SCREENS[0]`. Linie wykresu zaczynają świecić dopiero po przejściu.
2. Układ jak w REF_B:
   - nagłówek z instrumentem, TF z `/api/v1/timeframes`, BID/ASK/SPREAD ze store `quote`, strefa czasu, status MT5;
   - wykres główny z OHLC i wskaźnikami w nagłówku wykresu;
   - okna RSI i MACD pod wykresem;
   - po prawej drugi wykres Kronos z opisem kierunku i niepewności;
   - zakładki opcji: WSKAŹNIKI / STREFY / VOLUME PROFILE / PLAN / MODELE / WYKRES.
3. **Silnik wykresów:** decyzja należy do Ciebie, uzasadnij ją w raporcie:
   - (a) `lightweight-charts` przez istniejący `ChartPanel` / `chartview` z nakładką canvas na plan bota i karty sygnałów, albo
   - (b) canvas 2D z REF_B.
   - Warunek dla obu: wskaźniki, strefy i VP liczone **tak samo** jak w WtcTower (te same funkcje, bez nowych wzorów).
   - Preferowane (a), bo spójne z resztą aplikacji i z `chartprefs` (zapamiętywanie warstw).
4. Plan bota (karta przy cenie): wejście, SL, TP1–3, RR netto i stan z `/api/v1/plans/chart` / `/api/v1/sh/chart`. Brak aktywnego planu → karta się nie pokazuje.
5. Sygnały AI i % modeli:
   - znaczniki na wykresie + lista w karcie;
   - % tylko dla kalibrowanych prawdopodobieństw, reszta jako „score” albo „niekalibrowany” (S3 §0).
6. Kronos:
   - TF spoza M1/M5/M15/M30/H1 → komunikat w oknie Kronos;
   - Kronos niezainstalowany lub wyłączony → stan z `/api/v1/kronos` i nazwa `.bat` do instalacji;
   - seria prognozy przesunięta do ostatniego zamknięcia głównego wykresu (jak w REF_B).
7. Odświeżanie:
   - świece na żywo ze store (`bar`, `bar_closed`);
   - Kronos i plan co zamknięcie świecy wybranego TF;
   - bez pętli pollingu częstszej niż 5 s.

## Kryteria odbioru E3
S5 C1, C5; D1–D3 dla tego ekranu. Zrzut porównany z `S04_charts.png`.
