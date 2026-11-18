# K5 – Session Volume Profile (profil każdej sesji)

**Wzorzec (`charts.js`):** `SVP_BINS`, `svpBinTicks`, `svpProfile`, `svpRecalc`, `svpVisible`, rysowanie profili w `drawBotLayers`, zakładka VOLUME PROFILE w `renderOpts` (zestaw sesji, sesje, siatka, Value Area, tabela ostatnich profili). Port: `referencje/kod/svp_port_pmw_svp_1.js`.
**Zrzut:** `S04c_charts_session_volume_profile.png`.

## Zakres

1. Osobny profil **każdej sesji** z zestawu `LAB_XAU_REFERENCE_V1` / `LAB_BTC_REFERENCE_V1` / `SCALP_OPENING_V1` (AUTO według instrumentu). Sesje w strefach IANA z czasem letnim. Sesja bieżąca: „W TOKU”, liczona tylko z zamkniętych świec.
2. **ZAŁOŻENIE:** profile sesji liczy frontend portem `svp_port_pmw_svp_1.js` (1:1 z `svp/engine.py` + `zones/dsvie.py`) na świecach z API. Port kopiujesz do `screens/charts/svpPort.(js|ts)` z tymi samymi eksportami: `svpCompute`, `svpWindows`, `SVP_PROFILES`.
   - DO WERYFIKACJI (z K0): jeśli backend ma GET liczący profil nazwanej sesji bez zapisu, użyj backendu i opisz to w raporcie (test zgodności nadal obowiązuje dla portu, jeśli zostaje w kodzie).
   - **Zakaz automatycznego `POST /api/v1/svp/profiles`** (tworzy zapisany profil użytkownika).
3. Profil widocznego zakresu: `GET /api/v1/svp/visible` (PMW-SVP-1 VISIBLE).
4. Ustawienia 1:1: zestaw sesji, włączanie pojedynczych sesji, siatka w tickach (XAU 10–200, BTC 500–5000), Value Area 60/70/80 %, POC / VA / HVN / LVN, tabela ostatnich profili (sesja, stan, POC, VAH, VAL, świece).
5. Źródło wolumenu: `TICK_VOLUME` dla MT5 (aktywność brokera, nie wolumen transakcyjny) – etykieta jak we wzorcu.
6. Profile tylko na TF ≤ H1; wyżej komunikat. „Boksy sesji” i „POC / VAH / VAL poprzedniej sesji” korzystają z tych samych profili.

## Test zgodności (obowiązkowy)

```
python update_charts/narzedzia/svp_zgodnosc/make_fixture.py
node   update_charts/narzedzia/svp_zgodnosc/test_svp_port.mjs <ścieżka portu w frontend>
```
Wynik 27/27. Dodaj oba polecenia do `tools/run_tests.py` (lub odpowiednika), aby test szedł przy każdym uruchomieniu testów.

## Kryteria K5
- [ ] Test zgodności SVP 27/27 na porcie z aplikacji.
- [ ] Scenariusz 1:1 `K3_xau_m5_svp` przechodzi.
- [ ] W zakładce sieć brak `POST /api/v1/svp/profiles`.
