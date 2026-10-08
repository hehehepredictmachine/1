# Audyt MasterQUO M07/M03E Operational Profiles v1.0.0-CANDIDATE

## Zakres zmian

Wyłącznie nowa warstwa badawcza: `M07_M03E_PROFILE_DETECTOR.py`, `M07_M03E_PROFILE_RUNTIME.py`, `RUN_MT5_OPERATIONAL_PROFILES_READONLY.py`, konfiguracja trybów, testy i dokumentacja. Zachowane moduły M01/M02/M02I/M03/M09/M10A/M14/M15 są kopiami bez zmian w ich plikach wykonywalnych. Starsze raporty i testy w ZIP służą regresji.

## Kluczowe korekty wykryte podczas audytu

1. Wcześniejsze M03E wymagało ręcznego podawania ID FVG/POI, liquidity i struktury. Nowy adapter wybiera wyłącznie obecne `event_id` M02/M03, sprawdza dostępność i kierunek oraz tworzy plan.
2. M03E pięć CORE wymaga prawdziwego `early_evidence`. Przy automatycznym wyborze wynik jest ponownie sprawdzany przez oryginalne `early_assessment` i `construct_early`, a dopiero później M03 ponownie oblicza go w normalnym przepływie.
3. M02/M03 mogą normalizować as_of z `Z` na `+00:00`. Porównania są czasowe (UTC), nie zależne od pisowni ISO.
4. Trwały profil w SQLite zachowuje stałe reguły w trakcie lifecycle; starego FVG nie można automatycznie potraktować jako nowej wersji po zamknięciu poza granicą strefy. Rewizja granic FVG lub zmiana parametrów na tym samym event_id wymaga niezależnego nowego zdarzenia badawczego i nie awansuje istniejącego rekordu.
5. M10A stosuje osobne dowody kolejnych czterech etapów na czterech kolejnych zamkniętych świecach; wynik research nie jest autoryzacją do zlecenia.
6. Cztery profile wyświetlania trybów obejmują trzy badawcze definicje i AUTO; MVP ma jawną nową definicję.
7. Badanie M03 geometrii FVG przeprowadzono na sztucznych świecach poprzez prawdziwą funkcję `find_fvgs`, nie wyłącznie na wpisanym ręcznie znaczniku.
8. Skrypt Windows odczytuje dane tylko przez oryginalny oficjalny MT5 bridge; nie wymaga screenshotów ani OCR.
9. Ścieżki diagnostyczne pozostają WAIT/NO_TRADE, gdy M02 nie ma kierunku lub M03 nie ma kompletu dowodów; nie ma fallback typu „EMA BUY”.
10. Rachunek Zero to informacja o profilu brokera, nie gwarancja braku prowizji, spreadu i poślizgu.

## Wyniki testów (własne i regresyjne; osobne uruchomienia)

- 61 testów `M07_M03E_PROFILE_TESTS.py`: PASS, w tym geometria FVG, LONG/SHORT, M5, M15, brak danych, timestampy, M10A rules.
- 24 testy `M07_M03E_RUNTIME_TESTS.py`: PASS, w tym trwałe SQLite, cache, odłączenie MT5, fail-closed monitor i odczyt FakeMT5.
- 794 testy z zachowanej integracji `RUN_ALL_M10A_M15_TESTS.py`: PASS (oryginalne skopiowane źródła, osobny przebieg).
- Razem: 879 testów offline (794 + 85), wszystkie PASS. **Nie** interpretować jako testów rynku rzeczywistego ani dowodu edge.

## Testy niewykonane

- Historia z prawdziwego terminala użytkownika, test DEMO XAUUSD i potwierdzanie triggera na rzeczywistych sesjach: NOT_RUN.
- M06 walk-forward / FINAL_OOS / costs / forward oraz analiza win rate i expectancy netto: NOT_RUN.
- Rzeczywisty Telegram end-to-end i niezależna autoryzacja wykonawcy: NOT_RUN (Telegram opt-in, żadnych order_send).
- Baza zaufanych zatwierdzonych strategii M08 i pełna integracja pozycji/ryzyka M11: NOT_CONNECTED.

**Status: CANDIDATE / PENDING APPROVAL.**
