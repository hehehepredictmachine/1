# MasterQUO M04N v1.1.0 — Gold & USD Intelligence Feed + Forex Factory / Metals Mine

**Status: CANDIDATE / RESEARCH / READ-ONLY.** Nowy, samodzielny moduł dodatkowy do M04, nie zastępuje M04 ani nie modyfikuje M01–M16, M02I i dotychczasowego monitora. Nie wymaga OpenAI API. Działa na Windows 10/11 z Pythonem 3.10+ oraz Internetem. **Nie wysyła zleceń i nie przewiduje kierunku ceny.**

## Co pobiera automatycznie

| Grupa | Źródło | Uwierzytelnienie | Co oznaczają dane |
|---|---|---|---|
| Polityka Fed i przemówienia | oficjalne RSS Federal Reserve | Bez klucza | Wiadomości i komunikaty, możliwe opóźnienia |
| CPI, PPI, zatrudnienie NFP | oficjalne RSS BLS | Bez klucza | Najnowsze komunikaty/statystyki w formie nagłówków |
| Harmonogram publikacji BLS | oficjalny `bls.ics` | Bez klucza | Zaplanowane wydarzenia (nie prognoza i nie wynik odczytu) |
| Złoto, USD, obligacje, geopolityka, zakupy złota przez banki, ETF | GDELT DOC 2.0 | Bez klucza | Agregator tytułów i URL; źródła wymagają weryfikacji |
| **Forex Factory** — tygodniowy kalendarz USA/USD i Chin/CNY | publiczny tygodniowy JSON Fair Economy | Bez klucza | Godzina, priorytet, forecast/actual/previous; dane agregatora, nie komunikat urzędowy |
| **Metals Mine** — tygodniowy kalendarz metali i makro | publiczny tygodniowy JSON Fair Economy | Bez klucza | Wydarzenia USD/CNY i wybrane dotyczące metali, np. LME; przybliżony wpływ na złoto |
| Rentowność USA 10Y, realna 10Y, oczekiwania inflacyjne, Fed funds, inflacja, zatrudnienie, szeroki USD | FRED API v1 | **Opcjonalny klucz FRED** | Szeregi publikowane z opóźnieniem, nie ticki, nie DXY, nie surprise |

Moduł nie pobiera kompletu wiadomości z całego świata; *żadne* z tych źródeł nie gwarantuje całkowitego i natychmiastowego pokrycia. Nie implementuje w tej wersji pełnego kalendarza FOMC, BEA/PCE, wszystkich przemówień, płatnych serwisów, przepływów COMEX/CFTC/ETF ani treści pełnych płatnych artykułów. Użytkownik może dodać legalne źródła RSS do konfiguracji wraz z jawną allowlistą domen.

## Nowe źródła: Forex Factory i Metals Mine (v1.1.0)

**Automatycznie pobierane są kalendarze ekonomiczne (JSON), nie newsy HTML.** Oficjalne strony udostępniają przyciski „Weekly Export: JSON”; adresy odczytu to `https://nfs.faireconomy.media/ff_calendar_thisweek.json` i `https://nfs.faireconomy.media/mm_calendar_thisweek.json`. Strony informacyjne serwisów znajdują się pod `https://www.forexfactory.com/news` oraz `https://www.metalsmine.com/news`, a w raporcie występują wyłącznie jako **linki do samodzielnego otwarcia**, nie jako automatyczny kanał RSS. Nie znalazłem stabilnego potwierdzonego publicznego kanału automatycznego news RSS dla obu stron, dlatego nie deklaruję automatycznego poboru ich artykułów.

- Domyślny odczyt kalendarzy co 30 minut, minimalnie co 15 minut; odrzucanie 403/429 oraz opóźnienia ponownych prób (bez omijania blokad strony).
- Strefy czasowe z wyraźnym offsetem; braku czasu nie zastępujemy wymyśloną godziną. Wszystkie zapisane terminy są w UTC.
- Priorytety `HIGH/MEDIUM/LOW`, osobne pola `actual`, `forecast`, `previous`. Te wartości to *teksty z witryny*, nie dane zweryfikowane przez BLS lub Fed. Nie obliczamy „surprise” ani prawdopodobieństwa wzrostu ceny.
- Wspólne wydarzenia obu serwisów deduplikowane po godzinie/minucie, walucie i tytule; każda oryginalna obserwacja zachowuje oddzielny `provider_occurrences`. Oba portale są częścią ekosystemu Fair Economy, więc nie traktujemy ich jako niezależnego potwierdzenia.
- Podczas awarii jednego kanału pozostałe działają. Nieaktualny kalendarz nie służy do obliczania bieżącego `macro_risk`. Przed podłączeniem do M04/M11/M14 wymagana jest walidacja ryzyka.
- **Tylko ten tydzień** — to eksport tygodniowy, bez gwarancji pełnego kalendarza FOMC/BEA i przyszłych tygodni; na granicy tygodni należy okresowo ponowić pobieranie.
- W `M04N_CONFIG.json` można wyłączyć oba źródła zmieniając `enabled` na `false` lub ustawić `country_filter`. Metals Mine ma dodatkowo `include_metals_events=true`, więc może uwzględniać np. magazyny LME. Tę zależność od rynku miedzi traktuj jako pomocniczą, nie bezpośredni katalizator XAUUSD.

## Instalacja Windows

1. Rozpakuj ZIP do osobnego folderu, najlepiej `C:\\MasterQUO_M04N`.
2. Włącz połączenie z Internetem. MT5 **nie musi być uruchomiony** — M04N zbiera osobne informacje, a świece i Bid/Ask nadal pochodzą z istniejącego M01/MT5.
3. Zainstaluj Python 3.10 lub nowszy i dla Windows pakiet stref czasowych: `py -3 -m pip install tzdata`.
4. Uruchom dwukrotnie `START_M04N_COLLECTOR.bat`, a później osobno `START_M04N_VIEWER.bat`. Możesz też użyć poniższych poleceń.

```powershell
py -3 -m pip install tzdata
py -3 M04N_ENGINE.py --once
py -3 M04N_ENGINE.py
```

Pierwsze polecenie po instalacji wykonuje jeden cykl, ostatnie **działa stale**, sprawdzając źródła zgodnie z konfiguracją (domyślnie co 5 minut). Aby obejrzeć wiadomości:

```powershell
py -3 M04N_VIEWER.py --watch 10
```

**Opcjonalny FRED**: utwórz osobisty darmowy klucz na stronie FRED i w **tym samym oknie PowerShell** ustaw go w zmiennej środowiskowej:

```powershell
$env:FRED_API_KEY = "TWÓJ_KLUCZ_TUTAJ"
py -3 M04N_ENGINE.py --once --force
```

Nie umieszczaj klucza w ZIP, `M04N_CONFIG.json`, zrzutach ekranu ani rozmowach. FRED API wymaga osobnego klucza dla aplikacji. Bez klucza M04N działa dalej, a FRED jest oznaczony jako opcjonalnie pominięty.

Zmień w `M04N_CONFIG.json` np. odpytywanie poszczególnych kanałów lub wyłącz GDELT (`gdelt_enabled=false`) przy ograniczeniach API. Przy dopisywaniu własnego źródła HTTPS dopisz jego **dokładną** domenę do `allowed_hosts` — nie ma automatycznego zezwalania na przekierowania do innych witryn.

## Wyniki

Program zapisuje w katalogu `runtime/`:

- `M04N_INTELLIGENCE.json` — świeże i historyczne artykuły, tematy GOLD/USD/FED/INFLATION/LABOR/YIELDS/GEOPOLITICS/PHYSICAL/RISK, oznaczona siła wiadomości, terminy wydarzeń oraz źródła i ich zdrowie.
- `M04N_M04_CONTEXT_BRIDGE.json` — warstwa `context_inputs.macro_events`, `calendar_coverage`, `macro_news_context` oraz `fred_observations`. Gotowa do wykorzystania przez integrator M04, **bez autoryzacji sygnału**.
- `M04N_STATE.sqlite` — trwała deduplikacja URL, najwcześniejszy moment odebrania harmonogramu, historii i stanu źródeł. Nie usuwaj jej między restartami, jeśli chcesz uniknąć ponownych nagłówków.

### Informacje krytyczne

- `status=HEALTHY` oznacza wyłącznie działanie **skonfigurowanych** źródeł, nie kompletność globalnej informacji. `PARTIAL` i `UNAVAILABLE` muszą być widoczne w monitorze.
- `calendar_coverage.status` celowo **nie jest `VERIFIED`**, bo oficjalny kalendarze BLS/Forex Factory/Metals Mine nie obejmują wszystkich publikacji Fed/BEA i geopolityki. Jeśli M04 widzi wysokie ryzyko wydarzenia, może je blokować; jeśli nie ma wydarzenia, nie może na tej podstawie ogłaszać niskiego ryzyka.
- Nagłówki mają `potential_gold_direction=UNKNOWN`, `potential_usd_direction=UNKNOWN`. Ocena `impact=HIGH` to jawna **heurystyka priorytetu**, nie liczbowo skalibrowana prognoza kursu.
- Data w GDELT `seendate` to pierwsze zaobserwowanie w agregatorze, **nie czas publikacji źródłowej**. Artykuł bez wiarygodnego `published_at` nie trafia do „potwierdzonych nowych pilnych publikacji”.
- W FRED `observation_date` to data szeregu, **nie czas ogłoszenia wyniku**; wartości nie są łączone z oczekiwaniami/forecast, a średni ważony USD `DTWEXBGS` to nie DXY. Weryfikacja dostępności w czasie `first_available_to_this_collector_at` zapobiega antydatowaniu odczytu we własnym rejestrze.
- Przy pierwszym uruchomieniu wiadomości już dostępne w kanałach są **backfillem**, nie świeżymi alertami. Po przerwie w internecie wiadomość może dotrzeć z opóźnieniem.
- M04N **nie** zastępuje ani nie odblokowuje M01, M06, M08, M09, M10, M11, M14 lub M15 i nie wydaje transakcyjnego `LONG/SHORT`. `execution_permission=BLOCKED` zawsze.
- Częste odpytywanie może wywołać HTTP 403 / 429, niektóre witryny blokują boty. M04N przechodzi wtedy w stan zdegradowany i stopniowo wydłuża przerwę do ponownej próby. Nie obchodzi blokad ani zabezpieczeń serwisów.
- Do testów historycznych pamiętaj, że punkt w czasie (`first_seen_at`, `available_at`) musi pochodzić z momentu rzeczywistego odczytu; nie można później podać bieżącej bazy jako historycznej wiedzy.

## Testy bez Internetu

```powershell
py -3 -m unittest -q M04N_TESTS M04N_M04_CONTRACT_TESTS M04N_FAIR_ECONOMY_TESTS
py -3 M04N_DEMO_OFFLINE.py
py -3 M04N_VIEWER.py --file demo_synthetic_only/M04N_SYNTHETIC.json
```

Pliki `demo_synthetic_only/` są wyraźnie oznaczone `synthetic=true` i `SYNTHETIC_TEST_ONLY`: **nie są rzeczywistymi wiadomościami, cenami ani sygnałami**.

`M04N_OUTPUT_SCHEMA.json` to kontrola kształtu raportu, a `M04N_INTEGRATION_CONTRACT.md` opisuje integrację z M04. Testy offline korzystają z podstawionych odpowiedzi, nie potwierdzają, że zewnętrzne serwisy aktualnie dopuszczają połączenia z Twojego komputera. Niezbędny końcowy etap to **test Windows + uruchomiony MT5 DEMO + audyt kompletności źródeł + backtest w M06**.

### Ograniczenia najnowszego rozszerzenia

Te źródła nie zastępują bezpośrednich komunikatów statystycznych ani cen i spreadów z MT5. Wystąpienie wydarzenia o wysokim priorytecie oznacza tylko potrzebę ostrożności. Należy respektować zasady i limity dostawców. Testy nowych parserów używają syntetycznych odpowiedzi JSON — nie potwierdzają bieżącej dostępności eksportu na komputerze użytkownika. `execution_permission` jest bezwarunkowo `BLOCKED`.
