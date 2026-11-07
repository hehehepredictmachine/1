# Pepe Data & Training Studio – 1.33.0 (specyfikacja STU)

Studio to **osobna aplikacja**: własny proces, port 8780 i katalog danych (`data_studio`). Studio **nigdy nie wysyła ani nie modyfikuje
zleceń**. Nie uruchamia Runtime bota i nie trzyma drugiego połączenia z MT5 obok bota.

## Uruchomienie
* **Z bota:** przycisk **Studio** w górnym pasku albo w menu CULT (pozycja „Training Studio”). Kropka ● znaczy, że Studio działa, a kliknięcie
  otwiera je. Gdy Studio nie działa, kliknięcie uruchamia je jako osobny proces:
  * w paczce DESKTOP: `PepeTrainingStudio.exe`;
  * w wersji folderowej: `python -m masterquo studio`.
* **Bez bota:** `PepeTrainingStudio.exe`, `36_STUDIO.bat` albo `python -m masterquo studio [--port N]`.

Studio czyta katalog danych bota tą samą regułą co bot (`MQ_BOT_DATA_DIR`, inaczej `default_data_dir`), nigdy „najnowszy folder”.

## Obszary
1. **Połączenia** – stan bota (port 8765), źródło danych, blokada eksportu.
2. **Modele** – rejestr **72 zadań** (`docs/MODEL_DATA_MATRIX.json`):

| Adapter | Zadania |
|---|---|
| TRAINHUB | 12 |
| FAMILY | 26 |
| RUNNER_GROUP | 26 |
| DETERMINISTIC | 6 |
| PRETRAINED | 2 |

   Stany: 62 SUPPORTED, 6 BLOCKED_DEPENDENCY (brak `.venv_deep`), 4 EXTERNAL.
3. **Eksport** – źródło danych:

| Źródło | Kiedy | Działanie |
|---|---|---|
| BOT_CACHE | bot działa | kopia tylko do odczytu z magazynu świec bota |
| MT5_DIRECT | bot nie działa | własny adapter tylko do odczytu, pełna historia od 2000-01-01 w porcjach |
| OFFLINE | – | wskazany magazyn |
| SYNTHETIC | – | symulator, paczki zawsze oznaczone |

4. **Walidacja i dataset** – walidacja surowych danych, budowa i walidacja datasetu.
5. **Trening** – trening / dopasowanie, ocena, test ładowania w **czystym procesie**.
6. **Kolejka i wyniki** – pauza, anulowanie, wznowienie, przesunięcie, przeniesienie do bota, raport.

## Paczka zadania
Jedno zadanie to jeden eksport i jedna paczka. Etapy:
`raw/export` → `validation/validate_raw` → `dataset/build_dataset` → `validation/validate_dataset` → `artifact/train` →
`evaluation/evaluate` → `evaluation/verify_loader`.

Każdy etap jest zatwierdzany atomowo (`.partial` → katalog końcowy) z sumami SHA-256. Trener dostaje dokładną ścieżkę datasetu.

## Blokady
* **PMW-LOCK-1:** plik blokady tworzony z `O_EXCL`, z właścicielem (pid, aplikacja, zadanie, host) i heartbeat. Blokadę martwego procesu lub
  ze starym heartbeat przejmuje się atomowo. Zwolnić ją może tylko właściciel.
* **Wspólna blokada eksportu** (`<dane bota>/locks/pmw_export.lock`) obejmuje każdą instancję Studio i eksport bota. Drugi eksport dostaje
  odmowę „eksport zajęty”.

## Przeniesienie do bota (PMW-STUDIO-IMPORT-1)
1. „Przenieś” wywołuje `POST /api/v1/studio/import`, gdy bot działa. Gdy bot nie działa, paczka trafia do skrzynki odbiorczej, którą bot
   przetwarza przy starcie.
2. Bot ponownie weryfikuje paczkę: sumy etapu artefaktu i pozytywny test ładowania.
3. Bot kopiuje ją jako **nową, nieaktywną wersję** do właściwego rejestru (trainhub albo rodziny). Nic nie wpływa na decyzje do czasu
   ręcznej aktywacji.
4. Historia: `GET /api/v1/studio/imports`. Rollback importu: `DELETE /api/v1/studio/import/{id}` (tylko wersja jeszcze nieaktywowana).
