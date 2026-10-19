# Scalping MTF – dashboard wielu interwałów (PMW-UPD-05)

## Jak otworzyć
Panel → **Wykresy → Scalping MTF** (`#/scalp-mtf`). Dashboard działa bez żadnego modelu ML/NSS – wymaga tylko świec MT5 i profilu scalp.
Dla aktywa bez profilu scalp: `UNSUPPORTED_STRATEGY_PROFILE` (pozostałe funkcje bez zmian).

## Pięć interwałów i ich role (z profilu, nie z głosowania)
| TF | Rola | Co pokazuje |
|---|---|---|
| H1 | szerszy kontekst | SAR / nachylenie / szerokość pasm; w trybie filtra BOTH tylko informacyjnie |
| M30 | kontekst i ograniczenia | warunek filtra kontekstu strategii (tryb BOTH/ANY/ANY_PLUS_H1 z profilu) |
| M15 | kontekst lokalny | jw. |
| M5 | zakres i setup | zamrożony range (L/H/MID), strefy, ATR(M5) |
| M1 | trigger | sweep / reclaim / potwierdzenie / retest |

Kolumny LONG/SHORT w macierzy pokazują warunek „silny trend przeciw stronie” dla każdego TF; wiersz pod macierzą pokazuje werdykt
**dokładnie tej samej funkcji `fade_blocked` co silnik** (np. w trybie BOTH jeden TF „sprzeczny” nie blokuje). „Reżim (wyświetl.)”
to etykieta prezentacyjna (SAR + nachylenie 0.1) – nie jest bramką.

## Jeden snapshot = jedna prawda
Po każdym przeliczeniu strategii (nowe zamknięte M1) backend tworzy `MTFContextSnapshot` (`scalp/dashboard.py`): ten sam instrument,
epoka sesji MT5, `as_of` = zamknięcie ostatniej M1, rewizje wszystkich TF, stan maszyny, zapisane bramki ocenionych kandydatów i zgodne
wyniki modeli. Pasek, macierz, pięć wykresów i checklista używają tego samego `snapshot_id` (widoczny w pasku). Wykresy pobierają
wyłącznie świece zamknięte do `as_of` dla tego snapshotu; świeca w trakcie to osobny, szary „podgląd LIVE”.

## Świeżość bez nowej świecy
Heartbeat co 1 s (bez przeliczania wskaźników) ocenia każdy TF względem oczekiwanego zamknięcia, połączenie MT5 i wiek kwotowania
(TTL z profilu). Utrata połączenia lub zatrzymany feed zmienia status na DISCONNECTED/STALE nawet bez nowej M1; zapisana analiza się
nie zmienia, ale pasek pokazuje „analiza nieważna wg heartbeat”. H1 sprzed 40 min nie jest „nieaktualne”. Weekend bez kwotowań →
„WEEKEND_TYPICAL_CLOSE (harmonogram brokera niezweryfikowany)”, w innym przypadku SESSION_UNKNOWN / NO_RECENT_DATA.

## Wykresy, zoom i synchronizacja
* Każdy wykres ma własny zoom (zapamiętany per wykres/instrument/TF), przycisk ⟲ resetuje tylko ten wykres.
* „kursor” – synchronizacja kursora w obrębie dashboardu, tylko dla tego samego instrumentu i epoki sesji; czas z M1 trafia na świecę
  wyższego TF, której przedział go **zawiera** (w luce – brak dopasowania, nigdy świeca z przyszłości).
* „zakres” – opcjonalne grupy A/B synchronizacji zakresu czasu (domyślnie niezależnie).
* Czas osi i synchronizacji: UTC.
* Presety: Pełne MTF / Wejście (M5 + M1) / Kontekst (H1/M30/M15) / Focus (jeden wykres); na telefonie macierz + jeden wykres z zakładkami.

## Setup i dowody
Panel Setup pokazuje ocenione kandydaty tego instrumentu (status SHADOW/BLOCKED/MISSED…), każdy warunek z wartością i powodem,
„Kompletność warunków” (nie P(zysk)), blokady, trigger, unieważnienie zakresu, wygaśnięcie i hipotetyczne poziomy oglądanego planu.
„dowód” ustawia kursor M1/M5 na czas sygnału. Wybór setupu jest tylko oglądaniem – nie zmienia strategii silnika.
Modele: model B (P(TP1 przed SL)), Scalp ML (P(net_R>0), PMW-UPD-03), NSS (TP1/SL/TIMEOUT, PMW-UPD-04) – każdy z własną definicją
i statusem; wynik NSS innego setupu/strony to `NOT_LINKED` (nie jest podstawiany).

## Pauza, inspekcja, powrót LIVE
„Pauza widoku” zatrzymuje tylko prezentację. „inspekcja” otwiera zapisany snapshot z archiwum (`mtf_snapshots`); świece archiwalne są
odtwarzane z bufora MT5 tylko gdy bufor nadal zawiera te same świece – inaczej `ARCHIVE_BARS_UNAVAILABLE` (nigdy nie podstawiamy
„latest”). Brak snapshotu w archiwum → `ARCHIVE_SNAPSHOT_UNAVAILABLE`. Przycisk **LIVE** wraca do bieżącego stanu.

## API
`GET /api/v1/scalp/dashboard?asset=` · `GET /api/v1/scalp/dashboard/chart?tf=&snapshot_id=` (410 SNAPSHOT_EXPIRED) ·
`GET /api/v1/scalp/dashboard/snapshots?setup_id=&cursor=` · `GET /api/v1/scalp/dashboard/snapshots/{id}` · WS `scalp_dashboard`,
`scalp_dashboard_health`.

## Rozwiązywanie problemów
* „dane: nieaktualne” – sprawdź MT5 (Dane i diagnostyka), połączenie i czy rynek jest otwarty.
* „analiza nieważna wg heartbeat” – czeka na nowe zamknięcie M1; nic nie jest przeliczane na starych danych.
* Puste wykresy z komunikatem SNAPSHOT_EXPIRED – strona automatycznie pobiera aktualny snapshot.

## Bezpieczeństwo
Dashboard nie wysyła zleceń, nie zmienia Execution Lock, strategii, dźwigni ani ryzyka. Dane syntetyczne mają etykietę DANE SYNTETYCZNE.
Testy na rzeczywistym MT5 (symbol, ceny, czas, Bid/Ask, reconnect): NIE WYKONANE w środowisku budowy – do sprawdzenia lokalnie.
