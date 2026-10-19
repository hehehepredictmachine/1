# Neutralizacja sygnału, operatory SEW i kinematyka Bid/Ask (PMW-UPD-08, R17–R19)

Moduły badawcze, domyślnie OBSERVE/SHADOW. Nie wysyłają zleceń, nie zmieniają Execution Lock, nie wybierają modeli automatycznie.

## R17 — `SIGNAL_NEUTRALIZATION_ROLLING_V1` (`analysis/neutralization.py`)
- Stary eksperyment M08 `LOGREG_NEUTRALIZED` to `FEATURE_RESIDUALIZATION_COMPAT_V1` – bez zmian (stare artefakty działają).
- Kolejność w każdym kroku: wynik z beta dopasowanego **tylko na wcześniejszych** obserwacjach (okno N=240, min 60) → zapis → dopiero aktualizacja okna.
- OLS przez SVD (`rcond 1e-10`, max condition 1e8, intercept, standaryzacja w oknie). Ortogonalność `Dᵀe≈0` dotyczy tylko okna dopasowania;
  korelacje poza oknem raportujemy osobno (mogą być ≠ 0 – drift).
- Stany: WARMUP, CONSTANT_FACTOR, SINGULAR, STALE_BETA, NAN_INPUT, DEGENERATE_RESIDUAL (z = null). Nieudane dopasowanie nigdy nie staje się beta=0.
- Sygnał referencyjny ROC20; czynniki: ATR14/C i nachylenie EMA50 (5 świec)/C. Adapter wyniku modelu: `log((p_up+1e-6)/(p_down+1e-6))` – to nie prawdopodobieństwo.
- Stan (bufor, fit, wersje, sekwencja) trwały w `neutralizer_state`, wyniki w `neutralization_events` (idempotentnie); zmiana wersji/kontekstu lub luka → reset.
- Eksperyment `MQ_NEUTRAL_REACTION_V1`: warianty RAW_FILTER / NEUTRAL_FILTER / RAW_PLUS_FACTORS (LOGREG/XGB) na **tych samych wierszach**, protokół SI-PROTO-1.0.0,
  osobne manifesty; liczba odrzuceń (rozgrzewka/awarie) raportowana. Residual ≠ alpha.

## R18 — operatory SEW (`lab/structure_nets.py`)
| Operator | g(A,S) | ∂/∂S | ∂/∂A | identity |
|---|---|---|---|---|
| ADD | A+S | 1 | 1 | A=0 |
| AND | A·S | A | S | A=1 |
| IAND | (1−A)·S | 1−A | −S | A=0 |
`A` = gałąź po spike, `S` = shortcut; orientacja IAND jest częścią API. AND/IAND wymagają binarnych wejść (shortcut przy zmianie wymiaru = projekcja + LIF);
niebinarne → `DOMAIN_MISMATCH` (bez cichego castowania). Inicjalizacja identity: ADD/IAND cicha gałąź, AND stale aktywna (sprawdzane wielokrokowym forward).
Manifest: `connect_f`, `merge_version`, `iand_orientation`, profil projekcji, domena; stary artefakt bez pola = ADD. Telemetria: firing gałęzi, aktywność shortcutu,
średnie wyjście (ADD może > 1), odsetek niezerowych, martwe/nasycone jednostki. Wybór operatora tylko na dev; zmiana operatora = nowy trening.

## R19 — `MQ_NEWTONIAN_QUOTES_V2` (`lab/quotes.py`, `lab/tick_store.py`)
- Własna implementacja (opis Code Base 78046; źródła MQ5 nieodczytane → brak parytetu). Stara kinematyka mid (M31) pozostaje adapterem.
- Ticki z tego samego workera/bridge (zachowany surowy `time_msc`, transformacja czasu zapisana). Bid aktualizuje się tylko przy zmianie Bid, Ask – Ask.
  Kubełek timestampu per strona (ostatnia cena w kolejności źródła) zamykany dopiero przez późniejszy timestamp; zegar sekundowy → COARSE_CLOCK.
- Skale 16/64/256 jako docelowy Kish n_eff aktualizacji (nie sekundy); rzeczywiste n_eff, span, liczba unikalnych czasów raportowane.
- Lokalny kwadratowy model ważony (QR/SVD), v/a w cenie i punktach; niepewność klasyczna i własny model random-walk+kwantyzacja (sumy sufiksowe),
  `SE_used = max`; wariancja prognozy z kowariancją historii i celu. Estymacja SE ≠ trafność prognozy ≠ P(zysk).
- Spread z bezpośrednich par Ask−Bid; punkt zwrotu −v/a tylko przy istotnym a (inaczej UNSTABLE_TURN_TIME); faza z priorytetem i histerezą.
- Prognozy: strumień główny bez nakładania, h = min(0.25·span, 10 s), ocena pierwszym quote strony w [target, target+lag]; brak → UNSCORED_GAP.
  Pasmo empiryczne tylko z dojrzałych błędów (inaczej MODEL_BAND_UNCALIBRATED). Scoreboard vs persistence; R² przy stałym celu = null.
- Archiwum ticków: chunki NPZ + manifest (hash, zakres, TRUNCATED przy limicie), replay buduje cechy M1 i scoreboard (to nie trening).
- `MQ_QUOTE_CONTEXT_REACTION_V1`: CORE vs ENRICHED na wspólnym okresie z tickami; brak ticków → `BLOCKED_NO_TICK_HISTORY` (bez ticków z OHLC).

## API / panel / agent
`/api/v1/structure-intelligence/{neutralization,quotes,quote-forecasts,quote-quality}`; joby: `tick_export`, `tick_replay`, `experiment`, `train` z `sew_operators`.
Panel: Modele i trening → Structure Intelligence (karty „Kinematyka Bid/Ask”, „Neutralizacja sygnału”, przyciski eksperymentów), MTF – linia neutralizacji i fazy.
Agent: wiedza K19–K24 (PMW-SI-KNOWLEDGE-1.1.0), prompt 1.7.0.

## Komendy
```
python -m masterquo structure-intelligence neutralize --latest --signal ROC20
python -m masterquo structure-intelligence train --latest --task STRUCTURE_MOVE_M1_V1 --experiment MQ_NEUTRAL_REACTION_V1 --families LOGREG,XGB --profile standard
python -m masterquo structure-intelligence tick-export --asset XAUUSD --days 90 --source bridge   (wykonuje działający bot – job tick_export)
python -m masterquo structure-intelligence tick-replay --latest
python -m masterquo structure-intelligence train --latest --task STRUCTURE_MOVE_M1_V1 --experiment MQ_QUOTE_CONTEXT_REACTION_V1 --families LOGREG,XGB
python -m masterquo structure-intelligence train --latest --task STRUCTURE_MOVE_M1_V1 --families MQ_SEW_RESNET1D_V2,MQ_SEW_RESNEXT_EB_V1 --sew-operators ADD,AND,IAND
```
Launcher `26_STRUCTURE_INTELLIGENCE.bat` (opcje 10–14). Train-all: etap `structure_intelligence` (standard: ADD/AND/IAND + oba eksperymenty).

## Statusy
Kod: zaimplementowany, testy syntetyczne. Ticki rzeczywiste / trening: NOT_RUN (brak MT5). Parytet z oryginałem MQ5: UNVERIFIED. Edge: NOT_EVALUATED.
Migracja 0022 addytywna (backup automatyczny przed migracją).
