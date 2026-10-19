# Standard gotowości modułów (wymaganie użytkownika z 18.10.2026)

Każdy moduł ma być **pełny, gotowy do pracy i do szkolenia**: dane → obliczenia → konsument → runtime/DB/API/WS → panel i wiedza
agenta → testy → dokumentacja → Windows/rollback. Szkielet, odłączony adapter, demonstracja albo wpis w menu nie są wykonaniem.

Raport każdego modułu podaje **osobno**:

| Pole | Znaczenie |
|---|---|
| implementation_status | kod istnieje i jest podłączony (IMPLEMENTED) / sprawdzony testami (VERIFIED) |
| source_status | źródło danych działa (np. RECEIVING) albo dokładny brak (SOURCE_MISSING, BLOCKED_IDENTITY_REQUIRED…) |
| mapping_status | dla wskaźników zewnętrznych: mapping zatwierdzony po porównaniu liczb z wykresem |
| runtime_status | READY_RUNTIME tylko przy świeżych zgodnych danych i podłączonym odbiorcy |
| dataset_status | zbiór point-in-time gotowy albo BLOCKED_NO_DATA / BLOCKED_NO_ARCHIVE |
| training_status | TRAINING_PIPELINE_IMPLEMENTED / wykonany trening / NOT_APPLICABLE dla wskaźnika deterministycznego |
| validation_status | ocena poza próbą; brak przewagi = NO_VALIDATED_EDGE (poprawny wynik badania) |
| mode | OBSERVE / RESEARCH / SHADOW – nowe moduły nie wykonują zleceń |
| needs | konkretne braki |

Gotowość kodu, obecność źródła, gotowość treningu, wytrenowane wagi i dowód przewagi to **odrębne stany**. Brak źródła nigdy nie
jest raportowany jako READY ani zastępowany zerem. Rejestr postępu: `docs/updates/update_registry.json`.
