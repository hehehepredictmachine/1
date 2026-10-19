# Moduły IQ Gold Gann, IQ Star Lines, PAL02M i Parabolic SAR (PMW-UPD-02)

## Co działa od razu
- **Parabolic SAR**: wspólny rdzeń (profil `MQ_SAR_WILDER_PROFILE_V1`, step 0,02 / max 0,2).
  - Konsumenci: scalp, lab, wykres i model reakcji.
  - Diagnostyka: flip, EP/AF, liczba świec od flipu, ryzyko whipsaw, dystans w ATR.
  - Płaski rynek oznacza „brak dowodu kierunku”, nawet jeśli seed wskazuje UP.
  - Na wykresie: przełącznik **SAR** w pasku opcji.
- **Panel**: Modele i trening → „Moduły IQ / PAL / SAR”. Pokazuje tożsamość, źródło, mapping, archiwum, trening i braki.
- **Agent**: wiedza IND-K01–K12 i narzędzie `get_indicator_context` (wartości zamrożone w snapshotcie). Bez klucza Claude działa opis deterministyczny.

## Podłączenie oryginalnych IQ (na Twoim komputerze z MT5)
1. Musisz mieć własną, licencjonowaną instalację IQ Gold Gann Levels MT5 (produkt 134935) lub IQ Star Lines MT5 (145140). Paczka nie zawiera płatnych plików.
2. W MetaEditor otwórz i skompiluj `mql5/PMW_ExtIndicatorExporter.mq5`. To pomocniczy wskaźnik: bez zleceń, nie zajmuje miejsca EA i niczego nie zmienia na wykresie.
3. Dodaj go do wykresu `XAUUSD-` z uruchomionym IQ.
   - `InpAdapterId`: `IQ_GOLD_GANN` albo `IQ_STAR_LINES`.
   - `InpPrefix`: prefiks nazw obiektów IQ (najpierw zostaw puste – eksporter zrobi inwentarz).
   - `InpProductVer`: wersja produktu.
4. Bot czyta pliki z `Common\Files\PMW_extind`. Inwentarz obiektów pokazuje `GET /api/v1/indicator-context/inventory?adapter=IQ_GOLD_GANN`.
5. Zapisz mapping (`PUT /api/v1/indicator-context/mapping`).
   - Reguły: prefiks + typ obiektu (HLINE/TREND/VLINE/RECTANGLE) + rodzaj (LEVEL/TRENDLINE/TIME_EVENT/TIME_WINDOW) + rola.
   - Zatwierdzenie wymaga przykładów, w których porównałeś liczby z wykresem.
   - Kolor nie jest podstawą mapowania. Zmiana wersji produktu wymaga ponownej weryfikacji.
6. Od tej chwili każdy odczyt trafia do archiwum point-in-time (`extind_snapshots`). Decyzja w chwili D używa tylko odczytów otrzymanych przed D.

## PAL02M
Narzędzie nie zostało zidentyfikowane, więc ma status **BLOCKED_IDENTITY_REQUIRED** i nie zwraca żadnych wartości. Po ustaleniu, czym jest, potrzebne są dwie rzeczy:
- manifest `data/extind/manifests/PAL02M.json` z polami: nazwa, producent, URL, platforma, wersja, hash pliku, wyjścia, licencja, zachowanie repaint;
- zaufany dekoder w kodzie projektu.

Nie podstawiamy innego wskaźnika o podobnej nazwie.

## Trening i ocena (model reakcji)
`MODULY_IQ_PAL_SAR.bat [XAUUSD|BTC]` wykonuje kolejno: status → rejestracja → zbiór → kalibracja SAR → trening → raport. Trening uruchamia też wspólny runner (00_TRENING_START.bat).

- **Próbka:** każdy cykl replay profilu scalp (bez wybierania tylko zyskownych).
- **Etykieta:** y = TP1 przed SL w zamrożonej polityce. Obok zapisywane jest net_R. To nie jest P(zysk netto).
- **Podział:** FIT 45% / TUNE 15% / CALIBRATION 10% / POLICY 10% / HOLDOUT 20%, chronologicznie, z purge i embargiem 30 min.
- **Kalibracja SAR:** siatka step {0,01;0,02;0,03} × max {0,1;0,2;0,3}, wybór wyłącznie na TUNE. Parametry SAR działającego bota się nie zmieniają.
- **Warianty:** BASE, BASE+SAR, BASE+IQ_GOLD_GANN, BASE+IQ_STAR_LINES, BASE+PAL02M (zablokowany). Porównanie z BASE na tym samym holdoucie, z bootstrapem bloków dniowych.
- **Wynik:** artefakty z manifestem, sumą kontrolną i kontrolą parity. Dane syntetyczne trafiają do `fixture_runs` i nigdy nie są aktywne.
- **Aktywacja:** tylko ręcznie (panel albo `indicator-context activate`), w trybie SHADOW. Model nie jest bramką i nie zmienia zleceń.

## Czego nie wykonano w środowisku budowy
Kompilacja eksportera (NOT_COMPILED_NO_METAEDITOR), test na produktach IQ (PRODUCT_NOT_INSTALLED), parytet z MT5 iSAR (MT5_PARITY_NOT_RUN) oraz trening na danych rzeczywistych.

## Rollback
- Model: `python -m masterquo indicator-context rollback --asset XAUUSD` albo przycisk w panelu.
- Mapping: usuń `data/extind/mappings/<ADAPTER>.json`.
- Archiwum zostaje w bazie.
