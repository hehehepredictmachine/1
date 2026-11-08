# PMW Quant Core – instrukcja obsługi (1.35.0)

Wszystkie polecenia uruchamia się z folderu `backend` programu, interpreterem `.venv`: `..\.venv\Scripts\python.exe -m masterquo quant …`.
Prościej użyć `37_QUANT_CORE.bat` z głównego folderu (menu z tymi samymi poleceniami).
Każde polecenie było uruchomione w testach (`test_quant_core.TestInventoryCli`, `test_ui_quant`). Kody wyjścia: 0 ok, 1 błąd, 2 brak danych / złe argumenty, 3 odmowa.

## 1. Po aktualizacji

1. Uruchom bota jak zwykle (`PepeMarketWizard.exe` albo `masterquo_start.bat`). Quant Core startuje automatycznie w trybie **SHADOW**: liczy i zapisuje, ale na nic nie wpływa.
2. Panel → **Ustawienia i diagnostyka → Koordynator decyzji** → sekcja „PMW Quant Core”. Widać tam:
   - stan danych i czas ostatniej zamkniętej świecy;
   - liczbę wyników gotowych i wykluczonych, z przyczynami;
   - czasy zadań p50/p95/p99;
   - oceny setupów.
3. Panel → **Modele i trening → Centrum treningu** → sekcja „PMW Quant Core”: dowody w ledgerze, artefakty meta-modelu, trening, aktywacja, rollback.

## 2. Diagnostyka

```bat
..\.venv\Scripts\python.exe -m masterquo quant status
..\.venv\Scripts\python.exe -m masterquo quant inventory            rem docs\quant\INVENTORY.md / .json (bez działającego bota)
..\.venv\Scripts\python.exe -m masterquo quant inventory --live     rem ze stanem działającego bota (API)
```

W API (bot działa, przeglądarka z sesją panelu):
- `GET /api/v1/quant/status`
- `GET /api/v1/quant/predictions`
- `GET /api/v1/quant/assessment`
- `GET /api/v1/quant/jobs`
- `GET /api/v1/quant/inventory`

Odczyty zwracają opublikowaną generację i niczego nie przeliczają.

Typowe przyczyny wykluczenia wyniku:

| Przyczyna | Znaczenie |
|---|---|
| `STATE_DISABLED` | brak środowiska modelu (`.venv_kronos`, `.venv_candles`, `.venv_deep`) |
| `STATE_NOT_TRAINED` | brak aktywnego artefaktu |
| `STATE_BLOCKED_DATA` | brak wymaganych danych (rozgrzewanie, brak DXY, pętla MM jeszcze nie policzyła) |
| `STALE` | wynik starszy niż jego TTL |
| `FUTURE_TIME` | czas wyniku z przyszłości (zegar / błąd producenta) |
| `LATE_GENERATION` | spóźniona odpowiedź workera dla starszej świecy |
| `CONTRACT_ERROR` | NaN / Inf / bool / zła jednostka / rozkład spoza zakresu |
| `SYNTHETIC_IN_REAL_SNAPSHOT` | wynik z danych syntetycznych w snapshocie rzeczywistym |

## 3. Eksport i trening modeli bazowych (bez zmian, istniejące narzędzia)

| Model | Narzędzie |
|---|---|
| Trainhub | `32_CENTRUM_TRENINGU.bat` (`python -m masterquo trainhub full --instrument XAUUSD`) |
| Rodziny 1.33 | `35_RODZINY_MODELI.bat` |
| Event GRU / MM | Centrum MM (`python -m masterquo mm train …`) |
| gold_candles | `10_PROGNOZY_INSTALUJ.bat` i trening prognoz |
| Kronos | `33_KRONOS_INSTALUJ.bat` |

Quant nie trenuje modeli bazowych drugi raz. Odbiera ich wyniki i pokazuje stan.

## 4. Trening Quant MetaModel

Meta-model uczy się na wierszach ledgera Quant, które zbierają się w SHADOW z rzeczywistych kandydatów setupów. Etykiety pojawiają się po upływie horyzontu.

```bat
..\.venv\Scripts\python.exe -m masterquo quant train --instrument XAUUSD
..\.venv\Scripts\python.exe -m masterquo quant list --instrument XAUUSD
```

- Za mało dojrzałych wierszy daje `INSUFFICIENT_EVIDENCE`, kod 2. To prawidłowy stan, nie awaria.
- Wynik `VALIDATION_FAILED` oznacza zapisany artefakt bez możliwości aktywacji. Przyczyny są w kolumnie „niespełnione kryteria”.
- Wynik `VALIDATED_SHADOW` oznacza, że artefakt można aktywować (SHADOW):

```bat
..\.venv\Scripts\python.exe -m masterquo quant activate --instrument XAUUSD --task <task_hash> --version <wersja>
```

Po aktywacji oceny setupów tego zadania pokazują P(zdarzenia), E[net R] i ewentualne „wstrzymałby”. W SHADOW nadal nie mają wpływu na decyzje.

## 5. ASSIST (opcjonalnie, tylko świadomie)

Warunki: aktywny `VALIDATED_SHADOW` oraz jawne potwierdzenie.

```bat
..\.venv\Scripts\python.exe -m masterquo quant mode ASSIST --confirm
```

W panelu: zaznacz „rozumiem…”, a potem przycisk ASSIST.

ASSIST może tylko **wstrzymać** kandydata (`MODEL_QUANT_HOLD`), gdy E[net R] ≤ 0 albo P < próg rentowności planu binarnego. Przy nieznanym koszcie nigdy nie wstrzymuje.
Nie składa zleceń, nie zmienia limitów, wolumenu ani trybu SIGNALS/PAPER/AUTO DEMO/AUTO LIVE. Nie omija STOP ani rezerwacji.

Powrót do domyślnego trybu: `quant mode SHADOW`. Wyłączenie Quant Core: `quant mode OFF` (zachowanie jak 1.34).

## 6. Pomiary

```bat
..\.venv\Scripts\python.exe -m masterquo quant bench
```

Wynik: czasy komponentów p50/p95/p99 na danych syntetycznych. Gdy bot działa, dodatkowo opóźnienie API i czasy cyklu na żywo.

## 7. Czego Quant Core nie robi

- Nie obiecuje skuteczności ani ROI.
- Nie traktuje zgodności modeli z tego samego feedu jako niezależnego potwierdzenia.
- Nie zamienia braku modelu na 50%.
- Nie uczy meta-modelu na danych syntetycznych do użytku.
- Nie wysyła wiadomości Telegram ani zleceń.
