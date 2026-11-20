# PepeMarketWizard – pakiet aktualizacji panelu CHARTS (1:1 z wizualizacją)

Pakiet zawiera instrukcje, według których Claude Code przebuduje **ekran CHARTS** tak, aby wyglądał i działał **dokładnie jak w wizualizacji** (wykres, okna RSI / MACD, Kronos, panel opcji, markery sygnałów, poziomy planu, karta „PLAN BOTA”), ale na prawdziwych danych z API bota.

| Co wprowadza | Szczegóły |
|---|---|
| Wygląd 1:1 | kod rysowania, CSS i znaczniki przeniesione z wizualizacji; zgodność sprawdza test pikselowy (8 scenariuszy) |
| Strategie bota jako wskaźniki | koszyki `FX_SMC`, `FX_SCALP`, `FX_HEDGE`, `S01–S12`, `SH`; markery, wejście, SL, TP1–TP3 (TP3 tylko tam, gdzie strategia go ma), karta planu |
| Strefy bota | tylko z wybranego TF (M1–M30), komunikat na innych TF |
| Session Volume Profile | profil każdej sesji, zgodność z silnikiem bota 27/27 |
| Wydanie | nowa wersja + przebudowa aplikacji (patrz `etapy/K7`) |

Ekran tylko odczytuje dane: **żadnych zleceń, żadnych zapisów w backendzie**. Silnik MT5, strategie i modele bez zmian.

## Zawartość

| Folder / plik | Co zawiera |
|---|---|
| `01_PROMPT_CHARTS.md` | **prompt do wklejenia w Claude Code** |
| `etapy/K0…K7` | etapy pracy |
| `spec/D1_DANE_I_KONTRAKTY_CHARTS.md` | skąd pochodzi każda wartość, model widoku |
| `spec/W1_WYGLAD_1DO1.md` | zasady przeniesienia wyglądu 1:1 |
| `spec/O1_KRYTERIA_ODBIORU.md` | lista odbioru |
| `referencje/` | wizualizacja, wycięty kod wzorca CHARTS, port SVP, zrzuty |
| `narzedzia/charts_1do1/` | test pikselowy 1:1 (dane, wzorce, skrypty) |
| `narzedzia/svp_zgodnosc/` | test zgodności Session Volume Profile z silnikiem |
| `MANIFEST_SHA256.txt` | sumy kontrolne |

## Jak uruchomić

1. Zrób kopię folderu bota albo commit.
2. Rozpakuj pakiet do głównego folderu bota jako **`update_charts/`** (obok `frontend/`, `backend/`, `desktop/`).
3. Otwórz Claude Code w głównym folderze bota i wklej całą treść `update_charts/01_PROMPT_CHARTS.md`.
4. Claude Code idzie etapami **K0 → K7**, po każdym zatrzymuje się z raportem i czeka na „dalej”.

## Związek z pełnym pakietem 1.42.0
- Jeśli nowy interfejs (kula FOREX) już jest – pakiet aktualizuje ekran CHARTS na miejscu.
- Jeśli pełny pakiet jest w trakcie – ten pakiet **zastępuje jego etap E3**; wydanie robi Z1 pełnego pakietu.
- Jeśli bot jest jeszcze w starym interfejsie 1.41.0 – Claude Code zapyta, czy najpierw wdrożyć pełny pakiet do E2, czy dodać sam ekran CHARTS.

## O co Claude Code zapyta / co sprawdzi (DO WERYFIKACJI)
- wariant bazy (powyżej);
- skąd świece BTC, gdy MT5 ma inny symbol;
- czy backend liczy profil sesji bez zapisu (wtedy użyje backendu zamiast portu);
- czy API podaje wszystkie pola karty planu (wynik sygnału, powody, udziały SH) – brak pola = stan pusty, nie zgadywanie;
- czy jest Go ≥ 1.23 do zbudowania .exe.

## Statusy
**POTWIERDZONE** – sprawdzone w kodzie 1.41.0 · **ZAŁOŻENIE** – przyjęta interpretacja · **PROPOZYCJA** – decyzja projektowa · **DO WERYFIKACJI** – do sprawdzenia przez Claude Code.
