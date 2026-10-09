# Zestawienie zmienionych filtrów (profil ACTIVE)

Przepływ: dane → wskaźniki → strategia → kandydat → filtr → trigger → AI → wyświetlenie → wykonanie. Liczby odrzuceń z replay (SYNTHETIC, 575.0 h): `drafts` = rozpoznane struktury (warunki konieczne spełnione), `below_watch` = odrzucone przez próg WATCH, `published_*` = opublikowane odczyty w danym etapie (sumowane po krokach).

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
| S01 | 1023 | 67 | 776 | 137 | 43 | 410 |
| S02 | 901 | 149 | 357 | 243 | 152 | 130 |
| S03 | 1574 | 3 | 400 | 737 | 434 | 1369 |
| S04 | 310 | 13 | 197 | 43 | 57 | 140 |
| S05 | 154 | 0 | 141 | 2 | 11 | 76 |
| S06 | 1566 | 33 | 793 | 541 | 199 | 578 |
| S07 | 1624 | 220 | 1136 | 92 | 176 | 1044 |
| S08 | 775 | 22 | 455 | 204 | 94 | 418 |
| S09 | 699 | 289 | 238 | 96 | 76 | 275 |
| S10 | 2898 | 35 | 2755 | 64 | 44 | 1308 |

Dalsze filtry wykonania (ryzyko, tryb, AI, makro) nie są symulowane w replay – działają w aplikacji i ich przyczyny są widoczne w drzewie decyzji.
Progi nie zostały obniżone „bo dawno nie było sygnału”; zmiana progów prezentacji nie zmienia progów wykonania ani limitów ryzyka.
