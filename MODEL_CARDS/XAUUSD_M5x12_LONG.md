# Karta modelu – XAUUSD · M5 × 12 świec (LONG, TP 1,5×ATR przed SL 1,0×ATR)

| Pole | Wartość |
|---|---|
| Aktywo / instrument | XAUUSD / ustalany z MT5 (na symulatorze: XAUUSD:Synthetic-Demo:XAUUSD-) |
| Źródło danych | wymagane: MT5 (zamknięte świece M5 brokera, strona bid/ask wg spreadu świecy) |
| Zadanie | p(TP przed SL w 12 świecach M5) – NIE kierunek następnej świecy; abstencja przy p < 0,55 |
| Cechy | FS-1.0.0: returns, volatility, bands, trend, activity, time; sekwencje 4 kanały × 32 |
| Etykiety | LBL-TB-1.0.0 (SL najpierw przy kolizji, niedojrzałe usuwane, luki usuwane) |
| Protokół | MQ-LAB-VAL-1.0.0 (holdout 20% raz, 4 foldy WF, embargo 12, seedy 11/23/37) |
| Champion | **brak** – BLOCKED_NO_REAL_DATA |
| Wynik techniczny (syntetyczny) | NO_VALIDATED_EDGE na 11888 zdarzeniach – patrz VALIDATION_RESULTS.md |
| Rola dopuszczalna | `fixture_only` (dane syntetyczne) / `research` (MT5 bez holdoutu) / `shadow` (zaliczony holdout) |
| Wpływ na decyzje | żaden – scenariusze i silnik nie używają tego modelu do zleceń; Execution Lock aktywny |
| Ograniczenia | brak ticków w etykietach (OHLC), spread ze świecy, brak kalibratora (ECE raportowane), sieci w numpy (CPU) |
