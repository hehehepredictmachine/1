# M15 — kontrakt integracji v1.0.0-CANDIDATE

**Zakres tylko M15.** `schema_version=2.0.0`. Nie zmienia M00–M14/M16. Domyślnie analiza bez publikowania i bez wysyłania zleceń.

## Przepływ danych

```text
MT5 terminal.exe/terminal64.exe -----> M01 (primary quote/bars/history)
TradingView authenticated alerts ----> M01 (supplemental only)
                                      M16 (runtime health, scheduling)
M02–M13 + M09 router + M10 setup + M11 risk ---> M14 (ANALYSIS decision, BLOCKED execution)
                                                   |
                                                   v
                                         M15 (validate + present)
                                         |                |
                                   atomic JSON         SQLite outbox
                                         |                |
                                   local monitor      Telegram sendMessage
                                                      EXPLICIT OPT-IN ONLY
```

### Minimalna współpraca z M14

Silnik konsumuje **oryginalny wynik referencyjnego M14** (`M14_SYNTHETIC_OUTPUT.json` tylko w testach) wraz z opcjonalnym kontekstem z przyszłego integratora. Wymagany `analysis_id`, znany `as_of` ISO offset, `module_id=M14`, `schema_version=2.0.0`, `decision_scope=ANALYSIS`, rzeczywista decyzja, blokady, flags i enum. Wejście jest sprawdzane przed zapisem plików.

M14 referencyjny nie może autoryzować zlecenia. M15 odrzuca próby ustawienia AUTHORIZED, live flag, order_actions, broker_order_sent lub submitted_order_id. Wsparcie przyszłego zaufanego wykonawcy wymaga *nowego audytu i odrębnego adaptera* — nie wolno rozluźniać tego warunku jedynie przez zmianę JSON.

### Kontekst renderowania

Opcjonalny plik JSON (`--context`) może zawierać `analysis_id`, `snapshot_as_of`, `instrument_id`, `account_type=ZERO_SPREAD`, `quote={source:MT5_PRIMARY,instrument_id,as_of,bid,ask}`, `plan={price_source:MT5_PRIMARY,instrument_id,as_of,entry,sl,tp1,tp2,tp3,plan_status}`, `next_expected_event`, `invalidation`, `opposite_scenario`, kolekcje setupów, statystyki z ich provenance i pozostałe rekordy systemu. Pola liczbowe, których nie ma, pozostają null.

**Ograniczenie:** M15 nie kryptograficznie uwierzytelnia pliku z kontekstem ani M14. Dlatego pola dołączone przez integrator mogą jedynie wspierać prezentację, nie awans do LIVE. Zatwierdzenie prawdziwych danych brokera musi odbyć się upstream w M01/M14 i przyszłej warstwie zaufania.

### Wyjścia

- `M15_EXPORT_FULL.json` — kanoniczny dokument, schema 2.0.0, uwzględnia wyjście M14 i wyłącznie dostarczone pola.
- `M15_MONITOR_SNAPSHOT.json` — atomowy plik dla UI, bez wykonywania zleceń; nie jest samodzielnym procesem stale pobierającym ceny.
- `M15_COMPACT_PL.txt`, `M15_FULL_PL.txt` — teksty analiz po polsku; brak danych oznaczony N/D.
- `M15_DELIVERY_OUTBOX.sqlite3` — trwały lokalny status alertów.
- `M15_LAST_DELIVERY_STATUS.json` — wynik ostatniej operacji kolejki/dostarczenia.

### Idempotency / delivery

Materiały w kolejce mają fingerprint treści materialnej, a zmiany czasu obserwacji bez nowych zdarzeń nie powodują nowego alertu. Dla kolejnych aktualizacji dostarczaj stabilny event ID. Timeout Telegrama: `UNKNOWN`, bez automatycznego retry; API Telegram `sendMessage` nie zapewnia zdalnego idempotency key. Dedupe jest lokalne i chroni przed powieleniem w obrębie jednej bazy, nie daje gwarancji exactly once przy awariach/replikacji.

### Uruchomienie Windows / Python 3.10+

```powershell
py -3 M15_REFERENCE_COMMUNICATION_ENGINE.py --m14 M14_REFERENCE_SYNTHETIC_OUTPUT.json --output-dir .\M15_OUTPUT
py -3 -m unittest M15_TESTS -v
```

Rzeczywista wysyłka *wyłącznie po świadomym uruchomieniu* i poprawnej konfiguracji użytkownika (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`) oraz użyciu `--telegram-send`. Nie dołączamy żadnych sekretów do ZIP. Nigdy nie używaj przykładowego pliku syntetycznego do rzeczywistych alertów.

```powershell
# Przykład składni, BEZ gotowych tokenów, NIE uruchamia zleceń MT5:
py -3 M15_REFERENCE_COMMUNICATION_ENGINE.py --m14 .\REAL_M14_RESULT.json --context .\REAL_CONTEXT.json --output-dir .\M15_OUTPUT --telegram-send
```

### Poza zakresem

Brak automatycznego połączenia do MT5 i UI, brak odbiornika TradingView, brak webhook server, brak routingu Telegram z prawdziwym botem w tej sesji, brak systemowej usługi 24/7, brak autoryzacji zleceń, brak handlu LIVE. M16 powinien harmonogramować M15 na eventy; M01 dostarcza spójne snapshoty. Zintegrować i odebrać lokalnie na DEMO przed produkcją.
