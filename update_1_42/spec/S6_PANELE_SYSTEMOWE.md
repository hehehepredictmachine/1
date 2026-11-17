# S6 – Panele systemowe w nowym stylu (Ustawienia · Tryb pracy + STOP · Diagnostyka)

**Decyzja użytkownika (POTWIERDZONE):** stare ekrany są usuwane. Funkcje niezbędne do prowadzenia bota przechodzą do paneli w nowym stylu, dostępnych z menu i z każdego ekranu.
**Zasada:** to jest **przeniesienie logiki 1:1 z nowym wyglądem**. Te same wywołania API, te same potwierdzenia, te same teksty ostrzeżeń. Zero nowych funkcji i zero zmian w zachowaniu.
Źródło logiki (POTWIERDZONE w 1.41.0):
- `frontend/src/components/Dialogs.tsx`: `SettingsModal` (l. ~20), `ModeDialog` (~257), `PowerDialog` (~319);
- `pages/AnalyticsPages.tsx`: `DiagnosticsPage` (~478);
- wskaźniki stanu z `components/layout/AppShell.tsx` (`chip-exec`, `chip-mode`, `stop-button`).

## 1. Dostęp

| Miejsce | Jak |
|---|---|
| Menu główne | pasek `#tools` (prawy dół): ikony **Ustawienia**, **Tryb pracy**, **STOP**, **Diagnostyka** obok istniejących (intro, dźwięk, ruch, pełny ekran) |
| Ekran FOREX i ekrany planet | prawy dół (miejsce ikony „⇄” z REF_B): te same 4 ikony |
| Każdy ekran | **wskaźnik stanu wykonania** w prawym górnym rogu, przeniesiony z `chip-exec`/`chip-mode`: „Tryb PAPER / AUTO_DEMO / AUTO_LIVE / SIGNALS” albo „STOP nowych wejść”. Kliknięcie otwiera panel Tryb pracy. Kolor jak dziś: AUTO_LIVE = ostrzegawczy, STOP = czerwony |
| Trasa | `#/system?p=settings \| mode \| diagnostics`, linkowalna, wstecz wraca na ekran źródłowy |

**STOP** jest zawsze osiągalny jednym kliknięciem z każdego ekranu (tak jak dziś przycisk w górnym pasku). To warunek bezpieczeństwa, nie nowa funkcja.

## 2. Wygląd (PROPOZYCJA)

- **Szuflada z prawej** nad bieżącym ekranem, szerokość `clamp(420px, 34vw, 560px)`, tło `.cs-win` z narożnikami, przyciemnienie sceny pod spodem (`rgba(0,0,0,.55)`).
- Scena WebGL pod szufladą zwalnia do 30% (jak `idle` w `STATUS`), zamiast się zatrzymywać.
- Nagłówek: numer i nazwa jak planety („SYS · USTAWIENIA”) oraz zakładki USTAWIENIA / TRYB PRACY / STOP / DIAGNOSTYKA.
- Pola formularzy w stylu nowego UI:
  - linia dolna `#2b303b`, fokus `#dfe3eb`;
  - przyciski jak `.act` z MODELS (obramowanie, wielkie litery z rozstrzeleniem);
  - przycisk niebezpieczny w kolorze `#e0b3b3`;
  - komunikaty jak `#mb-toast`.
- Wejście: szuflada wsuwa się w 420 ms (`cubic-bezier(.22,1,.36,1)`), treść pojawia się wierszami (styl `mbIn`). Przy ograniczeniu ruchu tylko przenikanie.
- Dostępność:
  - `role="dialog"`, `aria-modal="true"`, pułapka fokusu, ESC zamyka (jeśli nic się nie zapisuje), powrót fokusu do przycisku, który otworzył panel;
  - komunikaty w `aria-live`.

## 3. Zawartość (logika z 1.41.0, bez zmian)

### 3.1 USTAWIENIA (`SettingsModal`)
- Konfiguracja: `GET /api/v1/config`, zapis `PUT /api/v1/config` (wszystkie pola, które edytuje dziś `SettingsModal`: terminal, symbol/lista symboli, pomijane symbole, parametry pokazywane w modalu itd.).
- Hasło MT5 (opcjonalne): `POST /api/v1/secrets` (`MT5_PASSWORD`), usuń hasło, **Połącz ponownie** `POST /api/v1/mt5/reconnect`.
- Klucz Anthropic: `POST /api/v1/secrets/anthropic`, lista modeli `GET /api/v1/agent/models`, test `POST /api/v1/agent/test`, wybór modelu.
- „Zakończ konfigurację” przy pierwszym uruchomieniu, z identyczną logiką.
- **Usuń z UI** sekcję „Animacje / tło / GIF żaby” (`ThemeDialog`, `appearance`): dotyczy starego wyglądu, którego już nie ma. Przy endpointach `/api/v1/appearance/*` zapisz w raporcie, że nie są używane. **Nie usuwaj ich z backendu.**

### 3.2 TRYB PRACY (`ModeDialog`)
- Tryb wykonania: `POST /api/v1/mode` z `{ mode, confirm }` i tym samym potwierdzeniem tekstowym dla AUTO_LIVE co dziś.
- Tryb strategii: `POST /api/v1/strategy/mode` (AUTO / MANUAL + wybór).
- Tryb ML: `POST /api/v1/ml/mode`.
- Ścieżka główna: `POST /api/v1/mode/primary-path`.
- Opisy trybów i ostrzeżenia **słowo w słowo** z `ModeDialog`.

### 3.3 STOP (`PowerDialog`)
- „Nie zamyka pozycji. Wyłącza AUTO TRADING.”: `POST /api/v1/kill` `{ on, reason: "user_stop_button" | "user_resume" }`.
- Zamknij pozycje bota: `POST /api/v1/positions/close` `{ scope: "BOT", confirm }`, z tym samym potwierdzeniem.
- Zatrzymaj PepeMarketWizard: `POST /api/v1/admin/shutdown`.
- Kolejność i teksty jak w `PowerDialog`.

### 3.4 DIAGNOSTYKA (`DiagnosticsPage`)
- `GET /api/v1/analytics/diagnostics`, `GET /api/v1/timeframes`, `GET /api/v1/health` i pozostałe źródła, z których korzysta dziś `DiagnosticsPage`. Pełna lista w raporcie E0.
- Treść w formie listy kontroli. Kolory stanów jak w S3 §0. Bez wykresów, których nie było.

## 4. Testy (dodaj w E8)
- Każdy panel otwiera się z menu i z ekranu FOREX, a ESC zamyka.
- `data-testid` zachowane tam, gdzie testy ich używają: `stop-button`, `chip-exec`, `chip-mode`. Nowe: `system-settings`, `system-mode`, `system-stop`, `system-diagnostics`.
- Test sieci: otwarcie paneli wysyła tylko GET. POST idzie wyłącznie po kliknięciu i potwierdzeniu, z identycznym ciałem żądania jak 1.41.0 (porównaj z testami, które to dziś sprawdzają, np. `test_ui_pages.py`).

## 5. Okno startowe Windows (`desktop/splash.html`)
- Nowy wygląd:
  - czarna głębia, napis „PEPEMARKETWIZARD TEAM” i motto (typografia z REF_A);
  - linie postępu startu silnika;
  - wybór danych (faza `choose`) i błąd (faza `error`) bez zmian funkcji;
  - przycisk **WEJDŹ** zamiast „JOIN THE CULT”.
- **Protokół z Go bez zmian:** akcja `join`, fazy `progress | choose | error | ready`, pola `splashState`. Zmieniasz tylko HTML/CSS i teksty.
- Gdyby test Go sprawdzał tekst „JOIN THE CULT”, zaktualizuj test i komentarze w `app_windows.go` (bez zmiany logiki).
- Przebudowa: `python tools/build_desktop.py` (Go ≥ 1.23, kompilacja krzyżowa `GOOS=windows`, testy Go i `go vet` uruchamia sam skrypt).
