# Znane ograniczenia (stan na wydanie 1.0.0)

## Czego nie zweryfikowano
1. **Brak testu na Twoim Windows i terminalu MT5.** Całość sprawdzono na Linuxie z symulatorem terminala o tym samym API (`mt5/fake.py`).
   Prawdziwy pakiet `MetaTrader5` (tylko Windows) nie był uruchamiany. Pierwszy krok u Ciebie: `02_DIAGNOSTYKA.bat` i `06_DIAGNOZA_CZASU_MT5.bat`.
2. **Brak testu z prawdziwym API Claude** (brak klucza w tym środowisku). Integracja jest napisana na oficjalnym SDK `anthropic==1.7.0`
   i przetestowana z atrapą klienta (pętla narzędzi, błędy, JSON). Kształt odpowiedzi rzeczywistego modelu (np. bloki thinking, fallback)
   może wymagać drobnej korekty – sprawdź przyciskiem „Testuj połączenie” i „Analizuj teraz”.
3. **Pliki BAT nie były wykonane na Windows** (sprawdzone statycznie). Zestaw zależności z hashami zweryfikowano pobraniem kół
   win_amd64 dla cp313 i cp312.
4. **Dokumentacja MetaTrader5 (mql5.com) była zablokowana** przez politykę sieci środowiska budowy – kontrakt czasu opiera się na znanej
   treści dokumentacji i na pomiarze surowych danych w aplikacji, nie na świeżej lekturze strony.
5. **Newsy M04N** nie zostały pobrane w środowisku budowy (sieć do źródeł zablokowana) – w UI widać uczciwy status UNAVAILABLE.

## Ograniczenia metodyczne
* **Strategie są badawcze (CANDIDATE).** MVP/SMC/SCALPING i progi M07 nie mają walidacji OOS ani forward; reguła celów MQAI-LEVELS-1.0.0
  jest nowym, niezwalidowanym rozszerzeniem. Aplikacja nie dowodzi zyskowności – zalecany długi okres READ_ONLY/PAPER, potem DEMO.
* **Offset czasu**: mierzony bieżąco; przy zamkniętym rynku używany ostatni zapisany (oznaczony). Historyczne zmiany DST brokera nie są
  rekonstruowane w eksporcie historii (offset stosowany jednolicie – zapisane w manifeście).
* **Model sesji** uczy się przerw z historii H1 (godziny bez świec ≥ 80% dni). Święta i nietypowe sesje mogą być oznaczone jako luka
  niewyjaśniona (bezpieczna strona: blokada wejść na danym TF).
* **Kalendarz makro jest częściowy** (BLS + FF/MM tygodniowo). Przy domyślnym `macro_block_high_impact=true` brak kalendarza blokuje wejścia.
* **Sentyment rynkowy** nie jest dostępny (brak zweryfikowanego źródła) – panel pokazuje to wprost.
* **Prowizja** z historii transakcji wymaga ≥ 3 transakcji na symbolu; inaczej trzeba ją wpisać (bez tego wykonanie jest blokowane).
* **Netting**: istniejąca pozycja na symbolu blokuje nowe wejście (bez dokładania/odwracania).
* **Pozycje bez SL** (np. ręczne) blokują nowe wejścia (ryzyko nieograniczone). Pozycje ręczne nie są zarządzane bez jawnego przejęcia.
* **Zlecenia**: tylko rynkowe (DEAL) z SL i TP2 po stronie serwera, TP1 częściowe i BE zarządzane przez aplikację – działa, gdy aplikacja
  pracuje; po jej zamknięciu pozycje chroni SL/TP2 brokera, ale TP1/BE nie są wykonywane.
* **Wykresy**: nakładki pokazują ostatnie zdarzenia M03 (do 12/TF); strzałki/linie TP przed potwierdzeniem są opisane „(scen.)”.
* **Prawdopodobieństwa**: nie są wyświetlane (brak skalibrowanego M05P). „Win rate” liczony wyłącznie z rozliczonych transakcji.
* **DPAPI**: klucz zaszyfrowany dla bieżącego użytkownika Windows; przeniesienie folderu na inny komputer wymaga ponownego wpisania klucza.
* **Python 3.14** nie jest obsługiwany przez instalator (wybiera 3.13, potem 3.12) – świadomie, bez weryfikacji zgodności pakietów.
* **Legacy regresja**: 1 test oryginalnego pakietu (`test_40_viewer_has_six_correct_roles`) wymaga `tkinter`, którego nie było w środowisku Linux budowy.
