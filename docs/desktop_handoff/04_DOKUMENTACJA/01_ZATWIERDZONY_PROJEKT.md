# Zatwierdzone ustalenia — PepeMarketWizard Desktop

## Cel produktu

Jedna aplikacja Windows z EXE, własnym oknem i klientem; istniejący silnik bota i terminal MT5 pozostają punktem wyjścia. Projekt ma zostać faktycznie zintegrowany, a nie zastąpiony danymi z makiet. Głównymi instrumentami są XAUUSD i BTC, przy czym symbol brokera dla BTC trzeba potwierdzić. Symbol użytkownika dla złota to `XAUUSD-`.

## Wspólna oprawa

Ciemny grafit/zieleń, delikatne złote akcenty oraz Pepe Czarodziej z dołączonego pliku graficznego. Wyraźna hierarchia informacji, przyciski z podpisami, statusy również tekstem, przełączanie instrumentu, świeżość danych i rzeczywisty tryb/rachunek. Wybór pełnego koloru akcentu, tła, panelu, tekstu, wielkości czcionki oraz intensywności/wyłączenia animacji. Zapis preferencji w kliencie; kontrola kontrastu i obsługa ograniczonego ruchu.

## Panel 1 — Trading Intelligence

- Domyślnie cztery interwały M5, M15, H1, H4, w układzie 2×2; dostępne M1, M5, M15, M30, H1, H4, D1 według danych. Układy 1/4/6, zmiana interwału per wykres, powiększenie, tryb wykresów, pamiętanie układu. Przełączenie XAUUSD/BTC synchronizuje wykresy.
- Sekcja Signal Intelligence: wybór setupu, kierunek, warunki, trigger, invalidation, ceny planu, powody, wyniki modeli tylko z prawdziwego źródła. Rozróżnienie „brak sygnału” od „brak zlecenia”.
- Balance, equity, otwarty P/L, ROI oraz pozostałe statystyki z MT5 i określonym okresem/metodą. Brak danych = `—`, nie 0. Podgląd planu przed ewentualną ręczną akcją.

## Panel 2 — AI Neural Lab

- Neural Universe z różnymi ilustracyjnymi kształtami: warstwy MLP, las drzew Random Forest, kaskada drzew XGBoost, trajektorie Monte Carlo. Struktura, przepływ, ścieżka, wybór elementu, obrót, zoom, pauza, replay i sterowanie intensywnością.
- Faktyczną strukturę pokazuj tylko, kiedy jest dostępna w modelu. Graf poglądowy zawsze jest jednoznacznie oznaczony; nie udawaj aktywacji, treningu ani metryk.
- Sekcje treningu, walidacji i wdrożeń: źródło danych, status, wersja, wyniki poza próbą, wersjonowanie, test i ręczna decyzja o LIVE; brak danych = nieznany/N/A. Replay bez wycieku przyszłości.

## Panel 3 — Centrum Sterowania

- Status silnika, MT5, rachunku, czasu danych; konfiguracja terminala, XAUUSD-/BTC, Telegrama, dźwignia odczytana z brokera oraz diagnostyka.
- Tryby SIGNALS, PAPER, AUTO DEMO, AUTO LIVE z opisem konsekwencji. Przy pierwszym wyborze AUTO LIVE jawne podsumowanie rachunku i ryzyka. STOP zatrzymuje nowe wejścia; zarządzanie otwartymi pozycjami według rzeczywistej dostępności MT5 i ustawień.
- Ryzyko na transakcję, dzienny limit i maksymalna liczba pozycji jako świadomie ustawiane parametry, nie wartości wymyślone w makiecie. Rzeczywiste Bid/Ask, spread, prowizja i poślizg.
- Po zamknięciu okna opcja pracy w tle albo zakończenia, opcjonalny autostart, czytelny status działania. Execution Lock ma zostać wycofany, bez zastępowania go ukrytą blokadą.

## Strategie i bezpieczeństwo działania

Sygnały i zlecenia mają być oceniane osobno. Usunąć zdublowane/sprzeczne bramki, a brak opcjonalnego AI/modelu/wskaźnika nie powinien bez uzasadnienia zatrzymywać analizy. Zachować rzeczywiste wymagania brokera, jednoznaczny rachunek i tryb, jawne limity użytkownika, STOP, idempotencję i obsługę istniejących pozycji. Przed/po porównać na tych samych danych, po kosztach, poza próbą; nie deklarować wyższej skuteczności bez wyników.

Wcześniejsza specyfikacja scalpu określała ruchy ceny XAUUSD 2,5 / 3 / 5 USD i break-even po TP2. Nie utożsamiać ruchu ceny z zyskiem rachunku. Prowizja i poślizg nie są automatycznie zerowe z powodu rachunku Zero.

## Zakres zatwierdzenia

Użytkownik zaakceptował kierunek trzech przedstawionych makiet. Pozostałe niewyjaśnione szczegóły domenowe powinny być rozstrzygnięte na podstawie kodu, wyników testów i jawnych ustawień użytkownika. Makiety nie są wdrożeniem i nie stanowią potwierdzenia połączenia, treningu, statusu rachunku ani wykonania transakcji.
