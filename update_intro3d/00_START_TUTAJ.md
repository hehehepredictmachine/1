# PepeMarketWizard – pakiet: nowa animacja startowa 3D

Claude Code wprowadzi nową animację startu bota (scena 3D w czasie rzeczywistym zamiast filmu):

> W galaktyce, z głębokiej czerni wyłaniają się trzy męskie postacie 3D w garniturach. Środkowa ma czerwoną kominiarkę. Idą w stronę widza, zatrzymują się w połowie drogi. Pojawiają się 3 małe planety (FOREX, CRYPTO, OTC), środkowa postać kładzie na nie dłoń – błysk i przejście do menu głównego.

| Folder / plik | Co zawiera |
|---|---|
| `01_PROMPT_INTRO_3D.md` | **prompt do wklejenia w Claude Code** |
| `etapy/I0…I5` | etapy pracy |
| `spec/SC1…SC3`, `spec/O1` | oś czasu, postacie i planety, integracja, kryteria odbioru |
| `referencje/REF_C_intro_3d_i_menu.html` | działająca wizualizacja (intro 3D + menu) – otwórz w Edge/Chrome |
| `referencje/kod/intro3d/` | kod źródłowy wzorca (three.js 0.187.0), bryła postaci i jej generator |
| `referencje/wzor_chodu_od_uzytkownika.gif` | Twój wzór chodu |
| `referencje/zrzuty/00_storyboard.png` | 9 klatek kluczowych (pełne klatki w `narzedzia/intro_1do1/wzorce/`) |
| `narzedzia/intro_1do1/` | test klatek 1:1 (aplikacja ↔ wzorzec) |
| `MANIFEST_SHA256.txt` | sumy kontrolne |

## Jak uruchomić
1. Kopia folderu bota albo commit.
2. Rozpakuj pakiet do głównego folderu bota jako **`update_intro3d/`**.
3. Claude Code w głównym folderze bota → wklej całą treść `update_intro3d/01_PROMPT_INTRO_3D.md`.
4. Etapy I0 → I5, po każdym raport i czekanie na „dalej”.

## Związek z innymi pakietami
- Pełny pakiet 1.42.0 w trakcie → ten pakiet zmienia jego etap E1 (intro 3D zamiast filmu).
- Nowy interfejs już wdrożony → podmiana filmu na miejscu.
- Stary interfejs 1.41.0 → Claude Code zapyta, co zrobić.

## Ważne
- **ZAŁOŻENIE:** animacja zastępuje film `intro.mp4` (film idzie do archiwum).
- Postacie to bryły ludzkie w garniturach wygenerowane w kodzie (bez kupionych modeli). PROPOZYCJA na później: profesjonalne modele `.glb` z riggiem.
- Animacja bez dźwięku; nie łączy się z rynkiem, nie składa zleceń.
