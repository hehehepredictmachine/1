# M04N v1.1.0 — raport audytu i zmian

**CANDIDATE / READ-ONLY / PENDING APPROVAL**. Wersja osobna, wcześniejszy M04N v1.0.0 niezmieniony.

### Zmiany

- Dodano `FF_CALENDAR` — publiczny eksport tygodniowy Forex Factory (`nfs.faireconomy.media/ff_calendar_thisweek.json`).
- Dodano `MM_CALENDAR` — publiczny eksport tygodniowy Metals Mine (`nfs.faireconomy.media/mm_calendar_thisweek.json`).
- Rozszerzono konfigurację host allowlist, harmonogram odczytu (domyślnie 30 minut), SQLite, diagnostykę źródeł.
- Normalizacja ISO UTC, US/USD, CH/CNY, filtrowanie zdarzeń metali, walidacja payload JSON oraz brak fałszywego czasu dla `Tentative`.
- Konserwatywna klasyfikacja impact, odrębne `actual`/`forecast`/`previous`, brak automatycznych prognoz kierunku.
- Deduplikacja tytuł+waluta+minuta, pochodzenie w `provider_sources` i `provider_occurrences`, BLS z pierwszeństwem dla dokładnego duplikatu.
- Nie traktuje kalendarzy Forex Factory i Metals Mine jako dwóch niezależnych potwierdzeń (rodzina Fair Economy).
- Stare źródła nie są używane w bieżących alertach; brak źródła oznaczony `UNAVAILABLE_OR_STALE`.
- Uaktualnione `M04N_VIEWER.py`, `M04N_OUTPUT_SCHEMA.json`, pliki dokumentacji oraz eksport `M04N_M04_CONTEXT_BRIDGE.json`.
- Strony `/news` dodane jedynie jako linki referencyjne, **nie** jako automatycznie pobierane news feedy.

### Testy offline

- M04N_TESTS: 96 testów (wcześniejszy kod, adaptacja oczekiwań kontraktu) — PASS.
- M04N_M04_CONTRACT_TESTS: 6 testów — PASS.
- M04N_FAIR_ECONOMY_TESTS: 51 testów — PASS.
- **153/153 PASS** z lokalnymi fixturami bez zewnętrznych żądań HTTP.
- `M04N_DEMO_OFFLINE.py` — generuje wyraźnie syntetyczne raporty, wszystkie uprawnienia `BLOCKED`.
- Raport JSON: walidowany składniowo, kontrakt schematu `module_version=1.1.0`, `execution_permission=BLOCKED`.

### Ograniczenia

- Brak przeprowadzonej weryfikacji prawdziwego połączenia z serwerami Forex Factory/Metals Mine na Windows użytkownika. HTTP 403/429/zmiana eksportu mogą powodować degradację źródła.
- Raporty `HIGH` nie są sygnałami LONG/SHORT, a forecast/actual bez oficjalnego potwierdzenia nie służą do wyznaczania sygnałów na podstawie surprise.
- Nie jest to kompletny kalendarz USA/świata, pokrycie tylko tygodniowe i z założenia częściowe.
- Nie wykonuje zleceń ani automatycznie nie modyfikuje innych modułów.
