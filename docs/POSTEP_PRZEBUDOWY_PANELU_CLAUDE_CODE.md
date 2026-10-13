# Postęp przebudowy panelu (trzy strony) – Claude Code

Punkt odniesienia: 1.9.0 → wersja 1.10.0. **Stan: ukończone.** Routing: **hash** (`#/ai`, `#/wykresy`, `#/warunki/<setup_id>`). Hash nie wymaga fallbacku FastAPI. Wstecz/Dalej, bezpośredni link i odświeżenie działają bez 404. Nie dodano biblioteki routingu.

| Etap | Stan |
|---|---|
| 1. Mapa funkcji → strony, źródła danych | zrobione (tabela niżej) |
| 2. AppShell + routing hash + wspólny StoreProvider (jeden WebSocket poza stronami) | zrobione – `src/router.ts`, `src/components/layout/AppShell.tsx`, `src/App.tsx` |
| 3. Strona 1 „Analiza AI” (karta AI, pełne wyjaśnienie, H1/M30/M15/M5/M1, wykres główny, siatka 5) | zrobione – `src/pages/AiAnalysisPage.tsx`, adapter `src/ai.ts` |
| 4. Strona 2 „Wykresy bota” (TF z `GET /api/v1/timeframes`, widoki, kolumny, skupienie) | zrobione – `src/pages/BotChartsPage.tsx` |
| 5. Strona 3 „Warunki setupu” (lista, podsumowanie X z Y, 10 sekcji, trigger, plan, „Pokaż na wykresie”) | zrobione – `src/pages/SetupRequirementsPage.tsx`; backend `engine/setup_details.annotate` (MQ-SETUP-DETAILS-1.1.0) |
| 6. Panele dodatkowe, migracja preferencji wykresów i motywów | zrobione – `chartview.migrateLegacyViews`, `theme.tsx` (`tf:XX`, mapowanie `panel1..8`), opcje wykresów per strona |
| 7. Testy przeglądarkowe, rozdzielczości 1920×1080 / 1366×768 / 1024 / 390 | zrobione – `tests/test_ui_pages.py` (nowy), `test_ui_monitor.py`, `test_ui_setup_panel.py`, `test_ui_signal_card.py` (dostosowane) |
| 8. Build `frontend/dist`, instrukcja | zrobione – `npm run typecheck`, `npm run build`; `START_TUTAJ_PL.md`, `INSTRUKCJA_WINDOWS_PL.md` |

## Decyzje
* **Routing hash** zamiast ścieżek: backend serwuje tylko `/`, więc odświeżenie i link bezpośredni nie dają 404, a trasy API/zasobów są nietknięte.
  `#/warunki/bot` = śledź wybór bota, `#/warunki/<setup_id>` = setup przypięty przez użytkownika (zmiana wyboru AUTO go nie zastępuje; pokazujemy informację i link).
* **Oglądanie setupu nie jest mutacją.** Strona 3 czyta tylko `GET /api/v1/setups` i `GET /api/v1/setups/{id}/details`. Jedyne miejsce, które zmienia
  wybór strategii silnika (`POST /api/v1/prefs/setup-view`), to jawna karta „Działanie bota – wybór strategii silnika”. Test UI sprawdza brak tego żądania
  przy przeglądaniu, filtrowaniu, „Pokaż na wykresie”, Wstecz/Dalej.
* **AI oddzielone od pozwolenia silnika.** Karta AI ma własne stany: aktualna / wygasła / dotyczy innego setupu / scenariusz nieaktualny / brak klucza / brak odpowiedzi /
  ostatni przebieg z błędem. Tylko „aktualna” rysuje poziomy „AI:” na wykresach; plan silnika ma etykiety „Plan bota:”. Wejście na stronę nie zleca analizy AI.
* **Pięć wykresów bez szóstego.** Sloty to obszary siatki CSS; „Wykres główny” zmienia tylko `grid-area` – instancja wykresu i zoom zostają (test: `creations` bez zmian).
* **Identyfikatory wykresów** `ai-<TF>` i `bot-<TF>`; widoki zapisane pod starymi `panelN|symbol|TF` kopiowane raz (`mq.chartview.migrated.1_10`); kolory per TF (`tf:XX`).
* **Checklista w 10 sekcjach** grupowana w backendzie (opis prezentacyjny, statusy silnika bez zmian): MET / MISSING / PENDING / NO_DATA / NA → Spełnione / Niespełnione /
  Oczekiwanie / Brak danych / Nie dotyczy. Odczyty informacyjne i „nie dotyczy” nie wchodzą do mianownika „X z Y wymaganych”.
* **Etykiety zmienności zgodne ze źródłem**: „Daily High (HV-proxy 1σ)” przy HV_PROXY, „(IV 1σ)” tylko przy IV ręcznej (wcześniej zawsze „IV”).
* Szczegóły setupu innego rachunku zwracają 404 (scenariusz nie jest pokazywany jako należący do bieżącego rachunku).

## Czego nie zweryfikowano
* Windows, rzeczywisty terminal MT5 użytkownika i realne odpowiedzi Claude API (testy: symulator terminala – DANE SYNTETYCZNE – bez klucza; stany karty AI sprawdzone
  przez wstrzyknięcie wyniku w kontrakcie `agent/schema.py` do strumienia WebSocket).
* Czytniki ekranu – sprawdzono etykiety, fokus klawiatury i Escape, bez testu z czytnikiem.

## Mapa przeniesionych paneli

| Funkcja (1.9) | Nowe miejsce |
|---|---|
| Header: chipy MT5 / dane / backend / czas / AI / BOT / tryb / AUTO / ML, karty BALANCE…WIN RATE | kompaktowy pasek AppShell (symbol, MT5, dane, tryb wykonania, STOP, ustawienia, wygląd) + rozwijane „Konto” (balance, equity, żaba, daily P/L, pozycje, win rate, czas serwera, agent, ML, przełącznik AUTO/MANUAL) |
| Karta sygnału silnika (SignalTop: BUY/SELL, plan, checklista prosta, kontekst TF) | strona 1: skrót „Pozwolenie silnika” w karcie AI + pełna sekcja „Decyzja silnika” (otwarta domyślnie) |
| AgentDrawer (ocena AI, pytanie, analizuj, wnioski, historia) | strona 1: karta AI + pełne wyjaśnienie + „Analizuj teraz” / „Zapytaj AI” (bez podwójnych wysyłek); stan agenta, historia przebiegów i propozycje playbooka – sekcja „Agent” |
| Wykresy M1/M5/M15/panel 4, układ 8 TF | strona 1: H1, M30, M15, M5, M1 (wykres główny + siatka); strona 2: wszystkie TF z rejestru (D1…M1), widoki Wszystkie / Kontekst / Setup i wejście / Skupienie |
| VolPanel (poziomy dzienne, walls) | strona 2, sekcja dodatkowa „Zmienność i walls” (ze źródłem HV_PROXY / IV) |
| MarketsPanel, BotSignalsPanel, MarketDetail | strona 2, sekcja dodatkowa „Inne rynki” (podgląd nie zmienia symbolu silnika) |
| AutoPanel, LiveSetupsPanel, StrategiesPanel (reżim, ranking, monitory strategii) | AutoPanel (reżim) i StrategiesPanel (monitor S01–S12) → strona 2, sekcje dodatkowe; LiveSetupsPanel (ranking AUTO) → strona 3 |
| SetupPanel (AUTO / WYBRANY / WSZYSTKIE + szczegóły); ustawienie dźwigni z SetupPanel → `components/LeverageSettings.tsx` (Ustawienia → Ryzyko) | strona 3: lista scenariuszy z filtrami i szczegóły (oglądanie = stan prezentacji); wybór strategii silnika to osobne, jawne ustawienie „Działanie bota” |
| SignalsPanel (scenariusze, historia sygnałów, zlecenia, pozycje, rozliczone) + StatsPanel | globalny panel boczny „Pozycje i statystyki” (zakładki); plan sygnału, checklista 12A i kontekst M30/H8 → strona 3, sekcja „Sygnał silnika” |
| MLPanel | strona 3, sekcja „Podgląd ML” |
| RiskPanel | strona 3, sekcja „Ryzyko – limity” |
| NewsPanel | strona 1, sekcja rozwijana „News” |
| BotLog | globalne menu → „Logi” (panel boczny) |
| Ustawienia, tryb, STOP, wygląd/motywy, dźwignia | bez zmian (okna dialogowe z paska) |
