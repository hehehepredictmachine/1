# MasterQUO — M07/M03E Operational Strategy Profiles v1.0.0-CANDIDATE

**Polska instrukcja, tryb analityczny READ-ONLY. To nie jest bot składający zlecenia ani walidacja skuteczności strategii.**

## Co zostało połączone

MT5 -> M01 audyt -> M02 + M02I + M03 -> **M07/M03E automatyczny dobór rodziny i dowodów** -> M09 -> M10A lifecycle -> M14 decyzja -> M15 monitor (opcjonalnie Telegram). Rdzenie wcześniejszych modułów są zachowane bez zmiany; nowa warstwa wykonuje automatyczne dopasowanie istniejących M03 event_id do zamrożonego *badawczego szablonu* i generuje sprawdzalne reguły M10A. Nie wprowadza nowej, równoległej bazy produkcyjnych strategii M08.

| Tryb | Strategia badawcza | TF setupu | Wymagania, poza pięcioma CORE M03E |
|---|---|---|---|
| MVP | XAU-S01 Trend Pullback | M15 | zgodność M02 H1/H4, świeże kierunkowe FVG, aktywna referencja płynności (SSL/BSL) |
| SMC | XAU-S14 Sweep + FVG Continuation | M15 | jak wyżej, rzeczywiście wykryty sweep we właściwym kierunku i przed utworzeniem FVG |
| SCALPING | XAU-S06 Displacement Momentum Continuation | M5 | FVG oraz wcześniejszy displacement-confirmed BOS/MSS w tym samym kierunku |
| AUTO | wybór spośród trzech | M15/M5 | kolejność priorytetów SMC -> MVP -> SCALPING; bez empirycznego rankingu |

**MVP jest nową, prowizoryczną definicją na potrzeby projektu**, nie odtworzeniem nieznanej dotąd strategii użytkownika. Dostarczone profile nie obejmują wszystkich 20 rodzin MasterQUO. Nie obiecują wzrostu trafności.

## Parametry początkowe

`OPERATIONAL_PROFILES_v1.json` przechowuje: maksymalny wiek FVG w zamkniętych świecach, poziom mitigacji, maksymalną odległość FVG w ATR, progi faz kwalifikacji, uzbrojenia, triggera i potwierdzenia w jednostkach ATR oraz warunek unieważnienia. **Są to wartości PROVISIONAL, nie wynik optymalizacji OOS.** Zmiana profilu zmienia spec_hash i wymaga nowego testu M06.

Kod generuje poziomy tylko z zaobserwowanego FVG, ostatniego zamknięcia i policzonego ATR. Cena z niezakończonej świecy nie potwierdza etapów. Nie ma automatycznie wyliczonych SL/TP, pozycji w lotach ani prognozy TP-before-SL — bez wymaganych dowodów takie wartości pozostają niedostępne.

## Windows 10/11 — użycie

1. Uruchom MetaTrader 5 (zalecane konto **DEMO**) i upewnij się, że symbol XAUUSD jest dostępny w Market Watch. Konto Zero nie oznacza zawsze zerowej prowizji i poślizgu.
2. Rozpakuj ZIP do osobnego folderu; otwórz PowerShell w tym folderze.
3. Zainstaluj: `py -3 -m pip install MetaTrader5 numpy`.
4. Uruchom: `py -3 RUN_MT5_OPERATIONAL_PROFILES_READONLY.py --mode AUTO --symbol XAUUSD`.
5. W drugim oknie: `py -3 M15_SIGNAL_VIEWER.py`.
6. Wybrane inne tryby: `--mode MVP`, `--mode SMC`, `--mode SCALPING`.
7. Broker z symbolem `XAUUSDm`: `--symbol XAUUSDm`. Opcjonalny indeks USD: `--dxy-symbol <NAZWA_Z_MT5>`.
8. Alternatywnie otwórz `START_OPERATIONAL_PROFILES_AUTO_READONLY.bat` (domyślnie AUTO).

Ważne pliki w `runtime/`:
- `OP_DISCOVERY.json`: wykryty profil, powody niewykrycia, faktyczne identyfikatory dowodów;
- `OP_RESEARCH_LOCK.sqlite`: trwała blokada tożsamości badawczego planu w wybranym trybie;
- `M10_STATE.sqlite`: trwała historia M10A i przejść setupu;
- `M10A_UPSTREAM_MONITOR.json`: wynik M01→M14;
- `M15/`: końcowy eksport M15 + kolejka alertów;
- `MT5_RAW_DIAGNOSTIC.json`: odczyty MT5/M02I.

Telegram domyślnie **OFF**. Dostępny tylko przez świadome `--telegram-send` i osobną konfigurację z wcześniejszego M15; przekazywane są komunikaty **analityczne**, nie dyspozycje inwestycyjne. Nie umieszczaj tokenów w plikach JSON lub w rozmowie.

## Kiedy nie będzie sygnału

Brak danych, brak kierunku M02, brak położenia FVG i referencji płynności, brak wymaganego sweepa lub BOS, brak świeżości, konflikt snapshotów, brak potwierdzonego baru -> `NONE`, `WAIT` lub `NO_TRADE` i **execution BLOCKED**. Każda analizowana sytuacja może nie doprowadzić do wejścia. Nie ma awansu tylko za zgodność EMA/RSI/MACD.

## Granice bezpieczeństwa

- Konto MT5 Zero jest zadeklarowanym profilem. Koszty muszą być później odczytane z rzeczywistych Bid/Ask oraz rozliczeń brokera przez M11/M12. W tym module nie podaje się rentowności netto.
- `research_only=true`, `m08_registry_approved=false` i `execution_permission=BLOCKED` zawsze.
- Żadnych zleceń MT5 / `order_send`, screenshotów, OCR ani transakcji live; M15 nadal blokuje wykonanie.
- Profil i reguły są deterministyczne, nie jest to ML/self-retraining.
- M06 OOS, koszty, walk-forward i MT5 DEMO pozostają NOT_RUN, podobnie jak pomiar faktycznej częstotliwości i trafności sygnałów.
- Sygnały mogą być rzadkie i nie jest to wada świadcząca o awarii: konserwatywne warunki chronią przed wymyśloną analizą.
- Pozostałe moduły M01–M16 i M02I pozostają bez zmian; dostarczamy integrator-kandydata, nie produkcyjne zatwierdzenie.

## Testowanie

`py -3 -m unittest -q M07_M03E_PROFILE_TESTS M07_M03E_RUNTIME_TESTS`

`py -3 RUN_ALL_OPERATIONAL_PROFILE_TESTS.py` (85 nowych testów)

`py -3 RUN_ALL_OPERATIONAL_PROFILE_TESTS.py --with-regression` (dodatkowo 794 wcześniejsze testy; dłuższy przebieg)

To testy lokalne ze sztucznymi danymi. Wyniki testów i SHA256SUMS są dołączone do ZIP.
