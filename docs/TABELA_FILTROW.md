# Zestawienie zmienionych filtrów (profil ACTIVE)

Przepływ: dane → wskaźniki → strategia → kandydat → filtr → trigger → AI → wyświetlenie → wykonanie. Liczby odrzuceń z replay (SYNTHETIC, 30.0 h): `drafts` = rozpoznane struktury (warunki konieczne spełnione), `below_watch` = odrzucone przez próg WATCH, `published_*` = opublikowane odczyty w danym etapie (sumowane po krokach).

| Filtr | Cel | Zakres | Decyzja |
|---|---|---|---|
| Zgodność H4 i H1 (M02 SCALP) jako warunek każdego setupu | kierunek strukturalny | cały skaner (ORIGINAL) | ZASTĄPIĆ PUNKTACJĄ: w ACTIVE kontekst HTF = 10 pkt; konflikt raportowany z horyzontem (COUNTERTREND); ORIGINAL bez zmian |
| Pięć warunków CORE M03E (przewaga, FVG/OB, płynność, ścieżka, unieważnienie) dla każdej okazji | jakość lokalizacji | M07 (ORIGINAL) | OGRANICZYĆ DO STRATEGII: każda S01–S10 ma własne warunki konieczne; nie wymagamy jednocześnie retestu, OB, FVG i sweepu |
| Oczekiwanie na zamknięcie wszystkich TF / pełny cykl tylko po zamknięciu świecy | brak look-ahead | cały skaner | OGRANICZYĆ: skan co ≥ 2 s przy nowych danych; świeca tworząca się tylko dla WATCH/EARLY, CONFIRMED wyłącznie na zamkniętej |
| RSI + MACD + nachylenie EMA jako osobne potwierdzenia | momentum | punktacja | USUNĄĆ DUPLIKAT: jedna kategoria momentum (mediana 3 głosów), 20 pkt |
| Brak opcjonalnego DXY | kontekst USD | strategie z wymogiem DXY | PUNKTACJA: 5 pkt „dodatkowe” (0 przy braku), nigdy weto |
| Brak kalendarza / newsów | ryzyko makro | wykonanie | ZACHOWAĆ TYLKO DLA WYKONANIA: okno wydarzenia blokuje zlecenie; brak kalendarza = UNKNOWN, nie blokuje prezentacji |
| Oczekiwanie na odpowiedź Claude | druga opinia | wykonanie | ZACHOWAĆ TYLKO DLA WYKONANIA (VETO, maks. 60 s); lokalny WATCH/EARLY pokazywany od razu (AI_PENDING) |
| Blokada wykonania (READ_ONLY, ryzyko, limity) przeniesiona na prezentację | bezpieczeństwo | monitor | USUNIĘTE z prezentacji: setup widoczny z przyczyną zablokowanego wykonania; blokady wykonania bez zmian |
| Stałe WAIT/NO_TRADE i diagnostyczne side='LONG' (M00U10/U10) | diagnostyka READONLY | paczka wejściowa | NIE UŻYWANE do analizy (od 1.0); BLOCKED legacy rozdzielone od execution_permission |
| Globalne wymaganie historii | warm-up wskaźników | cały skaner | OGRANICZYĆ DO STRATEGII: min_bars per strategia, brak TF blokuje tylko strategie, które go wymagają |
| Cooldown | przeciw powtórzeniom | detekcja/zlecenia/powiadomienia | ROZDZIELONE: detekcja bez cooldownu (struktura publikowana raz), zlecenia – UNIQUE entry_key, powiadomienia – tylko EARLY/CONFIRMED/unieważnienie |
| Jakość danych, STALE, offset czasu, FUTURE_CANDLE | poprawność danych | cały system | ZACHOWAĆ (twarde): STALE nie tworzy nowych setupów |
| Limity ryzyka, RR netto, koszty, min. lot, uprawnienia | ochrona kapitału | wykonanie | ZACHOWAĆ bez zmian (nie obniżane dla liczby sygnałów) |
| Progi punktacji ACTIVE 40 / 55 / 70 | selekcja prezentacji | ACTIVE | NOWE (robocze): CONFIRMED wymaga dodatkowo prawdziwego triggera strategii |

## Lejek kandydatów (przed i po filtrach) – replay

| Strategia | Struktury (drafts) | Odrzucone progiem WATCH | WATCH | EARLY | CONFIRMED | Unikalne setupy |
|---|---|---|---|---|---|---|
| S01 | 61 | 6 | 43 | 11 | 1 | 19 |
| S02 | 36 | 1 | 15 | 10 | 10 | 11 |
| S03 | 74 | 0 | 13 | 45 | 16 | 66 |
| S04 | 14 | 1 | 11 | 1 | 1 | 6 |
| S05 | 3 | 0 | 3 | 0 | 0 | 2 |
| S06 | 82 | 3 | 31 | 31 | 17 | 27 |
| S07 | 81 | 7 | 51 | 10 | 13 | 54 |
| S08 | 29 | 0 | 17 | 8 | 4 | 13 |
| S09 | 47 | 22 | 11 | 6 | 8 | 18 |
| S10 | 163 | 0 | 159 | 3 | 1 | 69 |

Dalsze filtry wykonania (ryzyko, tryb, AI, makro) nie są symulowane w replay – działają w aplikacji i ich przyczyny są widoczne w drzewie decyzji.
Progi nie zostały obniżone „bo dawno nie było sygnału”; zmiana progów prezentacji nie zmienia progów wykonania ani limitów ryzyka.
