# MasterQUO M04N — rejestr źródeł i pokrycia

| Źródło | Endpoint / dokumentacja | Implementacja | Ograniczenia |
|---|---|---|---|
| Fed monetary RSS | https://www.federalreserve.gov/feeds/press_monetary.xml | TAK | Komunikaty z opóźnieniem, brak pełnego kalendarza |
| Fed speeches RSS | https://www.federalreserve.gov/feeds/speeches.xml | TAK | Więcej szumu, nie każda wypowiedź wpływa na XAUUSD |
| BLS CPI RSS | https://www.bls.gov/feed/cpi.rss | TAK | Nagłówek/release, nie jednolite actual/forecast |
| BLS NFP RSS | https://www.bls.gov/feed/empsit.rss | TAK | Ochrona przed opóźnieniem feedu |
| BLS PPI RSS | https://www.bls.gov/feed/ppi.rss | TAK | Mniejsza częstotliwość danych |
| BLS Calendar | https://www.bls.gov/schedule/news_release/bls.ics | TAK | Wyłącznie zdarzenia BLS; `PARTIAL` w M04 |
| GDELT DOC 2.0 | https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/ | TAK (opcjonalne wyłączenie) | Agregator publicznych artykułów, wyniki i opóźnienia zmienne |
| FRED series API | https://fred.stlouisfed.org/docs/api/fred/series_observations.html | TAK, po kluczu | Niefinansowy feed tickowy; wartości dzienne/miesięczne, historyczne |
| FOMC calendar i live press conference | https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm | NIE | Osobny importer kalendarza i konferencji do opracowania |
| BEA / PCE / GDP releases | https://www.bea.gov/news/schedule | NIE | Potrzebny importer harmonogramu, czas publikacji i revisions |
| COMEX futures / open interest | źródła licencjonowane / giełda | NIE | Dostęp i warunki licencyjne |
| CFTC Commitments of Traders | https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm | NIE | Dane tygodniowe, nie intraday |
| Gold ETF flows / central-bank buying | wydawcy ETF / World Gold Council | TYLKO NEWS | Brak jednolitego darmowego API i publikacji intraday |
| DXY, XAUUSD Bid/Ask | MetaTrader 5, M01 | **W ISTNIEJĄCYM M01**, NIE W M04N | Kontynuacja zasady MT5 PRIMARY; nie zastępować cen newsowymi |

**Wniosek:** osiągalny jest szeroki monitoring, a nie „wszystkie informacje” w sensie literalnym. Wiarygodność i licencja źródeł ważniejsze niż sama liczba nagłówków. Na poziomie macro news interpretacja kierunku pozostaje `UNKNOWN`.

## Dodatkowe źródła od v1.1.0

| Id | Portal | URL exportu JSON | Strona kalendarza | Zakres | Częstość |
|---|---|---|---|---|---|
| `FF_CALENDAR` | Forex Factory | https://nfs.faireconomy.media/ff_calendar_thisweek.json | https://www.forexfactory.com/calendar | USD, CNY; oznaczenia kraju i impact | 1800 s |
| `MM_CALENDAR` | Metals Mine | https://nfs.faireconomy.media/mm_calendar_thisweek.json | https://www.metalsmine.com/calendar | USD, CNY oraz wybrane wydarzenia metali | 1800 s |

**Potwierdzenie typu eksportu:** obie oficjalne strony `/calendar` oferują pozycję „Weekly Export → JSON”; adres `nfs.faireconomy.media` jest domeną z docelowego odnośnika JSON. Kalendarze mogą odmówić pobrania przez klienta HTTP; źródło otrzyma wtedy `UNAVAILABLE_OR_STALE`. Nie podejmujemy prób obchodzenia limitów dostępu.

**Metadane jakości:** `event_time_quality=THIRD_PARTY_WEEKLY_EXPORT`; `not_official_release=true`; `no_release_surprise_inferred=true`. `event_id` pozostaje stabilne przy zmianie prognozy, a `available_at` oznacza pierwszy odczyt przez M04N, nie oryginalny czas publikacji.

**Wspólna organizacja:** Forex Factory i Metals Mine korzystają z ekosystemu Fair Economy, więc nie są traktowane jako dwa niezależne potwierdzenia wydarzenia. Grupowanie jest zachowawcze — nie scala różnych miar CPI, jeśli nazwy się różnią.

**Newsy:** strony https://www.forexfactory.com/news i https://www.metalsmine.com/news zostały dodane jako *odnośniki referencyjne*. Nie są automatycznie pobierane: nie zweryfikowano stabilnego, publicznie dostępnego RSS/API bieżących artykułów. Zamiast wyświetlać fikcyjny status podłączenia, pola `news_page_auto_import=false` mówią o ograniczeniu wprost.
