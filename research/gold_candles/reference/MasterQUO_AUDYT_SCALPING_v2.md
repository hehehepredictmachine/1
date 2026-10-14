# Audyt MasterQUO XAUUSD EXECUTION LOCK i plan usprawnień

Data: 14.10.2026. Źródło audytu: załączony `MasterQUO_XAUUSD_EXECUTION_LOCK_PROMPT(1).md`, przeczytany w całości. Zakres: poprawność specyfikacji, wykonalność scalpingowa, modelowanie świec, prognozy i przygotowanie modułu Python. Nie otrzymano historii transakcji, ticków brokera ani repozytorium działającego bota.

## Werdykt

Prompt dobrze opisuje ochronę rachunku, zamknięte świece, koszty, deduplikację i zakaz wymyślania wyników. Nie wykazuje jednak przewagi rynkowej. Jego głównym problemem jest połączenie wolnego potwierdzania setupu z bardzo krótkim oknem wykonania oraz zestaw arbitralnych progów, których łącznej przepustowości nie sprawdzono.

Najważniejsze poprawki dotyczą kolejności zdarzeń, dopuszczenia świec odrzucenia, weryfikacji ekonomiki wszystkich ścieżek wyjścia i oddzielenia prognozy ceny od prawdopodobieństwa zyskownej transakcji. Nowa wersja jest propozycją do testowania. Szybsze potwierdzenie nie oznacza automatycznie lepszego wyniku.

## Ustalenia i proponowane poprawki

P0 = poprawność danych/wykonania. P1 = istotny wpływ na konstrukcję scalpingową. P2 = jakość badań, monitoringu lub utrzymania.

| Priorytet | Miejsce v1 | Problem i skutek | Poprawka v2 |
|---|---|---|---|
| P0 | §4, czas MT5 | Nie wskazano różnicy między czasem SDK Python i ewentualnym czasem eksportu serwera. Podwójne przesunięcie UTC może przesunąć świece i sesje. | SDK Python: epoch UTC bez dodatkowego offsetu; eksporty tekstowe wymagają jawnej strefy. |
| P0 | §3–4 | Sam fakt, że upłynął czas świecy, nie opisuje otrzymania i finalizacji jej danych. | Czytanie MT5 od pozycji 1, znacznik close/received, kontrola harmonogramu, rewizji i opóźnień. |
| P0 | §6 | „Niezależne” odbicia nie są dowodem niezależności statystycznej. | Rozłączne epizody kontaktu z określonym resetem; zależność wyników uwzględniana w walidacji. |
| P0 | §7 | Brak precyzyjnego rozstrzygnięcia zdarzeń M5/M30 zamykających się jednocześnie może dać różne decyzje. | Jeden pakiet zdarzeń czasu t; aktualizacja zamkniętego M30 przed oceną M5, bez przesuwania początku ważności triggera. |
| P0 | §9 | RR_profile jest maksymalnym wynikiem dwóch celów, nie EV. Pozostają TP1→SL, TP1→BE, TIME_EXIT i wyjście przy utracie L. | Zachować filtr geometryczny, a przewagę wyceniać z rzeczywistych ścieżek P&L netto. |
| P0 | §9–11 | Wykres Bid nie potwierdza wykonania SELL SL/TP po Ask. | Jawny price basis; replay Bid/Ask, ograniczenia brokera i realne potwierdzenia. |
| P0 | §10–11 | „Zarządzaj pozycją bez połączenia” nie gwarantuje lokalnego TIME_EXIT ani BE. | Ochronny SL na serwerze; lokalne zarządzanie wymaga łączności. Po awarii odtworzyć stan brokera. |
| P0 | §11 | BE po kosztach nie ma dokładnego modelu pozostałej części i opłat minimalnych. | Liczyć faktyczne pozostałe koszty oraz warunki Bid/Ask; nie ogłaszać BE przed potwierdzeniem. |
| P1 | §5–7 | Pivot z dwiema świecami po prawej potwierdza się około 60 minut po końcu świecy pivotu. Drugie odbicie może dodatkowo czekać około 25 minut na M30. | M30 jako znany kontekst; dwa epizody potwierdzane na M5. Pivot pozostaje poziomem potwierdzonym dopiero w confirmed_at. |
| P1 | §7 | Korpus >=50% odrzuca część hammerów/pin barów, które pokazują silne odrzucenie knotem. | Rozdzielić rodzinę odrzucenia i rodzinę kontynuacji, z własnymi warunkami korpusu/knota. |
| P1 | §7 | Pierwszy słaby retest jest natychmiast unieważniany, nawet jeśli strefa utrzymuje się. | Z góry określone okno maksymalnie 2 świec M5 na potwierdzenie; naruszenie struktury kończy setup natychmiast. |
| P1 | §7 | 5 sekund ważności ma mały margines na dostarczenie danych i wycenę. | Kandydat 30 sekund z kontrolą opóźnienia i świeżego ticka. To parametr do porównania z v1. |
| P1 | §7 | Sztywne 0,50 USD nie skaluje się ze zmiennością. Przy A5>=10 epsilon>=0,50, więc wejście jest matematycznie niemożliwe. | Ograniczać odchylenie od ceny triggera według ATR i pozostałej odległości do TP1; nadal wymagać R:R i kosztów. |
| P1 | §6,8 | Każdy knot poniżej głębokiej strefy unieważnia BUY, choć sweep może być właśnie pożądanym zdarzeniem. | Dopuścić ograniczone naruszenie knotem z powrotem; zamknięcie poza granicą lub nadmierna penetracja unieważnia wzorzec. |
| P1 | §9 | SL od reclaimu obejmuje czasem głęboki retest. Gdy druga reakcja jest też reclaimem, ten SL może być bardzo szeroki. | SL z faktycznego retestu L po reclaimie; nie z pominięciem niekorzystnych świec i nie z wymyślonego pivotu. |
| P1 | §5 | Najbliższa liczba podzielna przez 5 nie jest automatycznie wsparciem/oporem. | Wymagać lokalizacji przy potwierdzonym poziomie XAUUSD lub używać poziomu podanego wcześniej; freeze przed kontaktem. |
| P1 | §8 | Jednoczesne progi ER, percentyli ATR, ATR/g, dwóch swingów, sesji i sweepu mogą prawie wyzerować liczbę setupów. | Mierzyć odpływ kandydatów po każdej bramce; filtry jakości danych/ryzyka obowiązkowe, filtry przewagi muszą wykazać przyrostową wartość. |
| P1 | §5 | Oba rodzaje rosnących swingów wymagane jednocześnie mogą spóźniać rozpoznanie przejścia reżimu. | Jedna jawna klasyfikacja kontekstu M30; stare pivots jako lokalizacja i kontrola struktury, z limitem świeżości. |
| P1 | §8 | Okna sesyjne są założeniem, a nie dowodem godzin przewagi. | Oceniać wynik po kosztach według godzin i DST; zachować odrębność sesji analitycznych oraz godzin brokera. |
| P1 | §11 | Automatyczne BE po TP1 może ucinać drugą część na naturalnym cofnięciu. | Testować stałe BE względem BE po TP1 i potwierdzonym utrzymaniu mikrostruktury; wybór offline, jedna aktywna reguła. |
| P1 | §13 | Brakuje wykonywalnego modułu świec i mierzalnych celów prognozy. | Moduł OHLC → cechy → formacje → kontekst → prognoza 5/15/30 min, z oddzielnym statusem walidacji. |
| P0/P1 | §13–14 | P(UP) następnego close nie jest P(TP przed SL) ani szansą zysku po kosztach. | Prognoza ceny w shadow; model wyniku transakcji wymaga osobnych etykiet z replayu strategii. |
| P2 | §14 | 200 pozycji i 30 dni nie są gwarancją mocy statystycznej, zwłaszcza przy skorelowanych setupach. | Raport liczby dni/bloków, zależności, niepewności, stabilności sesji i liczby testowanych wariantów. |
| P2 | §14 | Wysoka accuracy kierunku nie dowodzi użyteczności ekonomicznej, szczególnie przy dużej klasie FLAT. | Brier, log loss, calibration, balanced accuracy, kosztowa użyteczność i porównanie do baseline. |
| P2 | §13–14 | Drifty i aktualizacja modelu nie mają dokładnych warunków uruchomienia/rollback. | Wersje, kontrakty cech, trening offline, rejestr modeli, blokada na rewizję danych oraz rollback. |
| P2 | Całość | Brak rozdzielenia stanu wzorca, prognozy, walidacji i połączenia może utrudnić monitorowanie. | Oddzielne state machines i czytelne powody WAIT/BLOCKED/EXPIRED/INVALIDATED. |
| P2 | Całość | Rozbudowany prompt może być różnie interpretowany przez agenta. | Parametry z jednostkami, deterministyczny pseudokod, testy granic, schemat JSON i jednoznaczna kolejność. |

## Co zachować

Jedną strategię i lustrzane BUY/SELL; gold-only; zamknięte świece; brak automatycznego SELL przy braku BUY; brak martingale; realne Bid/Ask, opłaty i margin; ryzyko maksymalnie 0,25% equity; limity dzienne/tygodniowe; deduplikację; kalendarz; weryfikację tickową; brak XAUT, astrologii i niezwalidowanego ML w aktywacji zleceń.

## Ekonomika na przykładzie 4140

Przy wejściu 4140, SL 4132,5 i TP 4145/4150 wartości brutto wynoszą odpowiednio 0,67R i 1,33R. Podział 50/50 daje 1,00R przy osiągnięciu obu celów. Próg 1,20R z v1 blokuje taki układ jeszcze przed kosztami.

Przy późniejszym wejściu 4140,4 z tym samym SL wartości spadają do około 0,58R, 1,22R i 0,90R dla profilu 50/50. To pokazuje koszt opóźnienia, ale nie uzasadnia sztucznego przybliżania SL.

Hipotetyczny SL 4138,7 przy wejściu 4140,4 daje około 2,71R / 5,65R i profil 4,18R brutto. Jest dopuszczalny wyłącznie wtedy, gdy rzeczywisty retest L utworzył taki poziom, pozwala na niego broker, a rzeczywiste koszty i minimalny odstęp SL mieszczą się w budżecie. Nie znamy danych brokera pozwalających ocenić wykonalność tego przykładu.

## Moduł, który został zbudowany

W archiwum znajduje się działający, samodzielny moduł `gold_candles`:

- `data.py`: wejście CSV, ścisła geometria OHLC, UTC, zamknięte świece, symbole XAUUSD/XAUUSD-, kontrola duplikatów, luk i pełnych agregatów M30;
- `mt5_reader.py`: odczyt z już otwartego terminala Windows, dokładna nazwa symbolu, weryfikacja XAU/USD i tick size, pozycja 1, Bid/Ask i wiek ticka;
- `patterns.py`: 23 jawnie zdefiniowane flagi formacji w rodzinach, pomiary korpusu/knotów, ATR14 Wildera, bez liczenia nakładających się formacji jako niezależnych dowodów;
- `features.py`: wyłącznie przyczynowe cechy M5, M30 dostępne w chwili decyzji, etykiety 1/3/6 świec i chronologiczne rozdzielenie z purge;
- `model.py`: multinomial logistic baseline, osobny etap kalibracji, kwantyle conditional delta ceny i portable JSON zamiast pickle;
- `analysis.py`: raport formacji, prognoz i odrębny Execution Lock, który w tym samodzielnym module zawsze blokuje zlecenia;
- `cli.py`: demo, CSV, trening offline, odczyt MT5, eksport historii i ciągły monitoring zamkniętych świec z kontrolą rewizji.

Nie zbudowano kompletnego silnika zleceń MasterQUO ani jego backtestera, ponieważ repozytorium bota i dane rachunku nie zostały załączone. Moduł nie wysyła zleceń. Rozpoznawanie świec działa bez modelu; prognozowane prawdopodobieństwa i zakresy wymagają treningu.

### Znaczenie prognozy

UP/FLAT/DOWN odnoszą się do zmiany przyszłego close względem aktualnego close i pasma 0,20 bieżącego ATR14 M5. Horyzonty to 5/15/30 minut, tylko dla ciągłego przebiegu M5. Rynek może wykonać ruch w przeciwną stronę wcześniej; model close nie opisuje drogi między świecami.

Kwantyle q10/q50/q90 są oszacowaniem warunkowego rozkładu przyszłej zmiany ceny. Przedział q10–q90 nie gwarantuje pokrycia 80% przyszłych obserwacji; faktyczne pokrycie jest mierzone w holdoucie. Bez modelu wynik jest `NO_TRAINED_MODEL` i `probabilities = null`.

To nie jest gotowa „sieć neuronowa o wysokiej skuteczności”. Implementacja zaczyna od sprawdzalnego baseline. LSTM/TCN/Transformer można porównywać później na tych samych podziałach i po uwzględnieniu opóźnienia oraz kosztu utrzymania. Złożoność modelu powinna wynikać z przyrostowej wartości OOS.

## Kolejność dalszych prac

1. Usunąć błędy czasu, ceny wykonania i chronologii zdarzeń; odtworzyć v1 jako baseline.
2. Porównać v2 z v1 na tych samych historycznych danych Bid/Ask, bez strojenia na holdoucie.
3. Mierzyć przepustowość bramek: kandydaci, dwa epizody, reclaim, retest, RR, koszty, realne wykonania.
4. Oddzielnie sprawdzić nowe świece odrzucenia, okno 2 świec i zmianę TTL. Nie włączać wszystkich badanych modyfikacji jednocześnie bez analizy ich przyrostowej wartości.
5. Wytrenować i skalibrować forecaster ceny na danych rzeczywistego feedu. Raportować także wynik względem prognozy częstości klas i prostych modeli bez formacji.
6. Dopiero po zbudowaniu tickowego symulatora pozycji uczyć przewidywania wyniku całej transakcji, z częściowymi wyjściami i opłatami.
7. Uruchomić forward demo, analizować różnice między planem a wykonaniem, freeze wersji i ewentualny rollback.

## Wykonana weryfikacja

29 testów automatycznych zakończyło się powodzeniem, w tym testy filtracji świecy bieżącej, UTC, odrzucenia błędnych OHLC, pełnego M30, niezmienności cech po dopisaniu przyszłych świec, purge etykiet, symetrii formacji, modelu z przyszłości, eksportu modeli i braku zgody na zlecenie. Testy modelu korzystają z jawnie syntetycznych danych i nie mierzą przewagi na złocie.

SDK MT5 sprawdzono testem adaptera ze stubem API. Nie wykonano połączenia z rzeczywistym terminalem Windows, backtestu P&L, forward demo ani treningu na historii brokera. Ochrona serwerowego SL i faktyczne opłaty pozostają zadaniem integracji.

## Źródła techniczne

- S1: [MT5 copy_rates_from_pos](https://www.mql5.com/en/docs/python_metatrader5/mt5copyratesfrompos_py): pozycja 0 oznacza bieżącą świecę; odczyt zwraca OHLC i inne pola.
- S2: [MT5 copy_rates_from](https://www.mql5.com/en/docs/python_metatrader5/mt5copyratesfrom_py): dane API Python mają czas UTC.
- S3: [scikit-learn — calibration](https://scikit-learn.org/stable/modules/calibration.html): prawdopodobieństwa wymagają oceny i kalibracji; trening kalibratora ma być rozdzielony od treningu modelu.
- S4: [scikit-learn — pitfalls](https://scikit-learn.org/stable/common_pitfalls.html): preprocessing z użyciem zbioru testowego prowadzi do przecieku.
- S5: [TimeSeriesSplit](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html): podział czasowy respektuje kolejność; nasze etykiety wymagają dodatkowej kontroli ich końców i purge.
- S6: [Quantile regression example](https://scikit-learn.org/stable/auto_examples/ensemble/plot_gradient_boosting_quantile.html): przykład szacowania przedziałów przez modele kwantylowe.
- S7: [TA-Lib — functions](https://ta-lib.org/functions/): katalog nazw formacji. Implementacja w paczce jest własna i nie deklaruje identycznych wyników z TA-Lib.
- S8: [MQL5 — symbol properties](https://www.mql5.com/en/docs/constants/environment_state/marketinfoconstants): właściwości kontraktu, ticków i ceny wykresu.

Ocena opóźnień, R:R, sprzeczności bramek oraz proponowane reguły v2 są wnioskami z audytu załączonej specyfikacji. Nie są wynikami empirycznego porównania strategii.

