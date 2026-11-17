# E5 – Ekran 03 MODELS & BACKTEST (`#/forex?s=models`)

**Wzorzec:** REF_B sekcja „MODELS & BACKTEST” (`MB`, `MB_STATE`, `renderModelsUI`, `renderModelDetail`, `renderMbCenter`, `svgBars`, `svgRel`, `drawModels`, `modelsPlanet`, `mbIntro`, `mbCountUp` + CSS „animowany panel modeli”).
**Zrzuty:** `S06_models.png`, `S06b_models_trening.png`, `S06c_models_backtest.png`, `S06d_models_monte_carlo.png`.
**Dane:** S3 §4.

## Zakres
1. Przejście 2600/1500 ms:
   - siatka planety rozwija się w eliptyczny tunel, księżyc przelatuje;
   - pojawia się obserwatorium z rdzeniem „CENTRUM TRENINGU”.
2. Nagłówek:
   - XAUUSD / BTC (trenowane osobno);
   - zakładki OBSERWATORIUM / TRENING / BACKTEST / MONTE CARLO;
   - paski stanu: historia MT5 i TF z `trainhub/status.data`, worker z `queue`, „AKTYWACJA RĘCZNA” (stała zasada).
3. **Lewy panel (animowany, decyzja użytkownika):**
   - podsumowanie z licznikami liczącymi od zera;
   - lista modeli z katalogu pogrupowana jak `sh/models.py`;
   - wiersze wjeżdżają po kolei;
   - kropki stanów migoczą, pasek skill i pasek treningu płyną, po CHAMPION przechodzi błysk;
   - zaznaczony wiersz ma świecącą belkę, a hover daje smugę i pierścień gwiazdy w obserwatorium;
   - **wszystkie animacje CSS z REF_B 1:1** (`mbDrift`, `mbScan`, `mbTw`, `mbRun`, `mbSweep`, `mbChip`, `mbBeam`, `mbIn`, `mbLine`, `mbFill`);
   - intro panelu odpalane tylko przy wejściu i zmianie instrumentu, nie przy kliknięciu.
4. Środek:
   - OBSERWATORIUM (gromady = grupy, jasność = skill z raportu, model w treningu z pulsującym pierścieniem i linią do rdzenia, orbita postępu zadania);
   - TRENING (10 etapów PMW-TH-PIPE-1, profile smoke/research/full z `trainhub/status.defaults`, kolejka zadań);
   - BACKTEST (warianty z raportu replay, krzywe HEDGE / NO_HEDGE / REDUCE, tabela);
   - MONTE CARLO (diagram rzetelności i metryki z raportu).
   - Brak raportu → `NOT_RUN` z instrukcją.
5. Prawy panel:
   - szczegóły modelu: skill vs bazowy, Brier, ECE przed/po, wersja i dane, walk-forward (log loss na foldach), holdout z krzywą rzetelności, ocena tradingowa w ATR po kosztach, ważność cech, bramka promocji;
   - przyciski akcji tylko jak w S3 §4.

## Kryteria odbioru E5
S5 C3, C5; D1–D3. Zrzuty 4 zakładek porównane ze wzorcami. Przy modelu `NOT_TRAINED` wiersz, gwiazda i panel szczegółów mają poprawny stan pusty.
