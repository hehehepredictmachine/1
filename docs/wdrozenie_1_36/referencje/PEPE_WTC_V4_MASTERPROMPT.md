# PEPEMARKETWIZARD — PEPE$WTC V4
## MASTERPROMPT DLA CLAUDE CODE
### MULTI-CHART • KRONOS • AI LIVE ZONES • VOLUME PROFILE AUTO ZONES

## CEL
Zaimplementuj produkcyjną wersję panelu **PEPE$WTC** w istniejącym projekcie PepeMarketWizard. Panel ma zachować stylistykę referencyjnej grafiki i obecnego prototypu webowego, ale zostać podłączony do realnych danych, modeli i usług bota.

Najważniejsze wymagania:
- duży główny wykres,
- możliwość dodawania wielu wykresów z różnymi timeframe'ami,
- wszystkie rzeczywiście dostępne indykatory bota,
- Kronos podłączony do wykresu,
- obsługa multi-timeframe,
- ręczne i automatyczne wyznaczanie stref,
- **automatyczne wyznaczanie stref przez Volume Profile**.

---

## 1. ZASOBY REFERENCYJNE
- `REFERENCE_PANEL_IMAGE.png` — główna referencja wizualna.
- `index.html` / `PepeMarketWizard_PEPE_WTC_V4_Standalone.html` — referencja zachowania i układu prototypu.
- `PREVIEW.png` — szybki podgląd.

Nie kopiuj ślepo uproszczonego kodu demonstracyjnego jako logiki produkcyjnej.

---

## 2. AUDYT PRZED WDROŻENIEM
Przed implementacją:
1. Zidentyfikuj stack UI i architekturę aplikacji.
2. Zlokalizuj realny MT5 Bridge.
3. Zlokalizuj realny moduł Kronos i checkpointy.
4. Zlokalizuj registry wskaźników, strategii i modeli AI.
5. Zlokalizuj istniejące moduły AI Live Zones, Setup Builder, Setup Checklist, sygnałów LIVE i Execution Lock.
6. Zidentyfikuj obecne źródła danych potrzebne do Volume Profile.

Nie twórz nowego równoległego silnika, jeśli istnieje działający komponent.

---

## 3. UKŁAD PANELU
Zachowaj układ podobny do prototypu:

### GÓRNY PASEK
- logo PepeMarketWizard,
- aktywna sekcja PEPE$WTC,
- status środowiska (DEMO / LIVE),
- podstawowa nawigacja.

### NAD WYKRESEM
- wybór instrumentu,
- wybór timeframe głównego wykresu,
- przycisk `Dodaj wykres`,
- konfigurator Kronos,
- wybór układu,
- reset widoku.

### PASEK INDIKATORÓW
Wyświetl wszystkie rzeczywiście dostępne wskaźniki bota, między innymi gdy są dostępne:
- EMA / SMA,
- VWAP,
- RSI,
- MACD,
- Bollinger Bands,
- ATR,
- Volume Profile,
- Order Blocks,
- Fair Value Gaps,
- Liquidity,
- Supply / Demand,
- S/R Bands,
- Session High / Low.

### LEWA KOLUMNA
- Kronos status,
- sygnały LIVE,
- Multi-Timeframe AI Matrix,
- neural Pepe assistant.

### CENTRUM
- duży główny wykres,
- automatyczne i ręczne strefy na wykresie,
- nakładka Volume Profile,
- pod wykresem: Smart Trade Setup Builder, Live Setup Checklist, AI Live Zones, Volume Profile Auto Zones.

### PRAWA KOLUMNA
- Kronos M1/M5 controller,
- Model Consensus,
- Analysis / Setup Summary.

### DOLNA CZĘŚĆ
- Multi-Chart Workspace z wieloma wykresami.

---

## 4. MULTI-CHART WORKSPACE
Funkcja obowiązkowa:
- użytkownik może dodawać i usuwać wiele wykresów,
- każdy wykres ma niezależny symbol i timeframe,
- wspierane TF: M1, M3 jeśli dostępny, M5, M15, M30, H1, H4, D1,
- kliknięcie miniwykresu synchronizuje go z głównym wykresem,
- deduplikuj subskrypcje danych,
- poprawnie rozpoznawaj świecę formującą się i zamkniętą.

---

## 5. KRONOS AI
Wymagania:
- tryb OFF / AUTO / MANUAL,
- niezależna obsługa M1 i M5,
- możliwość włączenia prognozy na wykresie,
- poprawne przypisanie prognoz do timeframe i timestampów,
- realny status modelu: READY / RUNNING / OFF / ERROR / STALE,
- brak wymyślonych confidence score, jeśli model ich nie zwraca.

Kronos ma być podłączony do głównego wykresu i wspierać setup checklist / consensus.

---

## 6. STREFY — RĘCZNE I AUTOMATYCZNE
Zaimplementuj dwa tryby pracy stref:

### TRYB MANUAL
- użytkownik może ręcznie włączać/wyłączać warstwy stref,
- użytkownik może ręcznie zaznaczać / edytować strefy,
- wspieraj co najmniej: Supply / Demand, OB, FVG, Liquidity Pools, S/R.

### TRYB AUTO
- system automatycznie wykrywa i aktualizuje strefy w czasie rzeczywistym,
- strefy są aktualizowane po nadejściu nowych danych / zamknięciu świecy,
- każda strefa ma typ, zakres cenowy, timeframe źródłowy, status aktywności i znacznik czasu.

Strefy muszą być czytelnie oznaczone na wykresie i możliwe do filtrowania.

---

## 7. VOLUME PROFILE — AUTO ZONES
To jest nowy element obowiązkowy.

### CEL
Na podstawie Volume Profile panel ma automatycznie wykrywać i prezentować najważniejsze strefy cenowe.

### WYMAGANIA FUNKCJONALNE
Zbuduj moduł **Volume Profile Auto Zones**, który:
- liczy Volume Profile dla wybranego zakresu / okna,
- obsługuje co najmniej:
  - POC (Point of Control),
  - VAH (Value Area High),
  - VAL (Value Area Low),
  - HVN (High Volume Nodes),
  - LVN (Low Volume Nodes),
- generuje na ich podstawie automatyczne strefy,
- pokazuje strefy na wykresie jako osobną warstwę,
- pozwala włączyć/wyłączyć każdy typ,
- synchronizuje wyniki z timeframe wykresu.

### ZASADY
- nie symuluj danych wolumenowych, jeśli nie są dostępne; wykorzystuj realne dostępne dane,
- jeśli zakres danych nie pozwala na poprawne wyliczenie, oznacz brak danych,
- nie traktuj każdego poziomu VP jako pełnoprawnej strefy handlowej bez jawnego oznaczenia typu,
- aktualizuj strefy przy zmianie instrumentu, timeframe'u i zakresu danych.

### UI DLA VOLUME PROFILE AUTO ZONES
Pod wykresem lub w prawej kolumnie dodaj oddzielny moduł, który pokazuje:
- status: ACTIVE / OFF / ERROR,
- przełączniki ON/OFF dla:
  - Volume Profile,
  - POC,
  - VAH/VAL,
  - VP Auto Zones,
- listę wykrytych stref,
- filtr timeframe,
- tryb AUTO / MANUAL dla aktualizacji.

---

## 8. SMART TRADE SETUP BUILDER I CHECKLIST
- Entry, SL, TP1, TP2, TP3,
- kalkulacja Risk/Reward,
- Setup Quality,
- Signal Strength,
- status Execution Lock,
- checklista warunków strategii oraz invalidation.

Edycja poziomów nie może automatycznie otwierać zlecenia.

---

## 9. SYGNAŁY LIVE / MODEL CONSENSUS / MTF MATRIX
- korzystaj z rzeczywistych strumieni danych i adaptera modeli,
- rozróżniaj siłę sygnału, jakość setupu, zgodność modeli i prawdopodobieństwo skalibrowane,
- kliknięcie sygnału prowadzi do odpowiedniego instrumentu i timeframe.

---

## 10. DANE I BEZPIECZEŃSTWO
- główne źródło: MT5 Bridge,
- bez screenshotów jako źródła danych,
- obsługa symboli z sufiksami brokera,
- retry, staleness, rozłączenia i ponowna synchronizacja,
- brak sekretów MT5 w UI,
- brak możliwości otwierania zleceń bez istniejącego przepływu autoryzacji i blokad.

---

## 11. WYDAJNOŚĆ I UX
- czytelność danych ponad ozdobniki,
- subtelne animacje neuralne,
- brak blokowania głównego wątku,
- poprawne odpinanie subskrypcji,
- obsługa `prefers-reduced-motion`, klawiatury i focus states,
- responsywność od laptopa po ultrawide.

---

## 12. KRYTERIA ODBIORU
Implementacja jest ukończona dopiero, gdy:
1. można dodawać i usuwać wiele wykresów,
2. każdy wykres ma niezależny timeframe,
3. Kronos działa dla M1 i M5,
4. wszystkie dostępne indykatory są poprawnie podłączone,
5. działają ręczne i automatyczne strefy,
6. działa **automatyczne wyznaczanie stref przez Volume Profile**,
7. strefy VP są widoczne na wykresie i można je filtrować,
8. panel działa z realnym MT5 Bridge,
9. nie ma sztucznych wyników AI w trybie produkcyjnym,
10. dostarczony jest raport zmian, wyników testów i braków.

---

## 13. REZULTAT KOŃCOWY
Dostarcz:
- produkcyjny panel PEPE$WTC,
- integrację z MT5,
- integrację z Kronos,
- obsługę multi-chart i multi-timeframe,
- wszystkie dostępne indykatory,
- AI Live Zones,
- Smart Trade Setup Builder,
- Live Setup Checklist,
- **Volume Profile Auto Zones**,
- raport wdrożenia i testów.

Nie przebudowuj innych sekcji aplikacji.
