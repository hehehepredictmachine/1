# K0 – Przygotowanie

**Cel:** bezpieczny punkt startu, rozpoznanie wariantu bazy i potwierdzenie, że test 1:1 działa w tym środowisku. **Nie zmieniasz kodu aplikacji.**

## Kroki

1. **Kopia:** gałąź `ui/charts-1do1` (git) albo kopia `frontend/src`, `frontend/public`, `CHANGELOG.md` do `archive/charts_backup_<data>/`.

2. **Wariant bazy** (zapisz w raporcie):

   | Wariant | Jak rozpoznać | Co robisz |
   |---|---|---|
   | **A** – nowy interfejs już jest (pełny pakiet 1.42.0 wdrożony lub w trakcie) | istnieje ekran FOREX z planetami i moduł ekranu CHARTS (np. `features/forex/screens/charts/`), trasa `#/forex?s=charts` | aktualizujesz ten ekran na miejscu. Jeśli pełny pakiet jest w trakcie, ten pakiet **zastępuje jego etap E3** |
   | **B** – czysta wersja 1.41.0 (stary interfejs) | brak ekranu FOREX, trasy `#/forex` | **zatrzymaj się i zapytaj** użytkownika: (1) najpierw wdrożyć pełny pakiet do etapu E2, czy (2) dodać sam ekran CHARTS pod `#/forex?s=charts` jako osobny widok (bez kuli FOREX, z powrotem do obecnego menu) |

3. **Wersja bazowa** z `CHANGELOG.md` i `APP_VERSION` – zapisz.

4. **Stan bazowy:** `npm run build`, `tsc -b`, `tools/run_tests.py`. Testy padające już przed zmianą wypisz osobno.

5. **Kształty API** (tylko klucze, bez danych rachunku) do `update_charts/raport/K0_ksztalty_api.json`, dla każdego endpointu z `spec/D1_DANE_I_KONTRAKTY_CHARTS.md`. Jeśli działa tryb syntetyczny (`07_START_DEMO_DANE_SYNTETYCZNE.bat`), użyj go. Tabela w raporcie: endpoint / pole → ✅ / ❌ brak / ⚠️ inna postać.

6. **Narzędzia testu 1:1:**
   - w `frontend` (lub osobnym folderze narzędzi): `npm i -D playwright` + `npx playwright install chromium`;
   - `node update_charts/narzedzia/charts_1do1/wzorzec_z_ref_b.mjs --tylko-wzorce` – renderuje wzorce **na tym komputerze** (czcionki i Chromium muszą być te same co przy teście aplikacji);
   - `node update_charts/narzedzia/charts_1do1/porownaj.mjs --szum` – szum wzorca ma wynosić 0 % we wszystkich scenariuszach. Inny wynik = zgłoś.

7. **Test zgodności SVP na kodzie bota:** `python update_charts/narzedzia/svp_zgodnosc/make_fixture.py`, potem `node update_charts/narzedzia/svp_zgodnosc/test_svp_port.mjs` (bez argumentu – sprawdza port z pakietu). Ma wyjść 27/27.

8. **DO WERYFIKACJI w kodzie:**
   - świece BTC, gdy silnik MT5 ma inny symbol (`/api/v1/market-zones/bars?instrument=BTC&tf=`);
   - czy backend ma GET liczący profil nazwanej sesji **bez zapisu** profilu (jeśli tak – K5 użyje backendu);
   - pola sygnałów potrzebne karcie planu (D1 §3) – czy są w odpowiedziach;
   - źródło BID / ASK / SPREAD (store `quote`).

## Raport K0
Wariant, wersja, stan bazowy, tabela pól API, wynik szumu wzorca, wynik SVP 27/27, rozstrzygnięcia DO WERYFIKACJI, pytania (maks. 3). **Czekaj na „dalej”.**
