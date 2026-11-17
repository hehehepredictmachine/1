# E4 – Ekran 02 SIGNALS (`#/forex?s=signals`)

**Wzorzec:** REF_B sekcja „SIGNALS” (`SG`, `MODEL_REG`, `KIND_PL`, `renderSignalsUI`, `renderDetail`, `renderGates`, `renderCenterAlt`, `drawMini`, `drawSignals`, `signalsPlanet`). Zrzut: `S05_signals.png`.
**Dane:** S3 §3.

## Zakres
1. Przejście 2600/1500 ms: powłoki planety SIGNALS rozchodzą się w konstelację.
2. Nagłówek:
   - instrument;
   - zakładki CENTRUM / NA ŻYWO / HISTORIA / STRATEGIE / WYNIKI (każda filtruje te same dane, bez nowych funkcji);
   - tryb pracy, ścieżka główna, stan STOP i blokada AUTO LIVE ze store (`s.mode` i pola stanu, które pokazuje dziś `ControlTower` / `ModePanel`; nie twórz nowych źródeł).
3. Lewy panel:
   - filtry ŹRÓDŁO (wszystkie / silnik / scenariusze / SH), KIERUNEK, ZAKRES;
   - lista z ikoną źródła, stanem (chip), czasem i szansą albo stanem modelu po prawej.
4. Środek, konstelacja:
   - cena w środku, sygnały jako gwiazdy (kąt = czas, pierścień = TF), podpisy kierunku i szansy;
   - widoki alternatywne zakładek jak `renderCenterAlt`;
   - pod spodem bramki ścieżki z S3 §3.
5. Prawy panel:
   - szczegóły sygnału: mini-wykres SVG z poziomami, szansa z etykietą źródła, RR netto, siła setupu (heurystyka z opisem), kontekst, warunki wejścia, trigger, unieważnienie, ocena AI;
   - **ocena prognozy – wszystkie modele z katalogu** (liczba z API, nie na sztywno 42);
   - pasek zgodności: zgodny / przeciwny / neutralny / brak.
6. Czytelność: rozmiary fontów z REF_B (wersja „zwiększona czytelność”, klasy `sg-*`).

## Kryteria odbioru E4
S5 C2, C5; D1–D3. Sprawdź na 3 sygnałach, że etykieta szansy (prawdopodobieństwo / Monte Carlo „symulacja” / score / brak) zgadza się z polem `unit` / `calibration` z API.
