# PROMPT GŁÓWNY: PepeMarketWizard 1.42.0, nowy cinematic i kula FOREX

Jesteś głównym inżynierem frontendu PepeMarketWizard Desktop (React 19 + TypeScript + Vite, backend FastAPI, wersja bazowa 1.41.0).
Wprowadzasz aktualizację **1.42.0**, której pełny opis jest w folderze `update_1_42/`. Pracujesz po polsku: komentarze i raporty piszesz po polsku, identyfikatory w kodzie po angielsku, jak w reszcie projektu.

## Cel

1. Nowy start aplikacji: **cinematic intro z filmu**, a po nim **menu główne z trzema planetami** FOREX / CRYPTO / OTC. Wzorzec: `referencje/REF_A_menu_glowne_v1_1.html`.
2. **Kula FOREX:**
   - kliknięcie planety FOREX uruchamia przelot kamery w cząsteczki;
   - przelot kończy się na ekranie FOREX (tło czarnej głębi, panele MODEL A / MODEL B, droga mleczna, 4 planety);
   - każda planeta otwiera swój ekran z przejściem: **CHARTS, SIGNALS, MODELS & BACKTEST, ROI**.
   - Wzorzec: `referencje/REF_B_kula_forex_i_ekrany.html`.
3. **Panele systemowe w nowym stylu**: Ustawienia (w tym MT5), Tryb pracy + STOP, Diagnostyka. Logika 1:1 z dzisiejszych dialogów (`spec/S6_PANELE_SYSTEMOWE.md`).
4. **Pełne usunięcie starego interfejsu** (wszystkie 41 ekranów, launcher JOIN THE CULT, boot intro, Galaxy V2, wieże, strony, terminale), przekierowania starych adresów i **pełna przebudowa aplikacji 1.42.0**: frontend, okno Windows .exe, paczki wydania. Szczegóły w `spec/S2_ROUTING_I_ZAMIANA_MOTYWOW.md`.
   Silnik, strategie, modele, API i moduły MQL5 w MetaTraderze **zostają bez zmian**.

## Źródła prawdy (czytaj w tej kolejności)

1. `spec/S1_ARCHITEKTURA_I_PLIKI.md`: struktura modułów i cykl życia rendererów.
2. `spec/S2_ROUTING_I_ZAMIANA_MOTYWOW.md`: trasy, co usunąć, co zostawić jako alias.
3. `spec/S3_DANE_I_KONTRAKTY.md`: każdy element UI → endpoint/pole → stan pustych danych.
4. `spec/S4_WYGLAD_ANIMACJE_DOSTEPNOSC.md`: tokeny, czasy, przejścia, ograniczenie ruchu, a11y.
5. `spec/S6_PANELE_SYSTEMOWE.md`: panele systemowe i okno startowe Windows.
6. `referencje/*.html`: wzorce wizualne i ruchowe. Shadery GLSL przenosisz **1:1** (stałe tekstowe), logikę rysowania przepisujesz do modułów TS.
7. `referencje/zrzuty/*.png`: obraz docelowy.

Kod bota ma pierwszeństwo przed opisem. Jeśli endpoint, pole albo plik wygląda inaczej niż w spec, **zatrzymaj się i zgłoś różnicę**. Nie zgaduj.

## Twarde zasady

1. **Nie wolno przenosić danych DEMO z REF_B**. Dotyczy to generatorów `genSignals`, `genModels`, `genRoi`, `loadSeries`, `seeded`, losowych serii i tabel. W aplikacji każda liczba pochodzi z API (S3). Brak źródła oznacza stan pustych danych z S3.
2. **Prawdopodobieństwo w %** pokazujesz tylko dla `unit=probability` z modelu skalibrowanego (kontrakt PMW-PRED, MQ-SIGNAL-1.0.0). Score, częstość historyczna i symulacja mają swoje etykiety. AI nigdy nie podaje procentu.
3. **Żadnych zleceń i zmian stanu bota z nowych ekranów.** Wolno tylko czytać (GET). Wyjątek: przyciski, które już istnieją w Centrum treningu i w Wykresach bota, wywołujesz tymi samymi funkcjami i z tymi samymi potwierdzeniami. Nie twórz nowych ścieżek POST.
4. **Nie dodawaj funkcji spoza paczki** i nie przywracaj starych koncepcji. Jeśli czegoś brakuje do spełnienia kryterium, zgłoś to.
5. **CSP**: `default-src 'self'`. Film intro musi być plikiem (`/assets/cinematic/intro.mp4`), **nie** `data:` URI. Bez skryptów inline i bez zewnętrznych CDN.
6. **Wydajność**: jeden kontekst WebGL na aktywny widok. Renderery montujesz i niszczysz w `useEffect`: `dispose` kasuje bufory, programy i RAF, a `webglcontextlost` jest obsłużony. Pauza przy `visibilitychange`. Limit DPR 1,65 jak we wzorcach.
7. **Ograniczenie ruchu** (`prefers-reduced-motion` i przełącznik w UI) działa na każdym ekranie, tak jak we wzorcach.
8. **Zero regresji funkcji bota**:
   - każda funkcja niezbędna do prowadzenia bota (ustawienia/MT5, tryb pracy, STOP, diagnostyka) działa w nowym UI identycznie jak w 1.41.0;
   - stare adresy przekierowują na nowe miejsca;
   - `npm run build` i `tsc -b` przechodzą bez błędów;
   - testy silnika z `05_TESTY_OFFLINE.bat` (tools/run_tests.py) przechodzą;
   - testy starego UI przenosisz lub przepisujesz zgodnie z E8.
9. **Stary interfejs przenosisz do `archive/ui_1_41/`, nie kasujesz.** Archiwum nie wchodzi do buildu ani do paczek wydania.

## Kolejność pracy

Wykonuj etapy **po kolei**. Każdy opis jest w `etapy/`:

| Etap | Plik | Wynik |
|---|---|---|
| E0 | `E0_PRZYGOTOWANIE.md` | inwentaryzacja, kopia, raport różnic spec vs kod |
| E1 | `E1_CINEMATIC_I_MENU_GLOWNE.md` | intro z filmu + menu 3 planet jako `#/menu` |
| E2 | `E2_PRZELOT_I_EKRAN_FOREX.md` | przelot + ekran FOREX (`#/forex`) z panelami modeli i 4 planetami |
| E3 | `E3_EKRAN_CHARTS.md` | `#/forex/charts` |
| E4 | `E4_EKRAN_SIGNALS.md` | `#/forex/signals` |
| E5 | `E5_EKRAN_MODELS_BACKTEST.md` | `#/forex/models` |
| E6 | `E6_EKRAN_ROI.md` | `#/forex/roi` |
| E7 | `E7_PANELE_SYSTEMOWE.md` | Ustawienia/MT5, Tryb pracy, STOP, Diagnostyka w nowym stylu |
| E8 | `E8_USUNIECIE_STAREGO_UI_PRZEBUDOWA.md` | pełne usunięcie starego UI, przekierowania, splash, testy, 1.42.0, pełna przebudowa (dist, exe, paczki) |
| E9 | `E9_ODBIOR.md` | odbiór wg `spec/S5_KRYTERIA_ODBIORU.md` + zrzuty porównawcze |

Po każdym etapie:
- uruchom `npm run build` (folder `frontend`);
- zrób zrzut ekranu tego etapu: Playwright/Chromium jest już używany w testach UI, a wynik zapisz do `update_1_42/raport/`;
- porównaj go ze zrzutem wzorcowym z `referencje/zrzuty/`;
- wypisz raport: co zrobione, pliki zmienione/dodane/usunięte, odstępstwa od wzorca z uzasadnieniem, punkty DO WERYFIKACJI z wynikiem;
- **zatrzymaj się i poczekaj na „dalej”**.

## Warunki zatrzymania (pytasz, zanim zrobisz)

- Endpoint lub pole z S3 nie istnieje albo ma inną postać.
- Element wymagałby zapisu do backendu (POST/PUT) spoza istniejących, potwierdzanych akcji.
- Zmiana dotyka logiki handlu, profili rynku, ryzyka, trybu pracy albo okna desktopowego (Go) poza tym, co opisują E7/E8.
- Usunięcie pliku, którego logika jest potrzebna w nowym UI i nie da się jej wydzielić do `core/` bez zmiany zachowania.
- Kryterium z S5 nie da się spełnić bez odstępstwa od wzorca.

Zacznij od etapu **E0**.
