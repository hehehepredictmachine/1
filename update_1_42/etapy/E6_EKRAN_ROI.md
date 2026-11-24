# E6 – Ekran 04 ROI (`#/forex?s=roi`)

**Wzorzec:** REF_B sekcja „04 ROI” (`RO`, `renderRoiUI`, `renderRoiTable`, `drawRoi`, `drawRoiEquity`, `roiPlanet`, `roStars`, `roIntro`, `roCount`). Zrzuty: `S07_roi.png`, `S07b_roi_brak_danych.png`.
**Dane:** S3 §5, wyłącznie `GET /api/v1/stats?mode=…`.

## Zakres
1. Przejście 2700/1500 ms:
   - burzowa planeta ROI jedzie na środek i rośnie;
   - przelot przez wir (smugi);
   - oddalenie do pełnej galaktyki spiralnej, potem pojawia się oko.
2. Nagłówek: przełącznik PAPER / AUTO_DEMO / AUTO_LIVE (domyślnie tryb, w którym bot pracuje) oraz paski stanu konta, snapshotów (`equity.label`) i waluty.
3. Lewy panel:
   - okres DZIŚ / TYDZIEŃ / MIESIĄC / CAŁOŚĆ;
   - zrealizowany wynik netto z licznikiem, pasek W / BE / L, metryki z S3 §5, chipy stanu;
   - sekcja rachunku i notatki `scope` / `sampling_note` / `note` z API.
4. Środek:
   - wir + oko (ROI rachunku z 30 dni albo wynik PAPER albo BRAK DANYCH);
   - księżyce ścieżek z podpowiedzią po najechaniu i kliknięciem przełączającym tabelę;
   - krzywa kapitału (equity i saldo, kursor z wartościami);
   - słupki miesięcy.
5. Prawy panel: tabele ŚCIEŻKI / STRATEGIE / INSTRUMENTY / MIESIĄCE z paskami netto i notatką z API oraz historia 20 transakcji.
6. Tryb AUTO_LIVE bez transakcji (albo inny pusty tryb): wszędzie stan „BRAK DANYCH” jak na zrzucie S07b, bez liczb zastępczych.

## Kryteria odbioru E6
S5 C4, C5; D1–D3. W raporcie dla jednego trybu z danymi zestaw 5 wartości z ekranu z polami odpowiedzi `/api/v1/stats`.
