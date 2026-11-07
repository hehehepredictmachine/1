# Postęp STU – Pepe Data & Training Studio (1.33.0)

| Wymaganie | Stan | Moduł | Testy |
|---|---|---|---|
| Osobna aplikacja (proces, port, katalog) | wykonane | `studio/app.py`, `studio/settings.py`, `__main__.py studio` | `test_studio_u5`, `test_ui_pmw133` (uruchomienie z bota) |
| Blokada międzyprocesowa + wspólna blokada eksportu | wykonane | `studio/lock.py`, `marketdata/export.py` | `test_studio_u5`, `test_export_mt5` |
| Rejestr 72 zadań + MODEL_DATA_MATRIX.json | wykonane | `studio/registry.py`, `docs/MODEL_DATA_MATRIX.json` | `test_studio_u5` |
| Kolejka z trwałym stanem | wykonane | `studio/queue.py`, `studio/jobrun.py` | `test_studio_u5` |
| Paczka per zadanie, etapy atomowe, sumy | wykonane | `studio/package.py`, `studio/pipeline.py` | `test_studio_u5` |
| Test ładowania w czystym procesie | wykonane | `studio/verify.py` | `test_studio_u5` |
| Import do bota, rollback, inbox | wykonane | `studio/importer.py`, API bota, `runtime.py` | `test_studio_u5` |
| PepeTrainingStudio.exe | wykonane | `desktop/*.go`, `tools/build_desktop.py` | `go test ./...` (test trybu studio) |
| Przycisk Studio + stan w menu bota | wykonane | `features/pmw133/StudioButton.tsx`, `/api/v1/studio/status|launch` | `test_ui_pmw133` |
| Interfejs (6 obszarów) | wykonane | `frontend/studio.html`, `src/studio/main.tsx` | `test_studio_u5` |

Nie sprawdzono w tym środowisku:
* eksportu MT5_DIRECT z prawdziwego terminala (brak Windows i MT5) – adapter jest testowany na symulatorze;
* okna `PepeTrainingStudio.exe` w Windows – sprawdzone kompilacja krzyżowa, `go vet` i testy logiki trybu studio.
