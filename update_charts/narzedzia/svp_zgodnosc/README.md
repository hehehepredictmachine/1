# Zgodność Session Volume Profile (frontend ↔ silnik bota)

Port `referencje/kod/svp_port_pmw_svp_1.js` odtwarza 1:1 `backend/masterquo/svp/engine.py` + `zones/dsvie.py`:
- przypisanie do binów jak `float //` w CPython;
- sumy jak `sum()` w CPython ≥ 3.12 (kompensacja Neumaiera);
- okna sesji w strefach IANA przez `Intl`.

W podglądzie zgodność sprawdzono na 44 profilach (44/44 identyczne). W aplikacji ten test musi przechodzić w CI:

    python update_charts/narzedzia/svp_zgodnosc/make_fixture.py
    node   update_charts/narzedzia/svp_zgodnosc/test_svp_port.mjs <ścieżka portu w frontend, np. frontend/src/features/forex/screens/charts/svpPort.js>

Docelowy moduł TS/JS portu ma eksportować `svpCompute`, `svpWindows`, `SVP_PROFILES` z tą samą sygnaturą.
