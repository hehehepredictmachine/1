# Postęp IND – wskaźniki, DXY, plany, SVP (1.33.0)

| Wymaganie | Stan | Moduł | Runtime / odbiorcy | Testy |
|---|---|---|---|---|
| Kontrakt PMW-IND-1 | wykonane | `indicators/contract.py` | IndicatorService | `test_indicators_u2` |
| AVWAP sesja/zdarzenie/ręczna + wersje kotwic | wykonane | `indicators/avwap.py` | kontekst ACTIVE, SH OBSERVE, wykres | `test_indicators_u2`, `test_ui_pmw133` |
| Spread vs sesja (stały zegar, percentyl) | wykonane | `indicators/spread.py` | kontekst, panel | `test_indicators_u2` |
| Semiwariancja | wykonane | `indicators/semivar.py` | kontekst, panel | `test_indicators_u2` |
| XAUUSD × DXY bez forward-fill | wykonane | `indicators/dxy.py` | kontekst, agent, panel `#/dxy` | `test_indicators_u2`, `test_ui_pmw133` |
| OFI / arkusz MT5 + archiwum | wykonane | `indicators/ofi.py`, `mt5/fake.py` | MICROSTRUCTURE, panel | `test_indicators_u2`, `test_families_u4` |
| Profil sesji + RVOL z kontrolą historii | wykonane | `indicators/profile.py`, `zones/dsvie.py` | kontekst, strefy | `test_indicators_u2`, `test_zones` |
| Pepe Scalp / Hedge Plan | wykonane | `plans/` | panel (warstwy) | `test_plans_svp_u3`, `test_ui_pmw133` |
| SVP profile + strefy + AI | wykonane | `svp/` | panel `#/svp`, warstwa SVP, agent | `test_plans_svp_u3`, `test_ui_pmw133` |
| Narzędzia agenta | wykonane | `agent/tools.py` | agent | `test_indicators_u2` |
| Panel DXY / SVP / warstwy | wykonane | `features/pmw133/*` | panel | `test_ui_pmw133` 3 OK + regresja UI 23 plików OK |

Ograniczenia środowiska testowego:
* brak terminala MT5 – arkusz, spread i DXY pochodzą z symulatora (dane SYNTETYCZNE);
* w weekend symulator nie ma ticków, więc bez zapisanego przesunięcia zegara serwera świece nie mają czasu UTC, a wskaźniki pokazują
  WARMUP / NO_DATA zgodnie z projektem.
