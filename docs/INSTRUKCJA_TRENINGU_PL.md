# Instrukcja treningu modeli – PepeMarketWizard 1.33.0

Trening nigdy nie aktywuje modelu. Aktywacja to Twoje kliknięcie i przechodzi test zgodności oraz próbki inferencji. READY oznacza, że
model potrafi zwrócić wynik. Nie oznacza zgody na handel.

## 1. Dane
* **Bot działa:** dane pochodzą z jego magazynu świec. Eksport historii uruchomisz z Centrum treningu (Modele i trening → Centrum treningu →
  „1. Dane”) albo plikiem `11_EKSPORT_HISTORII_XAUUSD.bat`.
* **Bot nie działa:** Pepe Training Studio eksportuje pełną historię własnym połączeniem tylko do odczytu (tryb MT5_DIRECT).
* Bot i Studio mają wspólną blokadę eksportu, więc dwa eksporty naraz są niemożliwe. Drugi dostaje komunikat „eksport zajęty”.
* Wymagania danych każdej rodziny opisuje `docs/MODEL_DATA_REQUIREMENTS.md`. Za mało danych kończy się odmową z powodem (BLOCKED_DATA).

## 2. Modele TrainHub (TH_BASELINE, TH_LOGREG, TH_HGB, TH_RF, TH_SVM, TH_XGB)
1. Otwórz Centrum treningu, sekcję „2. Trening”.
2. Wybierz modele, interwał bazowy, horyzont i próg ATR, a potem kliknij **Przygotuj i trenuj**.
3. Wybierz profil:

| Profil | Kiedy |
|---|---|
| `smoke` | szybki test potoku |
| `research` | ocena |
| `full` | wydanie |

4. Po zakończeniu w „Paczkach” sprawdź wyniki na holdoucie i wtedy kliknij **Aktywuj**. Rollback jest w tym samym miejscu.
5. CLI: `python -m masterquo trainhub train --instrument XAUUSD --models TH_RF,TH_SVM --profile research`.

## 3. Rodziny modeli 1.33 (ARIMA, SARIMAX, GARCH, mikrostruktura, para, koszyk, Kalman, breakout, LSTM, GRU, PPO, NLP)
* **Panel:** Centrum treningu → **Rodziny modeli 1.33**. W wierszu masz:
  * stan trzech osi;
  * przyciski Trenuj / Anuluj / Aktywuj ostatni / Rollback;
  * wybór użycia OFF / SHADOW / ASSIST.
* **Trenuj wszystkie** raportuje osobno: uruchomione, zablokowane (z powodem) i delegowane.
* **Plik:** `35_RODZINY_MODELI.bat` albo menu `32_CENTRUM_TRENINGU.bat` (opcje 7 i 8).
* **CLI:** `python -m masterquo families list|train|train-all|activate|use|rollback --instrument XAUUSD [--family F] [--profile P]`.
* **LSTM / GRU / PPO** potrzebują osobnego środowiska `.venv_deep` (PyTorch, Gymnasium, Stable-Baselines3).
  * Zainstaluj je raz plikiem `34_DEEP_INSTALUJ.bat`, z sumami SHA-256 z `requirements/requirements-deep-win.txt`.
  * Bez niego te rodziny mają stan MISSING_DEPENDENCY z instrukcją.
* **Para i koszyk** wymagają jawnej konfiguracji: `families.pairs = [["XAUUSD","BTC"]]`, `families.basket` (≥ 3 instrumenty). Nic nie
  jest dobierane automatycznie.
* **NLP:** import korpusu nagłówków (JSONL, deduplikacja). Lokalny model transformer tylko z Twojej ścieżki (`families.nlp_transformer_path`).
  Nic nie jest pobierane.

## 4. Role modeli w decyzjach (PMW-ARC-1)

| Rola | Działanie |
|---|---|
| OBSERVE (SHADOW) | wynik zapisany w rekordzie decyzji, bez wpływu |
| ASSIST | gdy READY-owa prognoza kierunku daje P(strony przeciwnej) ≥ `families.assist_hold_threshold` (0,60), wejście jest **wstrzymane**. W SH READY zmienia się na WAIT, w ACTIVE węzeł MODELS daje BLOCKED. Rola nigdy nie tworzy wejścia |
| REQUIRED | wpisz rodzinę do `decision.required_models`. Brak prognozy, prognoza nieświeża (> `decision.required_max_age_s`) albo przeciwna blokuje nowe wejście z powodem |

Podgląd: Ustawienia i diagnostyka → **Koordynator decyzji** (`#/decyzje`).

## 5. Pepe Data & Training Studio
1. Uruchom Studio przyciskiem **Studio** w górnym pasku albo w menu CULT. Możesz też użyć `PepeTrainingStudio.exe` lub `36_STUDIO.bat`.
2. Studio ma 6 obszarów: Połączenia → Modele → Eksport → Walidacja i dataset → Trening → Kolejka i wyniki.
3. Każde zadanie daje osobną paczkę z atomowymi etapami i sumami.
4. Paczkę przenosisz do bota przyciskiem „Przenieś”. Gdy bot nie działa, paczka trafia do skrzynki odbiorczej i jest wczytywana przy jego starcie.
5. W bocie paczka jest **kandydatem**. Aktywujesz ją ręcznie w Centrum treningu, a rollback importu usuwa nieaktywowaną wersję.

Szczegóły: `docs/DATA_TRAINING_STUDIO.md`.

## 6. Walidacja kontrolna
Polecenie `python tools/validate_families_synthetic.py --out raport.json` trenuje wszystkie rodziny na danych syntetycznych o znanej
strukturze. Sprawdza potok i bramki. Nie sprawdza rentowności. Wynik dla tego wydania jest w `docs/RAPORT_WALIDACJI_MODELI.md`.
