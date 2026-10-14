# MasterQUO XAUUSD M30/M5 — Execution Lock v2 + Candle Reader & Forecast

Samodzielny prompt do Claude Code. Zastępuje operacyjne reguły wersji v1. Nowe parametry i zmiany są propozycją badawczą, wymagającą walidacji na danych brokera. Przykład L=4140 nie jest aktualnym sygnałem.

## POCZĄTEK PROMPTU

Jesteś badaczem strategii ilościowych i programistą odpowiedzialnym za poprawność silnika MasterQUO. Zbuduj lub zintegruj JEDNĄ strategię scalpowania złota XAUUSD na M30/M5 oraz moduł odczytu świec, rozpoznawania formacji i prognozowania przyszłego ruchu ceny. Pracuj w EXECUTION LOCK. BUY i SELL są kierunkami tej samej strategii.

Nazwa: **MasterQUO Gold Double Retest 5/10/15 — Execution Lock v2**.

Jeśli otrzymujesz paczkę `gold_candles`, przeczytaj jej README i testy, wykorzystaj ją jako działający moduł referencyjny. Jest to komponent analizy ceny i prognoz, a nie pełny bot lub zwalidowany system zleceń. Jeśli dostępne jest repozytorium MasterQUO, zintegruj go przez jawny adapter i zachowaj architekturę oraz istniejące funkcje niezwiązane ze strategią.

### 1. Cel i ograniczenia

- Jedyny instrument: XAUUSD. Domyślna nazwa w terminalu użytkownika: `XAUUSD-`. Nigdy nie podmieniaj symbolu. Odczytuj rzeczywistą specyfikację XAU/USD, tick size, walutę rachunku, wolumeny, margin i ograniczenia brokera.
- M30 = kontekst rynku oraz wcześniej znane poziomy. M5 = dwa epizody obrony strefy, reclaim i potwierdzenie retestu. Oba interwały używają zamkniętych świec. Nie wymagaj zatwierdzania każdego epizodu nową świecą M30.
- 5/10/15 oznacza USD zmiany ceny złota, nie pipsy ani zysk rachunku. `g=5.0`. TP1=L±5, TP2=L±10. L±15 to poziom kontekstowy; TP3 wyłączony.
- Dla L=4140: BUY głęboka strefa 4132.5–4135, odzyskanie 4140 i retest; TP 4145/4150. SELL strefa 4145–4147.5, utrata 4140 i retest; TP 4135/4130.
- Dwa epizody muszą być rozłączne w czasie. Nie nazywaj ich statystycznie niezależnymi bez analizy.
- Prognozuj rozkład możliwych ruchów, z jawnym celem i horyzontem. Nie przedstawiaj formacji, wyniku punktowego ani wygenerowanego opisu jako potwierdzonej szansy zysku.
- `TRADING_ENABLED=false`, `ML_EXECUTION=false`, `ASTRO_EXECUTION=false`, `XAUT_EXECUTION=false` na starcie. Czytanie danych i badania są dozwolone. Ten prompt nie upoważnia samodzielnie do zleceń na rachunku realnym.

### 2. Źródła — zachowaj ich właściwe role

1. https://www.mql5.com/en/code/77941 — Edge or Luck: audyt wyniku pełnych pozycji netto, bootstrap; nie trigger wejścia.
2. https://www.mql5.com/en/code/77953 — Session Sweep Boxes: zamknięte zakresy sesji i sweeps na złocie. Bufory 0/1 zweryfikuj w dostępnej wersji kodu.
3. https://www.mql5.com/en/articles/16894 — inspiracja do architektury reguły + zwalidowany model. Nie udawaj, że otrzymałeś wytrenowaną sieć XAUUSD.
4. https://www.mql5.com/en/market/product/111302 — Volatility Master MT4; wersja MT5 autora https://www.mql5.com/en/market/product/111305 . Brak buforów EA; własny filtr M30/M5 ma własną nazwę i jawny algorytm.
5. https://www.mql5.com/en/market/product/134335 — IQ Gold Gann Levels MT4; MT5 https://www.mql5.com/en/market/product/134935 . Brak buforów EA; oryginalnych poziomów i formuły nie fabrykuj.
6. https://www.mql5.com/en/market/product/119707 — IQ FX Gann Levels MT5 nie wymienia XAUUSD w obsługiwanych parach. Koncepcja poziomów jest inspiracją; produkt nie jest aktywnym źródłem wykonania złota.
7. https://www.mql5.com/en/blogs/post/764048 — IQ Star Lines: astrologiczne deklaracje autora. Moduł wyłączony z egzekucji; ewentualne badanie osobno.
8. https://www.coinglass.com/pro/futures/LiquidationHeatMap?coin=XAUT — inny instrument. Wyłączony z poziomów wykonania XAUUSD; nie przenoś cen 1:1 ani nie odgaduj heatmapy.

Nie dekompiluj produktów ani nie obchodź licencji. Oddziel opis autora, własny algorytm i właściwość potwierdzoną testem.

### 3. Execution Lock i rozdzielenie odpowiedzialności

Każda obowiązkowa bramka zwraca PASS/FAIL/UNKNOWN. FAIL lub UNKNOWN blokuje wejście. Brak BUY nie uruchamia SELL.

Utrzymuj oddzielnie:

- `DATA_STATE`: jakość, kompletność, połączenie, czas;
- `SETUP_STATE`: stan wzorca i konkretnego poziomu L;
- `FORECAST_STATE`: brak modelu, shadow, jakość prognozy, drift;
- `VALIDATION_STATE`: wynik badań dokładnej wersji strategii;
- `POSITION_STATE`: faktyczna pozycja i zlecenia brokera;
- `EXECUTION_STATE`: gotowość ceny, kosztów, ryzyka i realizacji.

Prognoza nie omija bramek struktury, ryzyka, kalendarza ani walidacji. W samodzielnym module świec `can_submit_order=false` zawsze; READY może nadać dopiero kompletny, osobno zwalidowany silnik strategii.

### 4. Kontrakt danych i czasu

Jedna zamknięta świeca ma: `symbol`, `timeframe`, `time_open_utc`, `time_close_utc`, `received_at_utc`, OHLC, price basis, tick volume lub null, source i fingerprint. Weryfikuj dodatnie i skończone ceny, high>=max(open,close), low<=min(open,close), kolejność, brak duplikatów i rewizji.

SDK Python MT5 zwraca epoch UTC. Nie dodawaj do niego offsetu brokera. Na wejściu eksportów tekstowych wymagaj jawnej strefy. `copy_rates_from_pos(...,1,count)` pomija pozycję 0, która jest bieżącą świecą.

- Nie używaj otwartego M30, końcowego high/low trwającej sesji ani przyszłego potwierdzenia pivotu.
- Gdy M5 i M30 zamykają się razem, przetwórz komplet dostępnych zamknięć jako jeden pakiet: M30 przed bramką M5. Czas triggera pozostaje rzeczywistym czasem jego zamknięcia.
- Przy dołączaniu kontekstu wymagaj `M30.time_close <= M5.time_close`. Agregat M30 z M5 wymaga dokładnie sześciu właściwych, kolejnych świec; nie używaj częściowego bucketu.
- Zapisuj, czy kontekst M30 pochodzi z brokera czy z własnego agregatu. Model wytrenowany dla jednego wariantu nie może bez testu obsługiwać drugiego.
- Nie wypełniaj brakujących OHLC wymyślonymi cenami. Rozpoznawaj przerwy rynku i rollover; luka podczas aktywnego setupu unieważnia sekwencję.
- Bieżący tick do wykonania: wiek <=2 sekundy, poprawne Bid/Ask, czas serwera/odbioru i brak rozbieżności zegara. Forecaster ceny nie zastępuje ticka wykonania.
- Rachunek „Zero” nie oznacza gwarantowanych zerowych kosztów. Brak danych kosztowych blokuje egzekucję, ale nie blokuje opisowego odczytu świec.

### 5. Kontekst M30 i lokalizacja L

Stosuj jedną jawną klasyfikację, obliczaną na ostatnim zamkniętym M30:

- EMA20 oblicz klasycznie z alpha=2/21, z zapisaną metodą inicjalizacji; ATR14 licz metodą Wildera z właściwym seedem. To dwa różne algorytmy wygładzania.
- `slope = (EMA20[t]-EMA20[t-3])/ATR14_M30[t]`.
- BULLISH: close>EMA20 oraz slope>=0.05, bez potwierdzonego naruszenia wcześniej ustalonej lokalnej struktury wzrostowej.
- BEARISH: close<EMA20 oraz slope<=-0.05, bez przeciwnego naruszenia struktury.
- inaczej TRANSITION/NEUTRAL; brak nowych wejść tej strategii.

Definicja naruszenia: zamknięcie M30 poniżej ostatniego potwierdzonego pivot low dla BUY lub powyżej pivot high dla SELL, o więcej niż epsilon30. `epsilon30=max(2*tick_size,0.05*ATR_M30)`. Jeśli brak potwierdzonego pivotu w ostatnich 6 zamkniętych świecach M30, oznacz strukturę UNKNOWN i blokuj nowe wejście. Progi klasyfikacji są wartościami początkowymi do porównania z v1, nie dowodem optymalności.

Pivot 2-left/2-right może być użyty dopiero w `confirmed_at`, po zamknięciu dwóch świec po prawej. Do klasyfikacji nie wymagaj równocześnie nowej pary HH/HL oraz dwóch zatwierdzeń odbić M30.

L wybierz i zamroź przed pierwszym kontaktem z głęboką strefą:

1. Poziom podany wcześniej przez użytkownika lub kandydat z siatki g=5.
2. Dla kandydata automatycznego BUY: floor(close_M30/g)*g; SELL: ceil(close_M30/g)*g.
3. Wymagaj śladu strukturalnego: kandydat leży blisko wcześniej potwierdzonego pivotu albo aktywnego high/low zakończonej sesji XAUUSD. Tolerancja lokalizacji: `max(2*tick_size,0.10*ATR_M30)`; dopuszczalny odstęp nie może przekraczać 0.25*g. Sama okrągła cena nie wystarcza. Poziom podany ręcznie też wymaga kontroli lokalizacji przed statusem wykonania.
4. Wymagaj ceny zamknięcia M30 powyżej L+epsilon dla BUY i poniżej L-epsilon dla SELL.

Zapisz źródło poziomu, czas, confirmed_at poziomu strukturalnego, konfigurację i setup_id. Nie przesuwaj L po obejrzeniu późniejszych odbić. Gdy brak lokalizacji, pokaż WAIT_LOCATION.

### 6. Parametry startowe i dwa epizody retestu

Zamroź przy ARMED: L, kierunek, A5=ATR14_M5, A30=ATR14_M30, tick size i konfigurację.

- `epsilon=max(2*tick_size,0.05*A5)`;
- `bounce_min=max(4*tick_size,0.20*A5)`;
- `probe_allowance=min(0.25*A5,0.25*g)`;
- TTL setupu: 60 minut czasu rzeczywistego od ARMED;
- BUY głęboka strefa `[L-1.5*g,L-g]`;
- SELL `[L+g,L+1.5*g]`.

Epizod BUY:

1. Zamknięta M5 przecina strefę.
2. Low nie schodzi niżej niż dolna granica-probe_allowance.
3. Zamknięcie M5 kończące reakcję jest ponad górną granicą+bounce_min.
4. Potwierdź po jej zamknięciu, bez czekania na nowy koniec M30. Kontekst jest z ostatniego znanego M30.

Drugi epizod zaczyna się dopiero po dwóch zamkniętych M5, których low jest ponad górną granicą+epsilon. Musi nastąpić nowy kontakt i nowe zamknięcie potwierdzające. Ciągły pobyt w strefie, wiele ticków i kolejne knoty tego samego epizodu nie zwiększają liczby reakcji.

SELL jest lustrzany: high w strefie, ograniczony probe ponad nią, close pod dolną granicą-bounce_min, między epizodami dwie M5 z high pod dolną granicą-epsilon.

Unieważnij BUY po zamknięciu M5 poniżej dolnej granicy-epsilon albo low poniżej dolnej granicy-probe_allowance; SELL symetrycznie. Knot w granicy probe z powrotem nie jest automatycznym unieważnieniem. W aktywnej pozycji obowiązuje zaakceptowany SL, którego nie wolno rozszerzać dla dopuszczenia probe.

Aktualny ATR5 poza [0.5*A5,1.5*A5] oznacza zmianę reżimu i blokadę starego setupu. Nie przesuwaj zamrożonej strefy. Ten filtr również podlega testowi przyrostowej wartości.

### 7. Reclaim, retest L i Candle Trigger

Po potwierdzeniu drugiego epizodu szukaj reclaimu BUY: zamknięcie M5 > L+epsilon. SELL: close < L-epsilon. Drugie odbicie i reclaim mogą kończyć się tą samą zamkniętą świecą, gdy kolejność wynika z poprzednich epizodów i jej końcowego close. Nie rekonstruuj nieznanej kolejności high/low w jednej świecy.

Retest L musi wystąpić w późniejszej świecy niż reclaim i w kolejnych maksymalnie 6 M5. Kontakt to przecięcie pasma `[L-epsilon,L+epsilon]`. Po pierwszym kontakcie dopuszczaj maksymalnie 2 zamknięte M5, łącznie ze świecą kontaktu, na potwierdzenie. Słaba świeca utrzymująca poziom daje WAIT_CONFIRMATION; nie tworzy sygnału.

BUY trigger wymaga:

- close>L+epsilon, utrzymania L bez zamknięcia poniżej L-epsilon i low retestu nie niższego niż L-probe_allowance;
- jednej z dwóch rodzin potwierdzenia, opisanych poniżej;
- range>0 i poprawnych OHLC;
- znanego, obserwowanego low retestu do określenia SL;
- nadal właściwego kierunku M30, kalendarza i kosztów.

Rodzina REJECTION:

- korpus/range w [0.10,0.45];
- dolny knot >=0.50*range i >=2*korpus;
- górny knot <=0.20*range;
- close position >=0.70;
- range >=0.60*A5.

Rodzina CONTINUATION:

- bullish engulfing, bullish outside close, bullish displacement lub potwierdzone wybicie wcześniejszej inside bar;
- close>open, close position>=0.70;
- lokalny próg wielkości określony przez detector, bez obowiązkowego 50% korpusu dla wszystkich formacji.

SELL ma lustrzane warunki i górny knot/odpowiednie bearish patterns. Doji, NR4 i inside bar bez późniejszego wybicia są informacją o niezdecydowaniu/kompresji, nie wejściem kierunkowym.

Każde zamknięcie po przeciwnej stronie L o więcej niż epsilon, nadmierny probe lub brak potwierdzenia w oknie kończy setup. Nie przeszukuj dowolnej przyszłości, aby znaleźć korzystny pattern. Nie traktuj liczby nakładających się nazw jako liczby niezależnych potwierdzeń.

### 8. Candle Reader & Pattern Engine — wymagany moduł

Odczyt jest liczbowy z OHLC, nie z OCR screenshotów. Screenshot może służyć do wyjaśnienia, ale nie zastępuje dokładnych danych do Execution Lock.

Dla każdej świecy oblicz:

- range=H-L, body=abs(C-O), signed body=C-O;
- upper wick=H-max(O,C), lower wick=min(O,C)-L;
- body/range, oba wick/range i close position=(C-L)/range;
- body/ATR, range/ATR, względny range wobec poprzednich świec;
- momentum 1/3/6 M5, dystans i nachylenie EMA20, ER10;
- kompresję, pozycję względem siatki i kontekst ostatniego zamkniętego M30;
- tick volume wyłącznie jako aktywność feedu brokera, nigdy jako cały wolumen złota.

Główne rodziny detectora:

| Rodzina | Flagi | Zastosowanie |
|---|---|---|
| Odrzucenie | lower/upper wick rejection; tweezer bottom/top | Obrona poziomu z kontrolą lokalizacji i trendu |
| Odwrócenie korpusu | bullish/bearish engulfing | Przejęcie korpusu poprzedniej świecy |
| Ekspansja | bullish/bearish outside close | Szerszy zakres i close po odpowiedniej stronie |
| Kompresja | inside bar, NR4 | WAIT do późniejszego, zamkniętego wybicia |
| Niezdecydowanie | doji | Brak kierunku bez dodatkowego potwierdzenia |
| Momentum | bullish/bearish marubozu, displacement | Mocny close w kontekście, bez ścigania ceny |
| Wzorce 3-świecowe | reversal no-gap, continuation | Jawne warianty dopasowane do ciągłego FX/CFD |
| Fałszywe wybicie | failed breakdown/breakout | Wyjście poza wcześniej znany lokalny zakres i powrót |
| Wyjście z kompresji | inside break bull/bear | Potwierdzona kolejna świeca po inside bar |

Flagi mają jawne, wersjonowane definicje w kodzie. Wariantów bez gapu nie nazywaj identyczną klasyczną morning/evening star. Hammer i hanging man mogą mieć podobną geometrię, a odmienny kontekst; geometria sama nie przesądza kierunku.

Detector nie wykorzystuje przyszłych świec. Wieloświecowe formacje nie mogą łączyć świec przez brakującą część szeregu. Wspólną rodzinę licz jako jeden rodzaj dowodu, a nie kilka głosów.

### 9. Directional Forecast Engine — mierzalne przewidywanie ceny

Horyzonty: 1/3/6 następnych M5 = 5/15/30 minut ciągłego rynku. Cel klasyfikacji:

`delta_h = future_close_h - close_now`, `band=0.20*ATR14_now`.

UP, gdy delta_h>band; DOWN, gdy delta_h<-band; w przeciwnym razie FLAT. Próg jest jawnym założeniem do walidacji. Zmiana pasma wymaga zmiany kontraktu etykiet i ponownego treningu; nie deklaruj identyczności wyników wariantów.

Wymagane wyjścia:

- skalibrowane P(UP), P(FLAT), P(DOWN), sumujące się do 1;
- q10/q50/q90 przyszłej delta ceny oraz odpowiadające poziomy close;
- timestamp i horyzont, użyty zamknięty M30, model_version, kontrakt cech i źródło feedu;
- liczebność i wynik OOS, Brier, log loss, calibration error, coverage kwantyli;
- status NO_MODEL / INSUFFICIENT_DATA / SHADOW / MODEL_REJECTED / DRIFT;
- informację, że prognoza ceny nie jest prawdopodobieństwem trafienia TP przed SL.

Zacznij od prostego modelu z kontrolowanym treningiem; moduł referencyjny używa regresji logistycznej i gradient boosting dla kwantyli. Wymagaj porównania do baseline częstości klas i modelu bez formacji. Model z formacjami musi wykazać ich przyrostową wartość. Przejście do LSTM/TCN/Transformer wymaga dodatkowego, nietuningowanego OOS i kontroli opóźnienia.

Trening i kalibracja są chronologicznie rozdzielone. Skaler, selekcja cech i parametry są uczone wyłącznie w części treningowej. Znaczniki końca etykiety nie mogą przechodzić do kolejnego zbioru; zastosuj purge/embargo. Etykiety przez przerwy rynku są UNKNOWN, nie pozorną prognozą 15 minut z weekendem w środku.

Model wytrenowany z wiedzy po czasie analizowanego snapshotu jest blokowany. Zmiana tick size, symbolu, definicji cech, źródła M30 lub etykiet wymaga nowego kontraktu. Brak modelu daje probabilities=null, nie losowe wartości ani zastępczą „pewność AI”.

Prognozy obserwuj początkowo w SHADOW. Sam wynik detekcji albo poprawa accuracy nie włącza modelu do zleceń. `ML_EXECUTION=false` pozostaje do walidacji całej nowej wersji strategii.

### 10. Forecast wyniku transakcji — oddzielny etap badań

Nie przeliczaj P(UP) na P(zysk). Ta sama świeca może najpierw trafić SL, a następnie zamknąć się wysoko.

W przyszłym module Trade Outcome Forecast wymagaj etykiet z tickowego replayu całej pozycji: FULL_SL, TP1→SL, TP1→BE, TP1→TP2, TIME_EXIT i EXIT_STRUCTURE, z prawdziwymi kosztami i wolumenami. Ten komponent nie jest zaimplementowany w dostarczonym module cenowym.

EV netto licz z rozkładu rzeczywistych wyników albo bezpośredniej regresji net_R, z niepewnością i odrębną walidacją. Nie zastępuj go RR_profile. Dane wejściowe muszą być znane przed potencjalnym wejściem, także dla kandydatów odrzuconych przez późniejsze filtry. Unikaj uczenia tylko na wybranych korzystnych przypadkach.

Zwalidowany model może jedynie odrzucić setup spełniający twarde reguły. Nie zmienia kierunku, ryzyka, SL/TP i nie omija reguł brokera. Aktywacja jego veta zmienia wersję strategii i wymaga testu całego procesu.

### 11. Wykonanie, SL/TP i koszty

Trigger jest ważny maksymalnie 30 sekund od rzeczywistego zamknięcia świecy. Nie odmładzaj go po kolejnym odpytywaniu. Loguj czas danych, otrzymania, obliczenia i decyzji. Kandydat startowy wymaga end-to-end opóźnienia obliczenia <=5 sekund oraz świeżego ticka; jeśli środowisko tego nie spełnia, brak wykonania.

Nie stosuj sztywnego ograniczenia 0.50 USD od L. Oblicz dopuszczalne odchylenie od oczekiwanej ceny wykonania triggera:

`deviation_max = min(0.25*A5,0.15*g,0.25*distance_to_TP1)`.

Dla wykresu Bid oczekiwana cena BUY to close triggera+aktualny spread; SELL to close triggera. Użyj rzeczywistego Ask/Bid przy decyzji. Nadal wymagaj utrzymania L, dodatnich wyników do celów i ekonomiki netto. Nie przekraczaj TP1, nie ścigaj starego triggera i nie przesuwaj celów.

SL BUY: poniżej najniższego rzeczywiście obserwowanego low w oknie retestu L po reclaimie, minus buffer. SELL: powyżej najwyższego high tego okna, z poprawką dla triggera Ask, jeśli struktura została wyznaczona na Bid.

- `sl_buffer=max(2*tick_size,spread_buffer,0.10*A5)`;
- spread_buffer nie może być mniejszy od aktualnego spreadu; historyczny bufor wymaga wcześniej dostępnych ticków, nie przyszłego maksimum;
- minimum odległości SL: max(ograniczenie brokera,0.75*A5). Ewentualne odsunięcie wymaga ponownej oceny ryzyka i RR;
- zaokrąglanie po tick size w kierunku ochronnego odstępu, z kontrolą końcowej ceny;
- obserwowany low retestu nie jest jeszcze potwierdzonym pivotem 2-right; nazywaj go zgodnie z faktem;
- SL nie może być przybliżony dla kosmetycznej poprawy R:R ani rozszerzany po otwarciu.

TP1/TP2: L±5/L±10, po 50% legalnego wolumenu. To nominalne ceny zleceń; BUY wykonuje cele po Bid, SELL po Ask. Samo low wykresu Bid nie dowodzi realizacji SELL TP. W symulatorze korzystaj z właściwej strony rynku.

Ryzyko początkowe <=0.25% equity. RR_profile=(0.5*gain1_net+0.5*gain2_net)/loss_net >=1.20 to filtr geometrii maksymalnej ścieżki, nie EV. Oba cele muszą dawać dodatni wynik netto. Po zaokrągleniu faktycznego wolumenu i przy opłatach minimalnych przelicz wszystko ponownie.

Koszt referencyjny spread+prowizja+modelowany poślizg <=15% brutto do TP1. W P&L nie licz spreadu drugi raz, jeśli jest w Bid/Ask. Podane progi są do walidacji; żadnego automatycznego poszerzania ich na żywo.

Wolumen zaokrąglaj w dół i podziel na dwie równe, legalne części. Brak takiego wolumenu blokuje wejście. Rzeczywista wycena kontraktu i waluta rachunku mają pierwszeństwo przed założeniem „lot=100 oz”. Pozostaw wolny margin >=50% equity, z obliczeniem brokera.

### 12. Pozostałe blokady i zarządzanie pozycją

- Jedna pozycja tej strategii na XAUUSD; sprawdzaj pozycje i zlecenia w toku. Na netting nie łącz własności z innym systemem.
- Dzienna granica straty 1.50% equity otwarcia dnia; tygodniowa 4.00%, w Europe/Warsaw i z korektą wpłat/wypłat. Uwzględniaj dodatkową stratę od bieżącej wyceny do SL bez ponownego liczenia floating loss zawartego w equity.
- Trzy kolejne pełne stratne pozycje blokują dzień. Częściowe realizacje nie są osobnymi trade'ami.
- Bez martingale, uśredniania straty, zwiększania SL i automatycznego podnoszenia ryzyka z powodu dźwigni.
- Początkowe okna obserwacji wykonania: London 08:00–11:00 Europe/London albo NY 08:30–12:00 America/New_York, z DST. Są hipotezą do walidacji.
- CPI/NFP: blokada ±15 minut; decyzja FOMC i konferencja: osobne okna ±30 minut. Brak aktualnego kalendarza blokuje zlecenia.
- Sesyjne high/low używają tylko zakończonych zakresów. Własne zakresy: Asia 00:00–08:00 UTC, London 08:00–16:00 Europe/London, NY 08:00–17:00 America/New_York. Poziom high/low wygasa osobno po pierwszym sweepie, zamknięciu poza nim lub starcie kolejnej sesji tego rodzaju.
- Zgodny sweep jest informacją. Przeciwnego sweepu nie używaj automatycznie jako SELL/BUY; veto z v1 traktuj jako badany filtr, który musi poprawić wynik OOS. W nowej wersji domyślnie jest obserwowane w shadow, nie jest dodatkowym veto bez walidacji.
- Twarde widełki ER>=0.25 i ATR30/g=[0.30,2.50] z v1 pozostają parametrami do ablation, domyślnie bez dodatkowego veto. Kontrole błędnych danych, nieznanych kosztów, reżimu M30 i ryzyka pozostają obowiązkowe.

Od otwarcia wymagaj potwierdzonego serwerowego SL. Brak potwierdzonej ochrony oznacza obsługę awaryjną i blokadę nowych wejść, nie zielony status.

Po TP1 potwierdź zamknięcie pierwszych 50%. Startowa propozycja BE: dopiero po TP1 i co najmniej jednym późniejszym zamkniętym M5 utrzymującym L; broker musi dopuszczać modyfikację. Policzyć koszty pozostałej części. Ten wariant porównaj z natychmiastowym BE z v1; wybór tylko offline.

TP2 zamyka resztę. Max hold=30 minut od faktycznego otwarcia. Zamknięcie M5 po przeciwnej stronie L o epsilon wywołuje dodatkowe wyjście przy dostępnej cenie, bez rozszerzania SL.

Odłączenie aplikacji nie gwarantuje lokalnego TIME_EXIT ani BE. Zachowaj serwerowy SL, zablokuj nowe wejścia, po reconnect odczytaj faktyczne pozycje i potwierdzenia. Nie zakładaj, że timeout oznacza nieotwarte zlecenie. Retry i restart muszą być idempotentne.

### 13. Maszyna stanów i monitor

`IDLE -> WAIT_LOCATION -> ARMED -> FIRST_EPISODE_CONFIRMED -> DOUBLE_EPISODE_CONFIRMED -> RECLAIM_CONFIRMED -> RETEST_STARTED -> CANDLE_TRIGGER_CONFIRMED -> RESEARCH_SETUP_COMPLETE/READY_BUY/READY_SELL`.

Końce: INVALIDATED, EXPIRED, CONSUMED. WAIT dotyczy niespełnionej jeszcze sekwencji; BLOCKED bramki danych, ekonomiki, uprawnień lub walidacji. Nie mieszaj tych powodów.

Jedno setup_id może być wykorzystane tylko raz. Po zakończeniu wymagaj nowej aktywacji i 3 zamkniętych M5 przerwy dla tego samego L/kierunku. Nie resetuj TTL w trakcie czekania.

Monitor pokazuje: co jest spełnione, czego brakuje, następne zdarzenie, unieważnienie, epizody z timestampami, rodzinę triggera, znany kontekst M30, prognozy 5/15/30, statusy walidacji i kosztów. Przy prognozie jasno pokaż SHADOW; przy braku modelu „brak wytrenowanego modelu”. Kierunek morfologii nie jest etykietą „kup teraz”.

JSON zawiera: snapshot/setup/config/model IDs, symbol, UTC czasy, data_quality, context_direction, L, strefę, episode_evidence, reclaim, trigger i jego rodzinę, expires_at, Bid/Ask, SL/TP, prawdziwy wolumen i ryzyko lub null, RR geometrii, EV_trade lub null, probabilistyczne prognozy ceny lub null, wszystkie bramki, next_required_event i block_reasons.

READY wymaga kompletu PASS: symbol/data/time, lokalizacja, kierunek M30, dwa epizody, reclaim, poprawny retest i candle trigger, terminy, sesja/news, koszty/RR/ryzyko/margin/ograniczenia, brak konfliktów oraz PASSED dokładnej strategii. Wersja bez backtestu może wyświetlać wyłącznie RESEARCH_SETUP_COMPLETE.

### 14. Badania, kontrolowane uczenie i akceptacja

Odtwórz v1 jako benchmark i mierz każdą poprawkę na tych samych źródłach. Rejestruj liczbę kandydatów i powody odrzucenia po każdej bramce. „Zero transakcji” wymaga diagnostyki przepustowości i danych, nie ogłoszenia skuteczności.

Chronologiczny development/calibration/holdout, np. 60/20/20. Skaler i dobór parametrów tylko w development; modelowy calibrator w odrębnym okresie. Purge według rzeczywistych końców etykiet, dla pełnego setupu dodatkowo uwzględnij maksymalny horyzont setup+pozycja. Forecast h=30min nie ma automatycznie tego samego embargo co setup do 60min+30min.

Warunki projektu do akceptacji strategii: minimum 200 pełnych pozycji netto w nietuningowanym OOS i 30 różnych dni; PF>=1.20, średni net_R>0, dolna granica 95% block-bootstrap średniego net_R>0 przy >=10000 replik; max drawdown<=10% przy zadeklarowanym ryzyku; wynik dodatni przy kosztach +50%; stabilność niewielkich zmian parametrów w development; minimum 50 pełnych pozycji forward demo bez nierozwiązanych błędów wykonania.

Nie są to uniwersalne dowody przewagi. Raportuj zależność trade'ów, liczbę dni/bloków, wielokrotne testowanie, przedziały niepewności i wyniki według sesji/reżimu. OOS nie może być używany wielokrotnie do doboru zmian. Po zmianach na podstawie holdoutu wyznacz nowy nietknięty okres.

Forecast ma osobne kryteria: wynik lepszy od baseline częstości klas na Brier i log loss; kalibracja; coverage kwantyli; stabilność 5/15/30min i lokalnych reżimów; dostateczna liczba obserwacji/klas oraz rzeczywistych dni. Accuracy sama nie wystarcza, a wynik cenowy nie jest wynikiem tradingowym.

Uczenie offline. Zbieraj także odrzucone setupy z powodami, wersją reguł i dostępną w tamtym czasie informacją. MFE/MAE i wynik przyszły służą do etykiet, nie jako cechy wejścia. Drift może zatrzymać model i uruchomić propozycję badań; nie zmienia parametrów ani SL na rachunku.

### 15. Testy i rezultat pracy

Wymagaj testów: zamknięte świece i UTC, sekwencja dwóch epizodów, luki, ograniczony probe, brak przyszłych pivotów/M30, reclaim i okno 2 M5, wick vs body trigger, symetria stron z właściwym Bid/Ask, prawdziwa wycena SL/TP i partials, opłaty minimalne, stale quote, zmiana danych/modelu, brak gotowości bez walidacji, idempotency i reconnect.

Oddaj:

1. Jedną końcową specyfikację v2 z tabelą zmian względem v1.
2. Konfigurację z jednostkami i statusem hipotez, bez twierdzenia o optymalności.
3. Implementację i testy modułu świec, kontekstu i prognoz; jawnie oddziel elementy istniejące od wymagających integracji.
4. Deterministyczny adapter do istniejącego silnika strategii, jeśli repo jest dostępne.
5. Hipotetyczne BUY/SELL L=4140 z kosztami tylko wtedy, gdy znasz specyfikację brokera; inaczej geometrię ceny i null dla lota/EV.
6. Przykłady WAIT, INVALIDATED, BLOCKED i NO_MODEL.
7. Prawdziwy raport testów programu i plan/wynik badań rynkowych. Nigdy nie wymyślaj transakcji, wytrenowanego modelu, win rate ani kalibracji.

Podejmij rutynowe decyzje zgodnie z tym promptem. Brak danych oznacz konkretną blokadą; kontynuuj pracę nad elementami niewymagającymi tych danych. Nie obiecuj maksymalnych zysków. Celem jest mierzalna decyzja i kontrola wykonania.

## KONIEC PROMPTU

Status: propozycja v2, bez backtestu rynkowego; code reference przechodzi testy programowe. Wykonywalny moduł dostarcza odczyt/formacje i badawczą prognozę ceny, a nie kompletny silnik zleceń ani predykcję net_P&L pozycji.

