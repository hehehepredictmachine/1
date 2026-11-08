# PMW Quant Core – wycofanie zmian i lista zmienionych plików (1.35.0)

## Poziomy wycofania (od najlżejszego)

1. **Wyłączenie wpływu**: `python -m masterquo quant mode SHADOW --instrument XAUUSD`. Z ASSIST wraca do obserwacji. Koordynator czyta rodziny jak w 1.34.
2. **Wyłączenie Quant Core**: `python -m masterquo quant mode OFF --instrument XAUUSD`. Brak cyklu, ledgera i ocen. Decyzje jak w 1.34.
   Pozostają dwie poprawki w istniejących modułach: odrzucenie czasu z przyszłości i Wilson. Obie tylko zaostrzają.
3. **Rollback artefaktu meta-modelu**: `python -m masterquo quant rollback --instrument XAUUSD --task <task_hash>` albo przycisk „rollback” w Centrum treningu.
   Przywraca poprzednią aktywną wersję, a gdy jej nie ma, usuwa aktywny wpis zadania.
4. **Usunięcie danych Quant**: zatrzymaj bota i usuń `<dane>\quant\`. Następny start utworzy pusty ledger w SHADOW. Baza `masterquo.db` nie była zmieniana.
5. **Powrót do 1.34.2**:
   - zatrzymaj bota;
   - rozpakuj paczkę `PepeMarketWizard_DESKTOP_1_34_2.zip` (albo folder 1.34.2) w miejsce programu, **bez** nadpisywania folderu `data`;
   - uruchom.

   Folder `<dane>\quant\` nie jest czytany przez 1.34 i można go zostawić.

## Migracje

- Brak migracji bazy SQLite i brak zmiany wersji `config.json`.
- Nowe pliki są addytywne, w `<dane>\quant\`: `settings.json`, `ledger.sqlite`, `snapshot.json`, `models\…`, `jobs\…`.
- `settings.json` powstaje dopiero przy pierwszej zmianie trybu. Do tego czasu obowiązuje domyślny SHADOW.
- Dane i ustawienia użytkownika 1.34 nie są nadpisywane.

## Zmienione pliki

Nowe:
- `backend/masterquo/quant/` (`__init__`, `ids`, `inventory`, `numeric`, `units`, `events`, `snapshot`, `checks`, `scheduler`, `adapters`, `features`, `metamodel`, `ledger`, `service`, `cli`)
- `frontend/src/features/pmw133/QuantSection.tsx`
- `tests/test_quant_core.py`, `tests/test_ui_quant.py`
- `docs/quant/*`
- `37_QUANT_CORE.bat`

Zmienione:

| Plik | Zakres |
|---|---|
| `backend/masterquo/decision/coordinator.py` | czas z przyszłości, identyfikator kanoniczny, wpis Quant w ASSIST, `MODEL_QUANT_HOLD` |
| `backend/masterquo/sh/service.py` | `MODEL_QUANT_HOLD` jak REQUIRED (READY → WAIT) |
| `backend/masterquo/evaluation/engine.py` | PMW-EVAL-ENGINE-2 (bez Wilsona jako niepewności p(x)) |
| `backend/masterquo/evaluation/service.py` | `listeners` |
| `backend/masterquo/modelhub/families/service.py` | `SEQ_GRU_EVENT` czyta wynik Event GRU z Quant |
| `backend/masterquo/runtime.py` | `QuantService` |
| `backend/masterquo/api/app.py` | `/api/v1/quant/*` |
| `backend/masterquo/__main__.py` | `quant` |
| `frontend/src/features/pmw133/DecisionPage.tsx`, `frontend/src/features/training-center/TrainingCenterPage.tsx` | osadzenie sekcji |
| `tests/test_evaluation.py` | oczekiwania PMW-EVAL-ENGINE-2 |
| `frontend/dist/*` | przebudowa |
| `backend/masterquo/version.py`, `tools/build_release.py`, `tools/make_manuals.py`, `desktop/winres` | wersja 1.35.0 |
