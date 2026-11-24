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

## 1.46 – wersje cech Quant (`PMW-QUANT-FEAT-3`) a powrót do starszej wersji

Gałąź architektury 1.46 wersjonuje semantykę cech MetaModelu. Nowe wiersze ledgera i nowe modele mają `PMW-QUANT-FEAT-3`. Artefakty sprzed
1.46 (`PMW-QUANT-FEAT-1`) dostają wejście jak dotąd.

**Ledger.** 1.46 dodaje w miejscu kolumnę `rows.feature_version` (`ALTER TABLE`, addytywnie, żaden wiersz nie jest usuwany). Wiersze sprzed
1.46 mają w niej pustą wartość (= FEAT-1), nowe `PMW-QUANT-FEAT-3`. Starsza wersja programu otworzy ten plik i zignoruje kolumnę, ale jej
trening **nie filtruje wersji**. Nauczyłby więc model na mieszance wierszy, w których te same kolumny (`st:mm:kalman_cross:aligned`,
`ctx:dxy_*`, `ctx:regime=*` kandydata SH) znaczą co innego.

- Po cofnięciu **nie trenuj Quant** (`quant train`, Centrum treningu) na ledgerze, który zawiera wiersze `PMW-QUANT-FEAT-3`.
- Jeśli trening w starszej wersji jest potrzebny:
  1. zatrzymaj bota i zachowaj kopię `<dane>\quant\ledger.sqlite` (np. `ledger.feat3.bak.sqlite`) – przy powrocie do 1.46 przywróć ją;
  2. sprawdź liczby wierszy: `SELECT COALESCE(feature_version, 'PMW-QUANT-FEAT-1') v, COUNT(*) FROM rows GROUP BY v;`
  3. w pliku, którego używa starsza wersja, odfiltruj wiersze nowej semantyki:
     `DELETE FROM rows WHERE feature_version = 'PMW-QUANT-FEAT-3';`

**MetaModele.** Starsza wersja odrzuci artefakt FEAT-3 przy wczytaniu (`INCOMPATIBLE_FEATURE_SCHEMA`). Quant ASSIST bez wczytanego modelu
**nie wstrzymuje wejść** (fail-open). Przed powrotem, jeśli aktywny jest model FEAT-3:

- przywróć poprzedni artefakt FEAT-1: `python -m masterquo quant rollback --instrument XAUUSD --task <task_hash>`, albo
- przełącz Quant na obserwację: `python -m masterquo quant mode SHADOW --instrument XAUUSD`.

**Aktywacja pierwszego modelu FEAT-3 (w 1.46).** Odpowiedź `POST /api/v1/quant/models/activate` i `quant activate` podaje
`feature_semantics` (wersja cech i opis). W Quant ASSIST zbiór HOLD zmienia się wtedy w obie strony, bo to inny model na innych cechach.
Sam reżim w kandydacie SH tylko zaostrza: model FEAT-3 jest oceniany z reżimem i bez niego, HOLD, gdy wstrzymuje którakolwiek ocena.
Cofnięcie aktywacji: rollback jak wyżej.

**QFENCE (1.46 arch, fala 2b).** Artefakt bez `producer_semantics = PMW-QUANT-PRODUCERS-2` w manifeście (każdy wytrenowany przed
poprawkami producentów, także FEAT-3 z fali 1) w aktywnym Quant ASSIST wstrzymuje każde nowe wejście SH i ACTIVE
(`MODEL_QUANT_HOLD`, powód `QUANT_REVALIDATION_REQUIRED`); w SHADOW działa jak dotąd. Rollback do takiego artefaktu przywraca to
wstrzymanie (fail-closed, nie fail-open). Zdjęcie bez retreningu: `quant mode SHADOW`. Nowe modele trenują się per grupa zadania
(`task_group`, klucz `G…`) – rollback / aktywacja podaje ten klucz w `--task`.
Wstrzymanie trwa, dopóki choć jeden aktywny zwalidowany artefakt ma starą semantykę. Nowy model grupy (`G…`) NIE zastępuje starych
artefaktów zapisanych pod `task_hash` – zostają w `ACTIVE.json`. Wyjście z QFENCE bez przechodzenia na SHADOW:
1. `quant train --instrument XAUUSD`, potem `quant activate --instrument XAUUSD --task <G…> --version <wersja>`;
2. dla każdego klucza z listy `revalidation_required` (`quant status` / `quant list`):
   `quant rollback --instrument XAUUSD --task <task_hash>` – powtarzać, aż klucz zniknie z `active` (rollback przywraca poprzednią
   wersję z historii, a ta też jest sprzed QFENCE);
3. `quant status`: `revalidation_required` puste.
Kolejność ma znaczenie: zdjęcie starych kluczy przed aktywacją nowego modelu zostawia ASSIST bez aktywnego modelu (Quant bez wpływu,
jak w SHADOW).

**Licznik wierszy.** Do czasu zebrania wierszy FEAT-3 (co najmniej DEV 300 + CAL 100 + TEST 100 na zadanie) trening odpowiada
INSUFFICIENT_EVIDENCE, a działa dotychczasowy artefakt FEAT-1. Stan: pole `training_evidence` w `GET /api/v1/quant/status` i
`python -m masterquo quant status`.
