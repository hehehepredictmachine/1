# Źródła i adaptacje – 10 strategii ACTIVE

## Weryfikacja dostępu (stan na 2026-10-09)
Próba otwarcia stron wskazanych w zleceniu z mojego środowiska budowy zakończyła się błędem DNS (`ENOTFOUND`) – środowisko nie ma
dostępu do tych serwisów. **Nie przeczytałem żadnej z książek ani ich fragmentów w tej pracy.** Nie podaję numerów stron ani cytatów.

| # | Pozycja (wg zlecenia) | Wydanie | Dostęp w tej pracy | Co faktycznie wykorzystano | Lokalizacja |
|---|---|---|---|---|---|
| 1 | Perry J. Kaufman – *Trading Systems and Methods* | 6. wyd. (ISBN 9781119605355 wg URL ze zlecenia) – nieweryfikowane | **METADATA_ONLY** (strona wydawcy niedostępna: ENOTFOUND) | ogólnie znane koncepcje kojarzone z autorem: adaptacyjna średnia KAMA i efficiency ratio, systemy trendowe i breakout kanału | https://books.wiley.com/titles/9781119605355/ |
| 2 | David R. Aronson – *Evidence-Based Technical Analysis* | DOI 10.1002/9781118268315 – nieweryfikowane | **METADATA_ONLY** (ENOTFOUND) | zasady metodyczne: obiektywne, testowalne reguły; problem wielokrotnego testowania; rozdział DEV/VAL/OOS | https://onlinelibrary.wiley.com/doi/book/10.1002/9781118268315 |
| 3 | Adam Grimes – *The Art and Science of Technical Analysis* | DOI 10.1002/9781119202837 – nieweryfikowane | **METADATA_ONLY** (ENOTFOUND) | ogólne idee: pullback w trendzie, test/nieudane wybicie, zakresy, zmiana struktury | https://onlinelibrary.wiley.com/doi/book/10.1002/9781119202837 |
| 4 | Mike Bellafiore – *The PlayBook* | – | **METADATA_ONLY** (strona SMB niedostępna: ENOTFOUND) | idea kart setupów i przeglądu transakcji → karty playbooka (`/api/v1/playbook`) | https://www.smbtraining.com/blog/the-playbook-by-mike-bellafiore |
| 5 | Ernest P. Chan – *Algorithmic Trading* | DOI 10.1002/9781118676998 – nieweryfikowane | **METADATA_ONLY** (ENOTFOUND) | ogólne idee: mean reversion na z-score, momentum, ostrożność wobec backtestu | https://onlinelibrary.wiley.com/doi/book/10.1002/9781118676998 |

Wniosek: **żadna konkretna reguła wejścia nie jest przypisana autorowi jako cytat.** Każda strategia ma status źródła
`SOURCE_UNVERIFIED` dla szczegółowych parametrów. Do dokładnego odwzorowania potrzebne byłyby: rozdział Kaufmana o KAMA/efficiency
ratio (formuła i filtr), rozdziały Grimesa o pullbackach i „failure test”, rozdział Chana o mean reversion (z-score/Bollinger) –
dołącz legalne fragmenty, a karty zostaną zaktualizowane.

## Podział: idea → formalizacja → adaptacja → parametry robocze
| Strategia | Idea (źródło, status) | Własna formalizacja programistyczna | Adaptacja do złota CFD / feedu brokera | Parametry robocze |
|---|---|---|---|---|
| S01 TREND_PULLBACK | pullback w trendzie (Grimes, Kaufman – METADATA_ONLY) | EMA20/EMA50, ER(20), głębokość korekty w ATR, strefa EMA20–EMA50, świeca reakcji | odległości w ATR (nie w $), SL SHORT + spread | min_depth 1 ATR, max 3,5 ATR, zone ±0,25 ATR |
| S02 ADAPTIVE_TREND | KAMA + efficiency ratio (Kaufman – METADATA_ONLY; formuła KAMA szeroko publikowana) | wejście na zmianie stanu, pasmo histerezy | pasmo 0,3 ATR zamiast filtra z odchylenia KAMA | KAMA(10,2,30), ER ≥ 0,3 |
| S03 CHANNEL_BREAKOUT | breakout kanału Donchiana (Kaufman – METADATA_ONLY) | kanał z barów poprzedzających, bufor, limit świecy | bufor/limit w ATR | N=20, bufor 0,1 ATR, max świeca 2,5 ATR |
| S04 VOLATILITY_COMPRESSION_BREAKOUT | zmienność i reżimy (SOURCE_UNVERIFIED) | percentyl szerokości BB, pudełko kompresji znane przed sygnałem | percentyl liczony na historii brokera | ≤ 15. percentyl z 120, ≥ 5 świec |
| S05 SESSION_RANGE_BREAKOUT | opening range breakout (literatura ogólna – SOURCE_UNVERIFIED) | okno sesji w strefie IANA, zamrożenie zakresu | godziny = konfiguracja do zbadania (CFD nie ma jednego otwarcia) | Londyn 08:00/60 min, NY 08:30/30 min |
| S06 BREAKOUT_RETEST | wybicie i test poziomu (Grimes – METADATA_ONLY) | pivot 3/3, sekwencja wybicie→retest→reakcja | tolerancja retestu w ATR | retest ≤ 0,3 ATR, fail 0,5 ATR |
| S07 FAILED_BREAKOUT_RECLAIM | failure test (Grimes – METADATA_ONLY) | wyjście poza krawędź, powrót ≤ 3 świece | opis ruchu ceny – bez interpretacji „płynności” | out 0,1 ATR, bufor 0,1 ATR |
| S08 RANGE_EDGE_REVERSION | handel w zakresie (Grimes/Kaufman – METADATA_ONLY) | zakres znany przed sygnałem (ER, dotknięcia) | wysokość zakresu w ATR | 40 świec, ER ≤ 0,25, 2–8 ATR |
| S09 STATISTICAL_MEAN_REVERSION | mean reversion z-score (Chan – METADATA_ONLY) | z = (C−SMA40)/σ40, filtr ER | stacjonarność ceny złota NIE jest zakładana – hipoteza do testu | WATCH −1,5, EARLY −2, stop −3,5 |
| S10 EXHAUSTION_STRUCTURE_REVERSAL | zmiana struktury, słabnący impuls (Grimes – METADATA_ONLY) | dywergencja RSI lub rozciągnięcie + CHoCH | RSI nigdy samodzielnym triggerem | impuls ≥ 3 ATR, stretch 2,5 ATR |

Dane: wyłącznie świece Bid z MT5 i Bid/Ask. **Tick volume nie jest używany** w żadnej strategii (brak udawania wolumenu giełdowego,
order flow czy footprintu). VWAP nie został dodany.

## Macierz różnic i nakładania
| | Mechanizm | Konieczny warunek wyróżniający | Reżim | Trigger | Wyjście |
|---|---|---|---|---|---|
| S01 | kontynuacja | korekta do strefy wartości | trend | zamknięcie nad high poprzedniej świecy | ekstremum impulsu / zasięg |
| S02 | kontynuacja | ZMIANA stanu KAMA | trend/przejście | zamknięcie nad KAMA+pasmo | trailing KAMA |
| S03 | wybicie | kanał N świec | ekspansja | zamknięcie nad kanałem | szerokość kanału |
| S04 | wybicie | wcześniejsza kompresja | kompresja→ekspansja | zamknięcie nad pudełkiem | wysokość pudełka |
| S05 | wybicie | zakres okna sesji | sesyjny | zamknięcie nad zakresem | wielokrotność zakresu, koniec okna |
| S06 | wybicie | wybicie→retest→reakcja | trend/ekspansja | reakcja po reteście | maks. po wybiciu, 2R |
| S07 | powrót | wyjście poza i powrót | range/wyczerpanie | zamknięcie z powrotem | środek / druga krawędź |
| S08 | powrót | zakres znany wcześniej, bez wyjścia | range | świeca odrzucenia | środek / druga krawędź |
| S09 | powrót | odchylenie statystyczne | range/przejście | zawrócenie z-score | SMA−1σ / SMA, czas |
| S10 | odwrócenie | wyczerpanie + zmiana struktury | wyczerpanie | zamknięcie nad niższym szczytem | 50% / 78,6% impulsu |

Nakładanie: S03/S04/S05/S06 przy tym samym poziomie dzielą `event_id` (`BREAKOUT:kierunek:koszyk poziomu`), S07/S08 – `RANGE_EDGE`,
S01/S02 – `TREND_CONT`. Selektor rankuje jedną reprezentację zdarzenia, pozostałe pokazuje jako „ten sam ruch”; pomiar w replay:
`events_shared_by_several_strategies` (docs/POROWNANIE_ORIGINAL_ACTIVE.md). Dziesięć strategii na jednym instrumencie **nie** jest
dziesięcioma niezależnymi źródłami ryzyka – limit ryzyka i pozycji jest wspólny dla całego XAUUSD-.
