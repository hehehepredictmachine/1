# E0 – Przygotowanie i inwentaryzacja

**Cel:** bezpieczny punkt startu i raport różnic spec ↔ kod, **zanim** cokolwiek zmienisz w aplikacji.

## Kroki
1. Kopia:
   - jeśli projekt jest w git, utwórz gałąź `ui/1.42-cinematic-forex`;
   - jeśli nie, skopiuj `frontend/src`, `frontend/public`, `frontend/index.html`, `desktop/splash.html` i `CHANGELOG.md` do `archive/ui_1_41/_backup_<data>/`.
2. Sprawdź wersję bazową. W `CHANGELOG.md` najwyższa ma być **1.41.0**, a `APP_VERSION` w backendzie też 1.41.0. Inna wersja → zatrzymaj się.
3. Zbuduj frontend bez zmian (`npm ci` jeśli trzeba, `npm run build`) i uruchom testy offline (`tools/run_tests.py`, tak jak w `05_TESTY_OFFLINE.bat`). Zapisz wynik bazowy. Testy, które padały już przed zmianami, wypisz osobno.
4. Inwentaryzacja **całego starego interfejsu** (do usunięcia w E8):
   - lista wszystkich plików `frontend/src` z oceną: stare UI / logika potrzebna nowemu UI (do wydzielenia w `core/`) / infrastruktura (api, store, util);
   - lista testów, które dotykają UI;
   - lista zasobów `public/`;
   - wypisz wszystkie odwołania do `Launcher`, `launcherNeeded`, `BootScreen`, `GalaxyMenu`, `galaxyEngine`, `NeuralCityMenu`, `cult-launcher`, `galaxy-menu`, `pmw.boot`, `mq.cult.joined`;
   - wypisz wszystkie odwołania do obrazów z `public/assets/cult|galaxy|neural`;
   - przeszukaj `frontend/src`, `tests/`, `desktop/`, `tools/` i dokumenty `.md`.
5. Sprawdź źródła danych z `spec/S3_DANE_I_KONTRAKTY.md`:
   - dla każdego endpointu potwierdź w `app.py` ścieżkę i parametry;
   - jeśli działa tryb syntetyczny (`07_START_DEMO_DANE_SYNTETYCZNE.bat`), pobierz po jednej odpowiedzi i zapisz ich **kształt** (klucze) do `update_1_42/raport/E0_ksztalty_api.json`; bez danych rachunku, tylko struktura;
   - zaznacz każde pole z S3, którego nie ma.
6. Rozstrzygnij punkty DO WERYFIKACJI z S2/S3, które da się sprawdzić w kodzie:
   - instrument BTC w CHARTS;
   - pola bramek w SIGNALS;
   - endpoint raportu Monte Carlo;
   - źródło znaczników wpłat w ROI;
   - dostępność Go ≥ 1.23 i sieci dla `tools/build_desktop.py` (przebudowa .exe – użytkownik ją zlecił);
   - **pytanie do użytkownika:** czy Studio (`studio.html`, `PepeTrainingStudio.exe`) zostaje bez zmian (domyślnie tak).
7. Skopiuj `update_1_42/zasoby/cinematic/intro.mp4` → `frontend/public/assets/cinematic/intro.mp4`. Sprawdź, że po buildzie plik jest w `frontend/dist/assets/cinematic/` i backend serwuje go z `/assets/cinematic/intro.mp4` (status 200, `video/mp4`).

## Raport E0 (wymagany)
- wynik bazowy build/testy;
- lista odwołań do starych motywów (plik → linia);
- tabela S3: endpoint / pole → ✅ istnieje / ❌ brak / ⚠️ inna postać;
- rozstrzygnięcia DO WERYFIKACJI;
- pytania do użytkownika (maks. 3), jeśli coś blokuje dalsze etapy.

**Nie zmieniaj w E0 kodu aplikacji** (wyjątek: skopiowanie pliku wideo do `public/`). Zatrzymaj się i poczekaj na „dalej”.
