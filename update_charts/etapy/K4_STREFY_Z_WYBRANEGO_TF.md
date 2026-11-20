# K4 – Strefy bota tylko z wybranego TF

**Wzorzec (`charts.js`):** `botIndex` (część `CH.bzones`), `drawBotLayers` (strefy), `renderOpts` (zakładka STREFY z komunikatem dla TF bez stref).
**Zrzut:** `S04d_charts_strefy_tylko_wybrany_tf.png` (H1 – brak stref, komunikat).

## Zakres

1. Źródło: `GET /api/v1/market-zones?instrument=` → `timeframes[tf]`. Rysujesz **wyłącznie** `timeframes[CH.tf]`. Nic nie jest przenoszone z innego TF.
2. Bot liczy strefy dla M1, M5, M15, M30 (`zones/market.py`, `TF_PARAMS`). Na innym TF: komunikat z wzorca i wyłączone przełączniki (jak `S04d`).
3. Typy i rysowanie 1:1: FVG, OB, popyt / podaż, wsparcie / opór, EQH / EQL, „wybrane przez silnik” (`visible`), historia (unieważnione / wygasłe – przełącznik `mzHist`).
4. Etykieta: typ · TF · jakość Q (heurystyka) · stan. Mapowanie pól na `z.*` – D1 §3.5.
5. Odświeżanie po `bar_closed` wybranego TF.

## Kryteria K4
- [ ] Scenariusze 1:1 `K4_xau_h1_strefy` i `K6_xau_m15_strefy` przechodzą.
- [ ] Zmiana TF nigdy nie zostawia stref poprzedniego TF (test jednostkowy adaptera + zrzut).
