# CLAUDE CODE — PEPEMARKETWIZARD
## MASTERPROMPT #017 — PEPE$SIGNAL V1.0
### SIGNAL INTELLIGENCE CENTER — 1:1 RECONSTRUCTION + REAL AI / MT5 INTEGRATION

> **Polecenie wykonawcze:** przeanalizuj istniejący projekt PepeMarketWizard i zbuduj produkcyjne wnętrze wieży `PEPE$SIGNAL`, możliwie najwierniej odtwarzające załączoną grafikę (`assets/REFERENCE_APPROVED.png`, 1672×941 px), zachowując rzeczywiste działanie wszystkich kontrolek. Nie ograniczaj pracy do opisów, pustych przycisków ani statycznych makiet. Nie ogłaszaj pełnej zgodności 1:1 bez pomiarów.

## 0. ZAKRES I PRIORYTETY
Jesteś Principal Frontend Engineer, Quant UI Architect, 3D/Creative Technologist, Backend Integration Engineer oraz QA Engineer.

W ramach zadania zmień wyłącznie **wnętrze wieży PEPE$SIGNAL oraz konieczne adaptery interfejsu**. Pozostaw nietknięte podstawowe menu Neural City, wieżę PEPE$WTC, PEPE$BANK, PEPE$ROI, kod trading execution, system licencji, trening modeli, rachunki MT5 i inne niezwiązane usługi. Moduł PEPE$SIGNAL służy analizie, dokumentacji i ocenie sygnałów; samo otwarcie widoku nie ma otwierać transakcji.

**Priorytety:** 1) poprawność danych i integracji; 2) zgodność wizualna ze zdjęciem; 3) interaktywność; 4) responsywność, płynność i dostępność. Uzupełnienie jednego aspektu nie może fałszować pozostałych.

### Materiały w paczce
- `assets/REFERENCE_APPROVED.png` — zatwierdzona grafika (źródło prawdy wizualnej).
- `assets/tower_reference.png` — referencyjny fragment grafiki lewej wieży; do wymiany na komponent 3D tylko jeśli istnieje poprawny asset.
- `PREVIEW_WEB.png` — zrzut działającego, niezależnego prototypu HTML.
- `index.html`, `app.js` — edytowalna implementacja referencyjna interakcji i layoutu.
- `PEPE_SIGNAL_STANDALONE.html` — wersja do otworzenia bez instalacji.
- `QA_VISUAL_FUNCTIONAL.md` — plan testów.

Przed zmianami sporządź krótką mapę istniejących komponentów, API i ograniczeń. Zapoznaj się z najnowszym repozytorium; nie zakładaj, że lokalizacja plików odpowiada starej paczce.

## 1. KOMPOZYCJA I WYGLĄD — REKONSTRUKCJA 1:1
Ustaw obraz referencyjny w przeglądarce w natywnej rozdzielczości **1672×941**, proporcje ok. 16:9, urządzenie DPR=1. Zmierz pozycje i proporcje elementów w pikselach oraz przygotuj mapę układu.

### Przewodnik obszarów (orientacyjny, zweryfikuj względem rzeczywistego obrazu)
| Obszar | Względna pozycja na grafice |
|---|---|
| Górna nawigacja | 0–44 px wysokości |
| Logo PepeMarketWizard | lewy górny róg, kompaktowe |
| PEPE$SIGNAL + podtytuł | 44–110 px |
| Pasek zakładek | ok. 110–151 px |
| Lewa futurystyczna wieża | x≈0–170, od y≈155 w dół |
| Strumień sygnałów | x≈170–445 |
| Centralny obszar analizy | x≈455–1260 |
| Prawa kolumna modeli | x≈1270–1660 |
| Dolna tabela sygnałów | pod analizą i kartami warunków, centralny obszar |

Zachowaj spójny układ: **wąska wieża | lista sygnałów | szeroka analiza | modele/metryki**. Na ekranach węższych używaj responsywnego zwijania paneli, a nie wymuszonej zbyt małej czcionki.

#### Styl wizualny
- Tło: głęboka czerń z ciemną zielenią, dyskretna holograficzna głębia.
- Obramowania: cienkie świetliste linie neonowo-zielone / cyjanowe, małe promienie i delikatne wewnętrzne poświaty.
- Tekst: biały / jasnozielony z wyraźną hierarchią, dane przygaszone w kolorze szarozielonym.
- Status BUY: nasycona zieleń. SELL: koralowa czerwień. WAIT/PENDING: bursztynowy.
- Typografia i etykiety: spójne z referencją, czytelne bez nadmiernego glow. Dla liczb `font-variant-numeric: tabular-nums`.
- Lewe pionowe centrum `PEPE$SIGNAL` zachowuje istniejący ornament budynku.
- Cała aplikacja ma wyglądać jak wysokiej jakości cyberpunkowy panel tradingowy, nie jak zwykły szablon administracyjny.

**Ważne:** grafika może służyć do dopasowania wizualnego i jako asset dekoracyjny, ale nie wolno udawać interaktywnego interfejsu przez pełnoekranowy screenshot z niewidzialnymi prostokątami zamiast prawdziwych komponentów.

## 2. NAWIGACJA I GŁÓWNE ZAKŁADKI
Zachowaj logo i menu na górze; aktywna zakładka to **PEPE$SIGNAL**. Zintegruj routing z faktycznym systemem nawigacyjnym bota, bez nadpisywania pozostałych paneli.

W obrębie PEPE$SIGNAL dodaj zakładki:
- SIGNAL INTELLIGENCE CENTER,
- LIVE SIGNALS,
- ALL STRATEGIES,
- AI EVALUATION,
- SIGNAL HISTORY,
- PERFORMANCE,
- SETUP BUILDER.

Każda zakładka musi wykonywać faktyczną akcję: filtrować, nawigować, otwierać istniejący widok czy prezentować odpowiednie dane. Jeżeli backend nie udostępnia wybranej funkcji, pokaż jawny status `UNAVAILABLE`, bez wymyślania wyników.

## 3. LEWY PANEL — LIVE SIGNAL STREAM
Utwórz rejestrowaną listę wszystkich sygnałów pochodzących z realnie zainstalowanych strategii. Lista nie może opierać się na ręcznie wypisanym, niepełnym katalogu.

Filtry: strategia, symbol, timeframe, kierunek BUY/SELL/WAIT, status, przedział czasowy, jakość/siła jeśli metryka istnieje. Obsłuż wyszukiwanie, sortowanie i wirtualizację długiej listy.

Element sygnału: nazwa strategii, instrument, TF, dokładny czas, kierunek, stan, siła (jeśli wyliczana), wskaźnik aktualizacji i źródło. Wybór sygnału aktualizuje **jednocześnie** cały środkowy i prawy obszar bez powtarzania zapytań.

Stany: NEW / CANDIDATE / CONFIRMED / WAIT / INVALIDATED / EXPIRED / FILLED / CLOSED — mapuj do istniejących nazw z repozytorium. Nie zmieniaj statusu `WAIT` na `BUY` bez rzeczywistego zdarzenia. Debounce i deduplikacja muszą bazować na stabilnym `signal_id`.

## 4. CENTRALNY PANEL WYBRANEGO SYGNAŁU
Góra: nazwa strategii, symbol, TF, timestamp, kierunek BUY/SELL/WAIT, siła sygnału 0–100 (jeśli właściwie zdefiniowana), status aktualności.

### Kontekst świecowy
Duży wykres OHLCV z realnego **MT5 Bridge**, bez screenshotów: crosshair, zoom, pan, wolumen, oznaczenia struktury rynku, Entry/SL/TP, OB, FVG, liquidity, Supply/Demand. Po kliknięciu wybranego sygnału przewiń do czasu utworzenia setupu, a nie do przypadkowego wycinka danych.

### Podsumowanie
Strategia, instrument, TF, kierunek, Entry, SL, TP1–TP3 (jeśli strategia ma te poziomy), R:R z poprawnym mianownikiem, status Execution Lock, ocena jakości i konsensus. Jeżeli wartość nie istnieje, wyświetl N/A.

### Trzy panele warunków
**ENTRY CONDITIONS** — wymagania setupu wzięte z definicji strategii, stan każdej reguły, dowód obliczenia, czas walidacji.
**TRIGGER CONDITIONS** — rzeczywisty wyzwalacz wejścia: close breakout, BOS, momentum, sweep etc., tylko gdy występuje w strategii.
**INVALIDATION** — konkretny poziom lub zasada unieważnienia; alarm po jej naruszeniu i zapis zdarzenia w historii.

Stany pojedynczego warunku: MET / NOT_MET / PENDING / UNKNOWN / INVALIDATED. Wyświetlanie zielonego checkmarka nie może bazować na fikcyjnym boole'u.

### Narracja
Generuj zwarty, objaśnialny opis odwołujący się do faktycznych warunków i wyników modeli. Nie pokazuj rzekomych prywatnych „myśli” modeli AI; prezentuj **telemetrię, dane wejściowe, wyjściowe wyniki, reguły i uzasadnienia dostępne w systemie**.

### Tabela aktywnych setupów
Tabela zbiorcza z funkcjonalnym wyborem rekordu, sortowaniem, paginacją i filtrami. Po kliknięciu wiersza zaznaczenie i pozostałe panele aktualizują się spójnie. Przy historii pokaż event timeline: detected, evaluated, confirmed, invalidated, closed.

## 5. PRAWY PANEL — AI MODEL EVALUATION
Połącz z **faktycznie zarejestrowanymi** modelami; przykładowe nazwy, które trzeba zweryfikować w repo: Kronos, XGBoost, CatBoost, Decision Tree, Neural Networks.

Dla każdego modelu:
- nazwa, model/version/checkpoint,
- instrument i interwał,
- stan READY / INFERENCING / ERROR / OFF / STALE,
- timestamp inferencji,
- direction/bias BUY/SELL/NEUTRAL,
- wynik / score zgodny z prawdziwą semantyką,
- metryka jakości, jeśli dostępna,
- wkład do konsensusu z ustalonym algorytmem wag,
- opis techniczny przyczyny decyzji, gdy taki adapter istnieje.

**Nie zamieniaj arbitralnie model score, normalized score, directional agreement ani intensity w P(sukcesu).** Jeśli żądane jest prawdopodobieństwo, udostępnij procent tylko po kalibracji z walidacją na danych out-of-sample, z rozdzieleniem od zgodności kierunkowej.

Konsensus ma prezentować: kierunek, liczba modeli zgodnych / liczba aktywnych, ważona zgodność (o ile zdefiniowana), status konfliktu, wagi pochodzące z konfiguracji oraz timestamp.

Kolejne panele:
- Siła sygnału,
- Jakość setupu,
- Kontekst ryzyka,
- MTF alignment (M1, M5, M15, M30, H1, H4, D1 — tylko faktycznie analizowane TF).

## 6. ANIMACJE I REAKCJE
Zastosuj dyskretne, rzeczywiście żyjące animacje:
1. pulsujące kontury budynku PEPE$SIGNAL i aktywnych paneli;
2. przepływ impulsów po sieci neuronowej na tle nagłówka i wokół lewej wieży;
3. łagodne przejście przy wyborze sygnału (150–250 ms);
4. animacja zmiany wartości i pasków model scoring (200–350 ms);
5. sygnałową falę po otrzymaniu nowego potwierdzonego sygnału;
6. delikatny puls dla statusów przychodzących z prawdziwego strumienia;
7. animacje alertów unieważnienia, bez zasłaniania wykresów.

Wszystkie animacje wyłącz lub ogranicz w `prefers-reduced-motion`. Nie generuj fałszywych „aktywności modeli” bez faktycznej telemetrii. Nie obciążaj głównego wątku przy aktywnym streamingu MT5.

## 7. KONTRAKTY DANYCH I ARCHITEKTURA
Dostosuj się do istniejących API; poniższy kontrakt jest poglądowy:

```ts
type SignalDirection = 'BUY' | 'SELL' | 'WAIT';
type SignalLifecycle = 'CANDIDATE' | 'CONFIRMED' | 'INVALIDATED' | 'EXPIRED' | 'FILLED' | 'CLOSED';
type ConditionState = 'MET' | 'NOT_MET' | 'PENDING' | 'UNKNOWN' | 'INVALIDATED';
interface SignalSnapshot {
  id: string; strategyId: string; strategyVersion: string;
  symbol: string; timeframe: string; direction: SignalDirection;
  status: SignalLifecycle; generatedAtUtc: string; updatedAtUtc: string;
  entry?: number; stopLoss?: number; targets?: number[];
  signalStrength?: number; setupQuality?: number;
  conditionResults: Array<{ ruleId:string; label:string; state:ConditionState; evidence?:string; evaluatedAtUtc:string }>;
  modelEvaluations: Array<{ modelId:string; modelVersion:string; timeframe:string; direction:string; rawScore?:number; calibratedProbability?:number; status:string; evaluatedAtUtc:string }>;
  invalidationRules: Array<{ ruleId:string; explanation:string; threshold?:number }>;
}
```

Narzędzia i adaptery sugerowane — dostosuj nazwy do projektu: `SignalRegistryAdapter`, `LiveSignalStream`, `SignalDetailService`, `ModelEvaluationAdapter`, `StrategyConditionsAdapter`, `SignalChartAdapter`, `MTFAlignmentService`, `ExecutionRiskReadAdapter`, `SignalHistoryStore`.

Wspieraj WebSocket/SSE lub obecny bus zdarzeń; snapshots + incremental events; ordering i dedup; retry z backoff; watermark/timestamp; reconnect i synchronizacja po utracie połączenia. Nie renderuj wyników z innego symbolu / TF po zmianie wyboru; anuluj opóźnione requests lub odrzucaj po id i wersji.

## 8. REAL DATA VS DEMO
Podgląd HTML w tej paczce zawiera sztuczne przykładowe sygnały i świece. W produkcji:
- nie wyświetlaj danych DEMO obok danych LIVE bez jednoznacznego rozróżnienia,
- nie pokazuj wyników lub stanów ON/OFF tylko dlatego, że użytkownik nacisnął przycisk,
- w razie braku danych pokaż `UNAVAILABLE` / `STALE` / `OFFLINE` / `N/A`,
- nie obiecuj skuteczności, zwrotu ani przyszłego ruchu ceny,
- stan wybranego instrumentu i rachunku przechowuj w istniejącym mechanizmie uprawnień;
- nie modyfikuj Execution Lock ani logiki składania zleceń.

## 9. TESTY ZGODNOŚCI WIZUALNEJ
Uruchom lokalnie aplikację (jeśli środowisko pozwala), wykonaj screenshot przy **1672×941 px, DPR=1** i zestaw z `assets/REFERENCE_APPROVED.png`.

1. Nakładka 50/50 (manual opacity) dla kontroli geometrycznej.
2. Mapa różnic pikselowych (diff heatmap).
3. SSIM (jeśli możliwe) — metryka pomocnicza, nie jedyne kryterium.
4. Weryfikacja osobno: nawigacja, tytuł, lewa wieża, liczba i szerokość kolumn, panel modeli, siła sygnału, wykres, warunki, tabela, kolory, fonty i glow.
5. Korekta proporcji, marginesów, borderów, wielkości czcionek i kolorów; powtarzaj porównanie.
6. Dla stanów dynamicznych zamrażaj dane i animacje, by wykonać powtarzalny screenshot.
7. Nie wolno uznawać pojedynczego wielkiego obrazu tła za rekonstrukcję interfejsu 1:1 — wszystkie dane i kontrolki muszą być prawdziwymi elementami UI.

Raport powinien jawnie wskazać różnice, które nie zostały usunięte. Z pojedynczego renderu nie można odtworzyć ukrytych powierzchni i pełnych szkieletów 3D — jeśli takie assety nie istnieją, opisz brak zamiast symulować skończoną realizację.

## 10. TESTY FUNKCJONALNE I INTEGRACYJNE
- Zmiana sygnału aktualizuje centralny wykres, entry, SL, TP, invalidation, model scores, narrative i MTF.
- Zmiana filtrów wpływa spójnie na listę i tabelę.
- Wybór sygnału historycznego nie pokazuje bieżącej oceny jako historycznej.
- Konkurujące wydarzenia nie nadpisują aktualnego wyboru.
- Dla WAIT i INVALIDATED brak fałszywego statusu gotowości do transakcji.
- Sygnały z różnych strategii mają rzeczywiste, różne reguły wejścia i invalidation.
- Wszystkie modele wyświetlają rzeczywiste statusy, timestampy i wersje.
- Brak nieuprawnionych akcji tradingowych z UI.
- Sprawdź responsywność 1920×1080, 1672×941, 1366×768 i 390×844.
- Zweryfikuj klawiaturę, focus, reduced motion, wycieki pamięci, reconnect i tryb offline.
- Uruchom testy regresji dla PEPE$WTC i pozostałych wież — bez modyfikowania ich wyglądu.

## 11. WYMAGANE DELIVERABLES
1. Zmieniony kod rzeczywistej aplikacji i adapterów.
2. Dokładny wykaz plików i zależności.
3. Działający panel PEPE$SIGNAL osadzony w prawdziwym routingu.
4. Wszystkie interaktywne sekcje i logika selekcji sygnałów.
5. Integracja z MT5, model registry i wszystkimi strategiami rzeczywiście istniejącymi w bocie.
6. Raport integracji: WORKING / PARTIAL / BLOCKED + dowody.
7. Screenshoty i mapa odchyłek względem obrazu referencyjnego.
8. Wyniki testów automatycznych i ręcznych.
9. Lista ograniczeń i brakujących usług lub modeli.

### KOŃCOWE POLECENIE
Odtwórz PEPE$SIGNAL **jak najwierniej wizualnie 1:1** oraz zapewnij prawdziwą funkcjonalność i kompatybilność z PepeMarketWizard. Nie kończ na statycznym mockupie; nie deklaruj niepotwierdzonych integracji i nie przedstawiaj generowanych procentów jako prawdopodobieństw skuteczności.
