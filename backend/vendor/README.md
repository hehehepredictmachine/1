# backend/vendor – silniki MasterQUO bez zmian
`legacy_core` (M02, M02I, M03, M07_M03E, PlanLock…), `mq_upgrades`, `m04n` – kopie 1:1 z oryginalnej paczki (bez plików .bat).
Hash każdego pliku: `VENDOR_MANIFEST.json`, kontrolowany testem `TestVendoredEnginesUnchanged`. Nie edytować – nowa logika jest w `backend/masterquo`.
Skrypty `RUN_MT5_*.py`, `M00U*.py` i viewery z tych katalogów nie są uruchamiane przez aplikację.
