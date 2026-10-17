# Raport zmian i testów – instalatory treningu XAUUSD / BTC (PepeMarketWizard 1.15.0, 2026-10-17)

## Co zostało ZROBIONE (w kodzie, z testami)
| Wymaganie | Realizacja |
|---|---|
| Wspólny pipeline, cienkie BAT-y | `backend/masterquo/training/{core,runner,report,cli}.py`; `tools/trening.cmd` + 6 launcherów; `22_TRENUJ_WSZYSTKIE_MODELE.bat` → ten sam mechanizm (zgodność argumentów: prowizja = XAUUSD) |
| Ścieżki ze spacjami/Unicode/`!` | BAT bez delayed expansion, ścieżki w cudzysłowach; test e2e w katalogu `dane treningu ąę !x` |
| Python 3.12/3.13 x64, izolacja `.venv`/`.venv_candles`, blokady z hashami | `INSTALUJ_TRENING.bat` wywołuje istniejące instalatory tylko przy braku środowiska; `training install` porównuje wersje z `requirements/*.txt` (hashy nie wymyślano) |
| Instrumenty, USD≠USDT, bez podmian | `config/instruments_v1.json`, `backend/mq_instruments.py` (metadane, kandydaci, odrzucenie WBTC/PAXG/XAUT, ostrzeżenie dla `BTSUSDT-`) |
| Eksport per instrument | `forecast/export.py` (instrument + dokładny symbol, M1–D1, porcje z checkpointem, metadane, SHA256, jakość, prowizja z historii transakcji, blokada funkcji zleceń) |
| Cały łańcuch dla BTC | gold_candles (profil grid 500, rejestr `data/instruments/BTC/forecast`), scalp A/B/C (profil BTC, rejestr osobny), legacy ML (osobna baza + router, backfill z symbolem BTC), lab |
| Bot per aktywne aktywo | ForecastService/ScalpService/MLRouter przełączają model/profil/rejestr; kolumna `instrument` w SHADOW (migracja 0015) |
| Lab: ten sam model oceniany i zapisany | artefakt = fit na danych rozwojowych (obiekt z holdoutu dla kandydata); brak refitu na train+holdout; `side`, `fit_scope`, kompletność rodzin, parity loadera, wskaźnik ACTIVE + rollback per rodzina |
| Prognozy: parity loadera | porównanie prawdopodobieństw loadera bota z pipeline'em treningowym na tych samych rekordach + odrzucenie innego kontraktu |
| Bez automatycznej promocji odrzuconych | prognozy/scalp aktywowane tylko przy walidacji SHADOW; lab „research” nie zastępuje „shadow”; ML z APPROX = RESEARCH_APPROX |
| APPROX nie trwale | `use_backfill_approx` nie jest zapisywany; parametr per zadanie (`/ml/train` body, `ml-offline`) |
| Statusy 3-osiowe, kody wyjścia, wznawianie, anulowanie, blokada drugiego runu | `training/core.py` (opis kodów 0–4) |
| Raport HTML/JSON | `data/training/runs/<run>/report.{html,json}`, zdanie podsumowania z liczb runu |
| Panel | Modele i trening → karta „Trening XAUUSD / BTC” (start, postęp, anuluj, wynik, aktywne modele, rollback) – `/api/v1/training*` |
| Przeniesienie folderu projektu | rejestry prognoz/scalp/ML odnajdują artefakty pod nowym katalogiem (sumy kontrolne nadal sprawdzane) |
| Dokumenty | `START_TUTAJ_TRENING_PL.md`, `MAPA_MODELI_I_TRENINGU.md/.json` (`tools/model_map.py`), `docs/schemas/*.schema.json`, profile `config/training_profiles_v1.json`, `MANIFEST_SHA256.txt`, CHANGELOG, RUNBOOK |

## Czego NIE zrobiono / nie dało się sprawdzić tutaj
- **Nie uruchomiono na Windows ani na Twoim MT5** (środowisko budowy to Linux bez terminala). Eksport, wykrywanie terminali i symboli, BAT-y oraz Tkinter nie były wykonane na Windows. BAT-y przeszły tylko kontrole statyczne (ASCII, CRLF, cudzysłowy). Kreator jest konsolowy, bez Tkinter.
- **Brak treningu na prawdziwych danych.** Nie ma więc żadnych wyników jakości, win rate ani „wytrenowanych modeli” w paczce. Wszystkie modele z testów są syntetyczne (TEST_TECHNICZNY) i nigdy nie są aktywowane.
- **Profil BTC dla prognoz i scalp to hipoteza:** grid 500 i reguły scalp skopiowane z XAUUSD, wszystkie progi względne. Nie był dostrajany.
- Kalendarz sesji brokera (weekend BTC) nie jest odczytywany z MT5. Jest wnioskowany z historii (luki w raporcie jakości).
- Twardy limit RAM na proces nie istnieje. Jest kontrola wolnej pamięci przed zadaniem, limity wątków i niższy priorytet.
- Lab trenuje tylko stronę LONG (domyślny protokół). Brak osobnego modelu SHORT.

## Testy (Linux, Python 3.13, symulator MT5, Chromium)
| Przebieg | Wynik |
|---|---|
| `tools/run_tests.py` – testy bota | 437 uruchomionych, 436 OK; 1 FAIL `test_ui_lab.test_01` spowodowany pozostawionym serwerem demo z przerwanego wcześniejszego przebiegu (ten sam port) – po jego zatrzymaniu `test_ui_lab` 5/5 OK |
| Testy `.venv_candles` (gold_candles + runtime + scalp) | 46/46 OK |
| Nowe `tests/test_train_all.py` | e2e XAUUSD+BTC (demo, ścieżka z Unicode/`!`), anulowanie + wznowienie, blokada drugiego runu, zgodność `train-all`, profile/metadane USD/USDT, brak zleceń w eksporcie, rollback lab, router ML (osobna baza, filtr symbolu, APPROX bez zapisu w config), konfiguracja gold_candles BTC, relokacja ścieżek – OK |
| Build frontendu (tsc + vite) | OK |
| pyflakes na zmienionych modułach | bez uwag |

Poprawki podczas testów:
- zapis manifestu lab gubił `sha256`, przez co artefakt był odrzucany;
- `ScalpService` w teście tworzonym przez `__new__` nie miał atrybutu `inst`;
- lista migracji w teście została uzupełniona o 0015.
