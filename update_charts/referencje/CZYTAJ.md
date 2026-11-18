# Referencje

- `REF_B_kula_forex_i_ekrany.html` – działająca wizualizacja (Chrome / Edge, offline). Kliknij kulę FOREX, potem planetę 01 CHARTS. **Wszystkie liczby to DEMO** (sygnały, strefy i profile policzone kodem bota 1.41.0 na świecach podglądu). Plik ma haki testu 1:1: `PMW_PREVIEW._chartsDump()` i `PMW_PREVIEW._chartsLoad(fixture)`.
- `kod/charts_wzorzec/` – wycinek wzorca ekranu CHARTS do przeniesienia 1:1:
  - `charts.html` – znaczniki (REF_B linie 456–483);
  - `charts.css` – wygląd (linie 9–14, 35, 89–166);
  - `charts.js` – logika i rysowanie (linie 947–1386, dane DEMO `BOTDATA` usunięte z wycinka).
- `kod/svp_port_pmw_svp_1.js` – port Session Volume Profile 1:1 z `svp/engine.py` + `zones/dsvie.py`.
- `zrzuty/` – obraz docelowy (1600×900): `S03` ekran FOREX, `S04` CHARTS M5, `S04b` zakładka STRATEGIE, `S04c` Session Volume Profile, `S04d` H1 bez stref, `S04e` M15 z planem bota.
- Dodatkowe 8 zrzutów wzorcowych testu: `narzedzia/charts_1do1/wzorce/`.
