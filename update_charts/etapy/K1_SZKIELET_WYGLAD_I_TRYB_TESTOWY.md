# K1 – Szkielet ekranu, wygląd 1:1, warstwa danych, tryb testowy

**Wzorzec:** `referencje/kod/charts_wzorzec/charts.html`, `charts.css`, z `charts.js`: `CH`, `L`, `UNAVAIL`, `TFR`, `TFSEC`, `KR_TFS`, `KR_H`, `ASSETS` (tylko `d` = liczba miejsc), `setChartStatus`, `fmtP`, `fmtT`, `tzShift`, `chartsPlanet`, `rectOf`.

## Zakres

1. **Moduły** (nazwy dopasuj do konwencji projektu, zasada ta sama):
   - `screens/charts/ChartsScreen.tsx` – React: znaczniki 1:1 z `charts.html`, montuje renderer w `useEffect` (`const dispose = mountCharts(el, deps); return dispose;`);
   - `screens/charts/charts.css` – kopia `charts.css` (bez zmian wartości; jeśli trzeba, zawęź selektory prefiksem `#charts-screen`, ale nie zmieniaj żadnej deklaracji);
   - `screens/charts/chartsRender.ts` – przeniesiony kod rysowania (K2–K5);
   - `screens/charts/chartsData.ts` – typy odpowiedzi API, adaptery `toViewModel()` (czyste funkcje), hook `useChartsData()`;
   - `screens/charts/svpPort.(ts|js)` – port SVP (K5).

2. **Model widoku = stan wzorca.** Adaptery zamieniają odpowiedzi API dokładnie na struktury, które czyta kod wzorca (`CH.data`, sygnały `s.*`, strefy `z.*`, stany strategii, meta, szanse modeli, Kronos). Kształt jest opisany w `spec/D1_DANE_I_KONTRAKTY_CHARTS.md` §3 i widoczny w `narzedzia/charts_1do1/fixtures/*.json`. Dzięki temu kod rysowania przenosisz bez zmian.

3. **Tryb testowy** (tylko gdy `import.meta.env.MODE === 'test'` albo flaga `?pmw_test=1` w buildzie deweloperskim; w produkcji hak nie istnieje):
   ```ts
   window.__PMW_TEST__ = { charts: { load(fx): Promise<void> } }
   ```
   - `load` otwiera ekran CHARTS w stanie „wszedł” (przejście zakończone), **odłącza API, store i polling**, ładuje fixture **przez te same struktury modelu widoku** (`candles`, `signals`, `zones`, `states`, `meta`, `probs`, `kronos`, `quote`, `L`, `str`, `tab`, `view`, `offset`, `cardMin`, `tz`, `serverOff`) i zamraża czas na żywo;
   - teksty pochodzenia danych w trybie testowym biorą wartość z `fx.test_texts` (`cardNote` = ostatnia notka karty planu, `headerTag` = znacznik w nagłówku), aby karta miała tę samą wysokość co we wzorcu;
   - `load` rozwiązuje się, gdy pierwsza klatka jest narysowana.
   Odpowiednik we wzorcu: `PMW_PREVIEW._chartsLoad` w `REF_B` (pokazuje dokładnie, co ustawić).

4. **Nagłówek 1:1:** tytuł „01 CHARTS”, przełącznik instrumentu, TF z `GET /api/v1/timeframes` (kropka stanu danych jak we wzorcu), BID / ASK / SPREAD ze store `quote`, wybór strefy czasu (LOKALNY / UTC / SERWER), status MT5 (`setChartStatus`: MT5 POŁĄCZONY / ŁADOWANIE / ROZŁĄCZONO / DANE NIEAKTUALNE). Znacznik `.demo-tag` pokazuje się tylko przy danych syntetycznych (`SYNTETYCZNE`), nigdy „DEMO” w produkcji.

5. **Przejście** wejścia 2400 ms i wyjścia 1500 ms według `chartsPlanet` (wariant A: wpięte w istniejący `SCREENS[0]`). Linie wykresu zaczynają świecić dopiero po przejściu.

6. **Dostępność 1:1:** role `tab`/`tablist`, `aria-selected`, `aria-pressed`, fokus na `#mc-plot` po wejściu, `inert` gdy ekran niewidoczny, komunikaty `aria-live` (wybór TF, wybór planu) nie częściej niż co 5 s.

## Kryteria K1
- [ ] Ekran otwiera się, nagłówek i ramki okien wyglądają jak `S04_charts.png` (bez danych na wykresie – stan `ŁADOWANIE`).
- [ ] `window.__PMW_TEST__.charts.load` istnieje tylko w trybie testowym (sprawdź build produkcyjny: `grep -r "__PMW_TEST__" frontend/dist` → 0 trafień).
- [ ] Adaptery mają testy jednostkowe na kształtach z K0.
