# E7 – Panele systemowe w nowym stylu (Ustawienia · Tryb pracy · STOP · Diagnostyka)

**Spec:** `spec/S6_PANELE_SYSTEMOWE.md`. **Musi być gotowe przed E8**, bo E8 usuwa stare dialogi i strony.

## Zakres
1. `frontend/src/features/system/`:
   - `SystemDrawer.tsx`: szuflada z zakładkami;
   - `SettingsPanel.tsx`, `ModePanel.tsx`, `StopPanel.tsx`, `DiagnosticsPanel.tsx`;
   - `ExecStatus.tsx`: wskaźnik stanu wykonania w prawym górnym rogu;
   - `system.css`.
2. Logikę przenieś **1:1** z `components/Dialogs.tsx` (`SettingsModal`, `ModeDialog`, `PowerDialog`) i `pages/AnalyticsPages.tsx` (`DiagnosticsPage`):
   - te same wywołania, potwierdzenia, teksty, kolejność;
   - funkcje pomocnicze przenieś do `frontend/src/core/` i importuj z obu miejsc, dopóki E8 nie usunie starych plików.
3. Ikony dostępu w menu (`#tools`) i na ekranach FOREX (prawy dół), wskaźnik stanu na każdym ekranie, trasa `#/system?p=…`.
4. Pierwsze uruchomienie: po intro automatycznie panel Ustawienia (jak dziś `setSettings(true)` przy `first_run_completed === false`).
5. Sekcji wyglądu (animacje tła, GIF żaby) nie przenosisz (S6 §3.1).

## Kryteria odbioru E7
- Na zrzucie widać szufladę każdej zakładki nad ekranem FOREX i nad menu, w stylu nowego UI.
- Test sieci: dla każdej akcji (zapis konfiguracji, połączenie MT5, zmiana trybu z potwierdzeniem, STOP on/off, zamknięcie pozycji bota, wyłączenie aplikacji – **to ostatnie tylko w trybie syntetycznym/testowym**) ciało żądania jest identyczne jak w 1.41.0.
- STOP osiągalny jednym kliknięciem z każdego ekranu.
- `data-testid`: `stop-button`, `chip-exec`, `chip-mode` zachowane.
