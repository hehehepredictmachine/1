# Audyt v1.0.0 Macro Guard — 8 października 2026

## Zmiany

- Dodano nowy `M04N_MACRO_GUARD.py` (ocena ryzyka M04 na odczytach M04N v1.1, niezależny M11, walidacja M14 z istniejącego M15, bez zleceń).
- Dodano `M04N_MACRO_VIEWER.py` — osobny graficzny panel na Windows z kalendarzem, stanem źródeł i dwoma odrębnymi wynikami M14/makro.
- Dodano CLI i BAT startowe, opcjonalne ostrzeżenia Telegram z deduplikacją/at-most-once attempt SQLite.
- Dodano kontrolę świeżości i pochodzenia raportów M04N/M04, fail-closed przy błędach i braku MT5, pełną dokumentację polską.
- Zachowano poprzedni program profili strategii i komplet plików M04N 1.1.0 w osobnych folderach bez ingerencji w ich kod.

## Zakres testów

W testach syntetycznych zweryfikowano: HIGH/EXTREME z kalendarza, rozbieżne/future timestamps, fałszywe COMPLETE calendar, edycję wydarzenia między raportami, brak M14, odłączenie MT5, wewnętrzne M11 BLOCKED, reakcję po restarcie, no-duplicate Telegram oraz brak możliwości wysłania zleceń.

## Ograniczenia — istotne

1. Testy offline, bez autoryzacji źródeł u brokera. Nie potwierdzono działania wszystkich zewnętrznych URL w momencie uruchomienia użytkownika.
2. Niniejszy moduł nie weryfikuje autentyczności plików JSON kryptograficznie — zakłada lokalne zaufane procesy i ograniczenia dostępu do folderu.
3. Nie ma pełnego pokrycia FOMC/BEA ani oficjalnych minut ogłoszeń wszystkich wydarzeń geopolitycznych.
4. M11 bez kompletnego `--risk-input` zawsze `BLOCKED`. Nie zostało wykonane rozliczenie spreadu/komisji na realnym MT5 Zero.
5. To nakładka monitora, a nie modyfikacja wewnętrznego pipeline przed M14 ani kontrola wykonania u brokera. Poprzedni Telegram M15 musi pozostać WYŁĄCZONY.
6. Próg ostrzeżeń HIGH/EXTREME i okna czasowe są heurystyczne, bez wyników OOS M06. Moduł nie potwierdza wzrostu rentowności.
7. Wysyłka Telegram nie była testowana na prawdziwym chat_id / serwerze. Przy wyniku UNKNOWN nie wolno bezpiecznie retry automatycznie.
8. Cały program pozostaje CANDIDATE / PENDING APPROVAL.

## Testy do odtworzenia

`py -3 RUN_MACRO_GUARD_ALL_TESTS.py`

## Wyniki wykonane w tej sesji

- `M04N_MACRO_GUARD_TESTS`: **49/49 PASS** (offline).
- `M04N_TESTS + M04N_FAIR_ECONOMY_TESTS + M04N_M04_CONTRACT_TESTS`: **153/153 PASS** (offline).
- `M07_M03E_PROFILE_TESTS + M07_M03E_RUNTIME_TESTS`: **85/85 PASS** (offline).
- `RUN_ALL_M10A_M15_TESTS.py`: **794/794 PASS** (run osobny: 679 M01–M14, 65 M15, 50 M10A/M15).
- **1081 wyników testowych** w oddzielnych przebiegach, nie w jednym wspólnym uruchomieniu.
- Pierwsza próba jednego zbiorczego uruchamiacza została przerwana przez limit czasu otoczenia; rozdzielono go na tryb 287 testów i opcjonalną długą regresję 794.
- CLI po podaniu nieistniejących raportów: **`NO_TRADE / BLOCKED`, PASS**.
- Porównanie bajtowe: `M04N_ENGINE.py` i poprzedni `RUN_MT5_OPERATIONAL_PROFILES_READONLY.py` identyczne ze źródłami (PASS).
