# Raport: scalp M5 Range → M1 Sweep/Reclaim → Retest, hedge, ML/NN – MasterQUO 1.12.0 (2026-10-15)

**Wniosek:** kod jest zbudowany i przetestowany. Dane rynkowe są niedostępne w środowisku budowy, dlatego:
- **trening na danych rynkowych: BLOCKED_NO_REAL_DATA**;
- **wynik OOS po kosztach: brak**;
- **hedge vs REDUCE: nieoceniony na danych rzeczywistych**.

Nic nie zostało dopuszczone do wykonania.

## 1. Zaimplementowane

**Profil i rdzeń strategii:**
- Wersjonowany profil badawczy z jednostkami: `config/scalp_profile_v1.json`.
- Automat stanów `backend/masterquo/scalp/strategy.py`:
  - zamrożony zakres M5;
  - sekcja M1 z `known_at`;
  - sweep/reclaim, potwierdzenie, tick volume, retest ≤3 M1;
  - limit pogoni/MISSED;
  - SL/TP1/TP2;
  - filtr kosztu i RR;
  - wielkość pozycji z zaokrągleniem w dół;
  - BUY/SELL lustrzane;
  - dziennik przejść.
- Wskaźniki (`scalp/indicators.py`): ATR Wilder, ER, BB z odchyleniem populacyjnym (%B, BW, percentyl, nachylenie), Parabolic SAR.

**Świece, sesje, adaptery:**
- Silnik świec SCI-1.0.0 (`scalp/candles_sci.py`): rodziny specyfikacji, ZERO_RANGE, jeden dowód na rodzinę, przyczynowe `PatternStats`.
- Sesje z IANA DST (`scalp/sessions.py`).
- Adaptery zewnętrzne ze statusami (`scalp/adapters.py`); PAL02M = UNDOCUMENTED_EXTERNAL; brak wartości = null.

**Hedge i replay:**
- Kontroler hedge (`scalp/hedge.py`): NETTING→REDUCE, 1 hedge, ≤50% base, TTL, wyjścia, osierocona noga, timeout→rekonsyliacja, P&L koszyka.
- Replay (`scalp/replay.py`):
  - Bid/Ask, prowizja, poślizg, partial TP;
  - 30 min, konserwatywna kolejność OHLC;
  - etykiety B oraz porównanie akcji C;
  - raport z bootstrapem bloków dni i bramką badawczą (`scalp/report.py`).

**Integracja z botem:**
- Serwis SHADOW w bocie (`scalp/service.py`):
  - te same bary sesji bota;
  - bramki AND;
  - zapis w `scalp_shadow` (migracja 0012) przed wynikiem;
  - rozliczenie hipotetyczne;
  - MTF/wskaźniki/sesje/adaptery/hedge/trening;
  - statusy CODE/DATA/MODEL/STRATEGY/HEDGE_VALID i EXECUTION_AUTHORIZED.
- API `/api/v1/scalp`, `/api/v1/scalp/shadow`.
- Konfiguracja `scalp` z przełącznikami typu `Literal[False]`.
- Eksport M1/M5/M15/M30/H1: `export-scalp`. Replay CLI: `scalp-replay`.

**ML/NN** (`gold_candles_runtime/scalp_features.py`, `scalp_train.py`, `scalp_infer.py`, `scalp_registry.py`, komenda workera `scalp_forecast`):
- kontrakt cech;
- plan przed treningiem;
- walk-forward;
- LR / HGB / **MLP 64/32 z early stopping na późniejszym fragmencie**;
- kwantyle, kalibracja, holdout raz;
- zadania B/C z replayu;
- rejestr z checksumami;
- rollback.

**Monitor i launchery:**
- Monitor: Wykresy bota → „Scalp M5 Range → M1 Sweep → Retest + hedge” z widokami MTF, Setup, Wskaźniki, Prognozy, Hedge/ryzyko, Trening.
- Launchery Windows 16–21: eksport, trening, walidacja, replay, start SHADOW, rollback.

## 2. Uruchomione (w środowisku budowy, Linux, symulator terminala)

| Polecenie | Dane | Wynik |
|---|---|---|
| `python -m unittest test_scalp_core` (bot venv) | SYNTHETIC_TEST | 40 testów OK (grupy 1–8 i 10) |
| `python -m unittest test_scalp_train` (`.venv_candles`) | SYNTHETIC_TEST | 7 testów OK (grupa 9) |
| `python -m unittest test_ui_scalp` (Chromium, `serve --demo`) | symulator | 3 testy OK, zrzuty `data/logs/ui_scalp/` |
| `gold_candles_runtime.scalp_train --data-kind SYNTHETIC_TEST --small-test` | 20 dni syntetycznego M1 | patrz niżej |
| `export_candles(..., SCALP_TFS, "scalp")` na FakeMT5 + `scalp-replay` | symulator, `data_kind` SYNTHETIC_TEST | 0 cykli, INSUFFICIENT_EVIDENCE |
| `tools/run_tests.py` | pełny zestaw | wynik w `RAPORT_TESTOW.md` |

**Szczegóły przebiegu `scalp_train --small-test`** (66 s; `.venv_candles`: numpy 2.3.5, pandas 2.2.3, scikit-learn 1.8.0):
- Wybór w walk-forward: LR dla wszystkich horyzontów.
- MLP: 7–8 epok, zatrzymane przez patience.
- Statusy: wszystkie horyzonty SHADOW_UNVALIDATED, ponieważ holdout ma < 30 dni. B i C: INSUFFICIENT_DATA.
- Aktywacja: NOT_ACTIVATED (NOT_REAL_USER_DATA).

To **test programu**, a nie wynik rynkowy.

**Przykładowy rekord replayu:** `research/scalp/PRZYKLAD_REKORDU_REPLAY_SYNTHETIC_TEST.json`.
- Źródło: scenariusz syntetyczny testu; służy do pokazania formatu.
- Zawartość: cykl BUY z TP1/TP2, punkty decyzji zadania C, dziennik stanów.

## 3. Zwalidowane

| Status | Wartość | Podstawa |
|---|---|---|
| CODE_VALID | tak | testy jednostkowe, integracyjne i UI – dowodzą poprawności zachowań kodu, nie jakości modelu ani rentowności |
| DATA_VALID | **nie** | brak eksportu z Twojego MT5 |
| MODEL_VALID | **nie** | brak treningu na REAL_USER_DATA |
| STRATEGY_VALID | **nie** | brak replayu OOS na danych rzeczywistych; brak liczby cykli, expectancy, PF i DD |
| HEDGE_VALID | **nie** | porównanie HEDGE_PARTIAL vs REDUCE nie zostało wykonane na danych rzeczywistych |

## 4. Dopuszczone do wykonania

**Nic.** EXECUTION_AUTHORIZED = false; konfiguracja nie przyjmuje innych wartości:
- `MODE=SHADOW`
- `LIVE_TRADING=false`
- `ML_EXECUTION=false`
- `HEDGE_EXECUTION=false`

Przejście na rachunek wymaga osobnej wersji i jawnej decyzji właściciela, po spełnieniu bramki badawczej.

## Blokady i jak je usunąć

**1. BLOCKED_NO_REAL_DATA.** W kontenerze budowy nie ma pakietu MetaTrader5 ani Twojego terminala. Na Windows z zalogowanym MT5:
1. `16_EKSPORT_HISTORII_SCALP.bat 6`
2. `19_REPLAY_SCALP.bat <prowizja>`
3. `17_TRENING_SCALP_ML.bat <prowizja>`
4. `18_WALIDACJA_SCALP.bat`

Raporty zapisują się w `data\scalp\replay\…\summary.json` oraz `data\scalp\runs\…\report.json`.

**2. Prowizja rachunku** jest nieznana programowi (profil „Zero” ≠ 0). Podaj ją jako argument launcherów oraz w `config.json` (`scalp.commission_per_lot_side`).

**3. Brak ticków.** Replay jest przybliżony (OHLC_APPROX). Dokładnej skuteczności scalp/hedge nie da się potwierdzić bez historii tickowej.

**4. Adaptery zewnętrzne** (IQ Gold Gann, IQ Star Lines, Volatility Master, heatmapa, PAL02M) wymagają licencjonowanego, udokumentowanego eksportu – lista w `docs/SCALP_HEDGE_ML_NN_PL.md`. Rdzeń działa bez nich.

**5. Rejestr eksperymentów:** `research/scalp/EXPERIMENT_REGISTRY.json` zawiera 14 zarejestrowanych wariantów; wszystkie mają status NOT_RUN_NO_REAL_DATA.

**6. Hedge względem REDUCE: nieoceniony.** Bez danych kontroler zawsze rekomenduje SHADOW/REDUCE.

## Ograniczenia, o których trzeba pamiętać

- **Liczby profilu** to hipotezy startowe. Strój je tylko w development; nie zmieniaj ich po obejrzeniu holdoutu.
- **Tick volume** to aktywność kwotowań brokera, nie wolumen rynku złota.
- **Limity dzienne i tygodniowe** liczone są z equity całego konta z zapisanym punktem odniesienia. Wpłaty i wypłaty nie są korygowane – zaznaczone w powodzie bramki.
- **`order_calc_margin` / `order_check`** nie są używane w SHADOW. Rzeczywista marża koszyka wymaga ich przed jakimkolwiek wykonaniem.
- **Pickle** z modelami drzewiastymi jest ładowany wyłącznie z własnego rejestru i po weryfikacji sha256.
