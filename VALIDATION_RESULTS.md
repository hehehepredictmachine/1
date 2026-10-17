# VALIDATION_RESULTS – tylko wykonane badania (17.10.2026)

## Najważniejsze

**W tym środowisku NIE wykonano żadnego badania na danych rynkowych.** Nie było terminala MT5 ani historii XAUUSD lub BTC.

Poniższe wyniki to **kwalifikacja inżynierska** protokołu MQ-LAB-VAL-1.0.0 na danych SYNTETYCZNYCH z symulatora terminala. To błądzenie losowe z przełączaniem reżimów, czyli dane bez prawdziwej przewagi. Służą sprawdzeniu, że pipeline nie „znajduje” przewagi tam, gdzie jej nie ma.

Nie są to wyniki XAUUSD ani BTC.

## XAUUSD – dane syntetyczne (SYNTHETIC), XAUUSD:Synthetic-Demo:XAUUSD-

- protokół `VP-013921045adf`; hash danych `666cbc8c13c1d001`
- zdarzenia: 11888 (dev 9509, holdout 2366)
- niejednoznaczne SL/TP w jednej świecy: 3
- okres 2026-09-06T10:45:00+00:00 – 2026-10-17T17:20:00+00:00; holdout od 2026-10-09T11:15:00+00:00 (hash `22980406316b53fd`)
- czas: 265.6 s (CPU kontenera)
- **werdykt: NO_VALIDATED_EDGE** – żadna rodzina nie spełniła z góry ustalonych kryteriów na danych rozwojowych
- holdout: nie użyty (brak kandydata po danych rozwojowych – zgodnie z protokołem)

| Rodzina | Status | Log loss (śr. ± sd) | Brier | ECE | AUC | Expectancy R | Pokrycie | Transakcje OOF |
|---|---|---|---|---|---|---|---|---|
| DUMMY | COMPLETED | 0.6537 ± 0.0077 | 0.2305 | 0.017 | 0.500 | — | 0.0% | 0 |
| RULE | COMPLETED | 0.6497 ± 0.0085 | 0.2287 | 0.018 | 0.548 | — | 0.0% | 0 |
| LOGREG | COMPLETED | 0.6527 ± 0.0034 | 0.2301 | 0.036 | 0.538 | 0.310 | 0.6% | 43 |
| TREE | COMPLETED | 0.6583 ± 0.0054 | 0.2325 | 0.056 | 0.515 | 0.871 | 0.3% | 24 |
| MINIROCKET | COMPLETED | 0.6711 ± 0.0144 | 0.2380 | 0.073 | 0.518 | 0.083 | 4.3% | 324 |
| XGB | COMPLETED | 0.6531 ± 0.0051 | 0.2302 | 0.028 | 0.533 | -0.083 | 0.1% | 8 |
| RESNET1D | COMPLETED | 0.6525 ± 0.0074 | 0.2299 | 0.035 | 0.542 | — | 0.0% | 0 |
| SEW_SNN | COMPLETED | 0.6530 ± 0.0091 | 0.2302 | 0.028 | 0.536 | — | 0.0% | 0 |
| LOGREG_PCA | COMPLETED | 0.6520 ± 0.0034 | 0.2297 | 0.034 | 0.541 | -0.225 | 0.3% | 23 |
| LOGREG_GMM_AUG | COMPLETED | 0.6533 ± 0.0032 | 0.2303 | 0.036 | 0.537 | 0.208 | 0.7% | 53 |
| LOGREG_NEUTRALIZED | COMPLETED | 0.6579 ± 0.0041 | 0.2325 | 0.023 | 0.503 | 0.250 | 0.0% | 2 |

Kontrole negatywne: PERMUTED_BLOCK_LABELS: zysk log loss vs DUMMY -0.0070 (OK); FUTURE_SHIFTED_LABELS: zysk log loss vs DUMMY -0.0058 (OK)

Tabela kandydatów (kryteria z góry): RULE: udział foldów lepszych od DUMMY 0.75, transakcje 0, kwalifikuje się: nie; LOGREG: udział foldów lepszych od DUMMY 0.50, transakcje 43, kwalifikuje się: nie; TREE: udział foldów lepszych od DUMMY 0.25, transakcje 24, kwalifikuje się: nie; MINIROCKET: udział foldów lepszych od DUMMY 0.00, transakcje 324, kwalifikuje się: nie; XGB: udział foldów lepszych od DUMMY 0.25, transakcje 8, kwalifikuje się: nie; RESNET1D: udział foldów lepszych od DUMMY 0.25, transakcje 0, kwalifikuje się: nie; SEW_SNN: udział foldów lepszych od DUMMY 0.25, transakcje 0, kwalifikuje się: nie; LOGREG_PCA: udział foldów lepszych od DUMMY 0.50, transakcje 23, kwalifikuje się: nie; LOGREG_GMM_AUG: udział foldów lepszych od DUMMY 0.50, transakcje 53, kwalifikuje się: nie; LOGREG_NEUTRALIZED: udział foldów lepszych od DUMMY 0.00, transakcje 2, kwalifikuje się: nie

## BTC – dane syntetyczne (SYNTHETIC), BTC:Synthetic-Demo:BTCUSD-

- protokół `VP-7af8d512059f`; hash danych `9e8fac626264eb05`
- zdarzenia: 11888 (dev 9508, holdout 2366)
- niejednoznaczne SL/TP w jednej świecy: 12
- okres 2026-09-06T10:50:00+00:00 – 2026-10-17T17:25:00+00:00; holdout od 2026-10-09T11:20:00+00:00 (hash `c08849957dbe9577`)
- czas: 349.9 s (CPU kontenera)
- **werdykt: NO_VALIDATED_EDGE** – żadna rodzina nie spełniła z góry ustalonych kryteriów na danych rozwojowych
- holdout: nie użyty (brak kandydata po danych rozwojowych – zgodnie z protokołem)

| Rodzina | Status | Log loss (śr. ± sd) | Brier | ECE | AUC | Expectancy R | Pokrycie | Transakcje OOF |
|---|---|---|---|---|---|---|---|---|
| DUMMY | COMPLETED | 0.4498 ± 0.0103 | 0.1386 | 0.009 | 0.500 | — | 0.0% | 0 |
| RULE | COMPLETED | 0.4506 ± 0.0108 | 0.1388 | 0.021 | 0.527 | — | 0.0% | 0 |
| LOGREG | COMPLETED | 0.4474 ± 0.0102 | 0.1380 | 0.016 | 0.562 | — | 0.0% | 0 |
| TREE | COMPLETED | 0.4538 ± 0.0102 | 0.1399 | 0.027 | 0.546 | — | 0.0% | 0 |
| MINIROCKET | COMPLETED | 0.4523 ± 0.0086 | 0.1395 | 0.031 | 0.546 | -0.720 | 0.0% | 2 |
| XGB | COMPLETED | 0.4469 ± 0.0105 | 0.1379 | 0.009 | 0.565 | — | 0.0% | 0 |
| RESNET1D | COMPLETED | 0.4533 ± 0.0082 | 0.1397 | 0.029 | 0.516 | — | 0.0% | 0 |
| SEW_SNN | COMPLETED | 0.4508 ± 0.0124 | 0.1387 | 0.023 | 0.548 | — | 0.0% | 0 |
| LOGREG_PCA | COMPLETED | 0.4474 ± 0.0101 | 0.1380 | 0.016 | 0.563 | — | 0.0% | 0 |
| LOGREG_GMM_AUG | COMPLETED | 0.4471 ± 0.0103 | 0.1379 | 0.013 | 0.564 | — | 0.0% | 0 |
| LOGREG_NEUTRALIZED | COMPLETED | 0.4508 ± 0.0104 | 0.1388 | 0.012 | 0.508 | — | 0.0% | 0 |

Kontrole negatywne: PERMUTED_BLOCK_LABELS: zysk log loss vs DUMMY -0.0047 (OK); FUTURE_SHIFTED_LABELS: zysk log loss vs DUMMY -0.0023 (OK)

Tabela kandydatów (kryteria z góry): RULE: udział foldów lepszych od DUMMY 0.00, transakcje 0, kwalifikuje się: nie; LOGREG: udział foldów lepszych od DUMMY 0.75, transakcje 0, kwalifikuje się: nie; TREE: udział foldów lepszych od DUMMY 0.25, transakcje 0, kwalifikuje się: nie; MINIROCKET: udział foldów lepszych od DUMMY 0.50, transakcje 2, kwalifikuje się: nie; XGB: udział foldów lepszych od DUMMY 0.75, transakcje 0, kwalifikuje się: nie; RESNET1D: udział foldów lepszych od DUMMY 0.00, transakcje 0, kwalifikuje się: nie; SEW_SNN: udział foldów lepszych od DUMMY 0.25, transakcje 0, kwalifikuje się: nie; LOGREG_PCA: udział foldów lepszych od DUMMY 0.75, transakcje 0, kwalifikuje się: nie; LOGREG_GMM_AUG: udział foldów lepszych od DUMMY 0.75, transakcje 0, kwalifikuje się: nie; LOGREG_NEUTRALIZED: udział foldów lepszych od DUMMY 0.00, transakcje 0, kwalifikuje się: nie

## Wniosek

**Żadna konfiguracja nie wykazała wiarygodnej przewagi.** Na danych syntetycznych jest to wynik oczekiwany i poprawny.

Dla rzeczywistych XAUUSD i BTC badanie trzeba uruchomić na Twoim MT5:
- ścieżka: Modele i trening → Uruchom badanie;
- wynik zapisuje się w `data/lab/studies/`;
- rejestr prób jest w tabeli `lab_trials`.

Do czasu takiego badania status modeli brzmi: **BLOCKED_NO_REAL_DATA**.
