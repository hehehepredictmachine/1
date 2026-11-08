# Wydajność – PMW Quant Core (1.35.0)

Pomiary wykonano 8 listopada 2026 r. w kontenerze budowania. Surowe dane: `docs/quant/PERFORMANCE_RAW.json`.
Narzędzia: `python -m masterquo quant bench` oraz skrypt pomiarowy uruchamiający bota `serve --demo`.
**To nie jest komputer użytkownika ani terminal MT5.** Symulator terminala (SYNTHETIC) zastępuje MT5, a Kronos, gold_candles i modele deep nie były zainstalowane.
Budżety na Windows z MT5 trzeba potwierdzić na docelowej maszynie poleceniem `37_QUANT_CORE.bat → 6`.

## Profil

| Pozycja | Wartość |
|---|---|
| Sprzęt | 4 vCPU Intel Xeon, 15 GB RAM, bez GPU (VRAM: nie dotyczy) |
| System | Linux 6.18 x86_64 (kontener) |
| Python / NumPy | 3.13.18 / 2.5.3 |
| Dane | symulator terminala `--demo` (SYNTHETIC), XAUUSD-, M1–D1 po 500 świec |
| Modele w cyklu | 22 rekordy: 15 READY (reguły SH, wskaźniki, DXY, strefy, mikrostruktura, 6 wyjść MM), 7 wykluczonych (Kronos ×2, gold_candles, MC = DISABLED; lab, Event GRU, scalp A = NOT_TRAINED) |
| Cykl | co 5 s, 24 cykle w oknie pomiaru |

## Cykl Quant Core (bot demo, SHADOW)

| Zadanie | p50 ms | p95 ms | p99 ms | max ms |
|---|---|---|---|---|
| snapshot (8 TF, QC) | 46,8 | 96,3 | 107,1 | 109,8 |
| base_predictions (`all_predictions`) | 4,1 | 52,0 | 736,6 | 940,3 |
| extended_predictions | 2,6 | 33,1 | 57,8 | 64,4 |
| contract_checks | 0,6 | 10,0 | 14,2 | 15,4 |
| **cały cykl** | **63,6** | **160,7** | **765,8** | **946,2** |

Maksimum `base_predictions` (~0,9 s) to pierwsze wywołanie po starcie: rodziny modeli ładują się i liczą swój cache dla nowej świecy.
Kolejne wywołania w obrębie świecy trafiają w cache.

## Komponenty (micro-benchmark, n = 200, dane syntetyczne)

| Komponent | p50 ms | p95 ms | p99 ms |
|---|---|---|---|
| QC snapshotu 600 świec | 1,20 | 1,85 | 3,53 |
| kontrola kontraktów 40 rekordów | 0,50 | 0,76 | 1,21 |
| symulacja planu 60 świec | 0,084 | 0,128 | 0,155 |
| predykcja meta-modelu | 0,077 | 0,125 | 0,144 |
| trening meta-modelu 400 wierszy (OOF, kalibracja, test) | 0,78 s (jednorazowo) | | |

Predykcja meta-modelu w koordynatorze (ASSIST) to ułamek milisekundy. Koordynator nie liczy modeli.

## Wpływ na bota (SHADOW vs OFF, ten sam proces, okna po 90 s)

| Miara | SHADOW | OFF |
|---|---|---|
| CPU procesu bota (% jednego rdzenia) | 39,6 | 37,6 |
| RSS procesu | 431,5 MB | 442,1 MB |
| `GET /api/v1/state` p50 / p95 / p99 | 15,8 / 36,0 / 54,7 ms | 19,2 / 33,7 / 80,1 ms |
| `GET /api/v1/quant/status` p50 / p95 / p99 | 3,0 / 26,2 / 71,6 ms | 3,2 / 15,9 / 30,1 ms |
| `GET /api/v1/quant/status` z CLI (n = 60) | 4,3 / 6,3 / 11,7 ms | – |

- Różnica CPU wynosi około 2 punktów procentowych jednego rdzenia. Różnice opóźnień API mieszczą się w rozrzucie pomiaru (60 próbek, ogony zależą od pętli innych usług).
- RSS po przełączeniu na OFF nie spadł, bo pamięć procesu Python nie jest zwracana. To nie jest wyciek Quant.
- Pracy wątku MT5 nie mierzono na prawdziwym terminalu. Quant czyta bufory bridge pod jego blokadą bez wywołań MT5. Wyjątkami są ticki Event GRU (tylko z aktywnym artefaktem na `REAL_TICKS`, priorytet historii workera) i scalp A (proces `.venv_candles`, raz na M1).

## Ograniczenia i budżety

- Deadline'y zadań (5 / 20 / 25 / 5 s) to bezpieczniki izolacji awarii, nie cele wydajności. Zadanie po deadline ma stan `TIMEOUT`, a jego wynik jest odrzucany.
- Nie mierzono Kronos, gold_candles, scalp A, Event GRU ani modeli deep w cyklu (brak środowisk i artefaktów). Ich koszt należy zmierzyć po instalacji (`quant bench` przy działającym bocie pokazuje `live_cycle`).
- Trening meta-modelu działa w osobnym wątku. Liczby wątków BLAS nie zmieniano.
