# PepeMarketWizard 1.42.0: nowy cinematic i kula FOREX (paczka dla Claude Code)

Ta paczka zawiera instrukcje dla Claude Code. Według nich Claude Code wprowadzi do kodu bota (wersja bazowa **1.41.0**):

1. **Nowy cinematic startowy i menu główne.** Intro z filmu, potem trzy planety: **FOREX, CRYPTO, OTC**.
2. **W pełni zaprojektowaną kulę FOREX:**
   - przelot kamery w cząsteczki;
   - ekran FOREX z tłem czarnej głębi;
   - dwa panele pracy modeli;
   - drogę mleczną;
   - 4 planety: **CHARTS, SIGNALS, MODELS & BACKTEST, ROI**, każdą z własnym ekranem i przejściem.
3. **Panele systemowe w nowym stylu**: Ustawienia (w tym MT5), Tryb pracy + STOP, Diagnostyka. Logika identyczna jak dziś.
4. **Pełne usunięcie starego interfejsu**: wszystkie 41 ekranów, JOIN THE CULT, boot intro 1.39, Galaxy V2, wieże, strony, terminale. Stare adresy przekierowują na nowe miejsca, a pliki idą do archiwum.
5. **Pełną przebudowę aplikacji 1.42.0**: frontend, okno Windows `PepeMarketWizardDesktop.exe` z nowym oknem startowym, paczki wydania.

Silnik bota, strategie, modele, API i moduły MQL5 w MetaTraderze **zostają bez zmian**.

Wszystkie ekrany w paczce działają na **prawdziwych danych z API bota**. Liczby w plikach referencyjnych są demonstracyjne (oznaczone DEMO) i **nie wolno ich przenosić do aplikacji**.

---

## Co jest w paczce

| Folder / plik | Co zawiera |
|---|---|
| `01_PROMPT_GLOWNY.md` | **Prompt do wklejenia w Claude Code.** Zasady, kolejność etapów, warunki zatrzymania. |
| `etapy/E0…E9` | Szczegółowe zadania etapów, każdy z kryteriami odbioru. |
| `spec/S1…S6` | Specyfikacja: architektura i pliki, routing i usunięcie starego UI, dane i kontrakty API, wygląd/animacje/dostępność, kryteria odbioru, panele systemowe. |
| `referencje/REF_A_menu_glowne_v1_1.html` | Działający wzorzec **menu głównego**: intro z filmu, 3 planety, wybór, powrót, renderer CPU. |
| `referencje/REF_B_kula_forex_i_ekrany.html` | Działający wzorzec **kuli FOREX**: przelot, ekran FOREX, panele modeli, 4 planety i 4 ekrany. Dane DEMO. |
| `referencje/zrzuty/` | Zrzuty wzorcowe każdego ekranu (A1–A2 menu, S01–S07 FOREX). |
| `zasoby/cinematic/intro.mp4` | Oryginalny film intro (H.264 736×414, 6,4 s, z dźwiękiem), wydobyty bez zmian z REF_A. |
| `MANIFEST_SHA256.txt` | Sumy kontrolne plików paczki. |

## Jak uruchomić

1. Zrób kopię folderu bota albo commit, jeśli używasz git.
2. Rozpakuj paczkę do **głównego folderu bota** jako `update_1_42/`, tak żeby obok były `frontend/`, `backend/` i `desktop/`.
3. Otwórz Claude Code w głównym folderze bota.
4. Wklej całą treść `update_1_42/01_PROMPT_GLOWNY.md`.
5. Claude Code wykona etapy po kolei: **E0 → E9**. Po każdym etapie zatrzyma się z raportem i poczeka na „dalej”.
6. Odbiór: `update_1_42/spec/S5_KRYTERIA_ODBIORU.md`, punkt po punkcie.

Jeśli wolisz pracować etapami w osobnych sesjach, w każdej sesji wklej prompt główny i dopisz na końcu: „Wykonaj tylko etap EX”.

## Statusy w dokumentach

- **POTWIERDZONE**: sprawdzone w kodzie 1.41.0 (plik, endpoint, pole).
- **ZAŁOŻENIE**: przyjęta interpretacja. Claude Code jej nie zmienia bez Twojej zgody.
- **PROPOZYCJA**: decyzja projektowa z podglądu, zaakceptowana w rozmowie.
- **DO WERYFIKACJI**: Claude Code musi to sprawdzić w kodzie i zgłosić wynik, zanim zbuduje zależną część.

## Ważne ograniczenia (dotyczą całej paczki)

- **Zero zmian w logice handlu.** Ekrany FOREX tylko czytają dane. Tryb pracy, STOP i ustawienia działają wyłącznie w panelach systemowych, z tymi samymi wywołaniami i potwierdzeniami co w 1.41.0. Przyciski treningu prowadzą do istniejących, potwierdzanych ścieżek.
- **Zero zmyślonych danych.** Gdy brakuje źródła, ekran pokazuje stan: BRAK DANYCH / NOT_TRAINED / NOT_RUN / SMALL_SAMPLE. Procent pokazujemy tylko wtedy, gdy model zwraca prawdopodobieństwo. Score zawsze jest opisany jako score.
- **CRYPTO i OTC** w tej wersji to planety menu z ekranem „Tryb w przygotowaniu”. Wybór planety **nie przełącza** profilu rynku bota.
