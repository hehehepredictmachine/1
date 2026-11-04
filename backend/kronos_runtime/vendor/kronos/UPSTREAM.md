# Kronos – kod modelu dołączony do PepeMarketWizard

Źródło: archiwum `Kronos-master.zip` przekazane przez użytkownika (repozytorium https://github.com/shiyu-coder/Kronos, gałąź master).
Licencja: MIT, Copyright (c) 2025 ShiYu – pełny tekst w `LICENSE` obok (wymagany przez licencję przy każdej kopii).

SHA-256 archiwum: `92fc55519ddc46f22e0c8ac10a37cde73d6346818f4b8aa10f0e54c9f8a620ff` (9 451 071 B).

| Plik | Oryginał (`model/…`) SHA-256 | Tutaj SHA-256 | Zmiana |
|---|---|---|---|
| `kronos.py` | `0a5f90282e2039c2de0771473419715c845def154896dbd0f5747837e6241032` | `a6c4588b5af8ec138693f0bfa978971f1588c160a45f25bf7c67b4f6762e834d` | tylko import: `sys.path.append("../")` + `from model.module import *` → `from .module import *` (pakiet `kronos_runtime.vendor.kronos` zamiast ogólnej nazwy `model`, która kolidowałaby z modułami bota) |
| `module.py` | `a07edbadc0e96804c8158c021bbc6063bb7cc43b34d7fc470d5c8ff2005a409f` | to samo | bez zmian |
| `__init__.py` | `f8f856ca3fedadcaac97e196be23d1aeda1c3c9ffe8903d66d43ea3bcac6240c` | to samo | bez zmian |
| `LICENSE` | `acb2d194d378204e5f2be4dcd24d39ecac437903620c790c3315a96dab388fdc` | to samo | bez zmian |

Dane testu regresji z `tests/data/` (plik wejściowy i oczekiwane wyjścia dla kontekstu 256 / 512) leżą w
`backend/kronos_runtime/tests_data/` bez zmian – używa ich przycisk „Sprawdź instalację” (porównanie z wynikiem referencyjnym autorów).

Wagi NIE są częścią archiwum ani paczki bota. Instalator pobiera je z Hugging Face (`NeoQuasar/Kronos-small`,
`NeoQuasar/Kronos-Tokenizer-base`) w przypiętych rewizjach z `kronos_runtime/lock.py` i sprawdza sumy z metadanymi źródła.
Logika predykcji (`KronosPredictor`, `auto_regressive_inference`) nie jest zmieniana: bot wywołuje oryginalne funkcje.
