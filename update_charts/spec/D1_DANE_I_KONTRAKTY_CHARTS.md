# D1 – Dane i kontrakty ekranu CHARTS

Zasada nadrzędna: **wzorzec pokazuje wygląd i ruch, nie liczby.** Każda wartość pochodzi z API bota przez `apiGet` (`frontend/src/api.ts`) i zdarzenia ze `store.tsx` (jeden WebSocket).
Endpointy oznaczone POTWIERDZONE istnieją w `backend/masterquo/api/app.py` (1.41.0). Pole, którego widok potrzebuje, a którego nie ma w odpowiedzi → **zgłoś** i pokaż stan pusty. Nie wyliczaj go w UI z innych danych bez zgody użytkownika.

## 0. Stany wspólne

| Stan | Kiedy | Wygląd |
|---|---|---|
| `BRAK DANYCH` | pusta lista / `status: NO_DATA` / brak pola | szary tekst, bez liczby, bez wykresu zastępczego |
| `NIEWYTRENOWANY` | stan modelu `NOT_TRAINED` | „—” + stan w wierszu szans |
| `UNCALIBRATED` | `calibration.status` inny niż `CALIBRATED_*` | bez procentu; „score” / „niekalibrowany” |
| `SYNTETYCZNE` | dane syntetyczne (`s.synthetic`) | `.demo-tag` w nagłówku z tekstem „SYNTETYCZNE” |
| `BŁĄD` | wyjątek HTTP / `state: ERROR` | czerwony tekst z `reason`, „Odśwież” |

Liczby: format jak `fmtP` (miejsca po przecinku instrumentu), czas jak `fmtT` z wybraną strefą (LOKALNY / UTC / SERWER).

## 1. Elementy ekranu → źródła (POTWIERDZONE)

| Element | Źródło | Uwagi |
|---|---|---|
| Lista TF | `GET /api/v1/timeframes` | nie koduj listy na sztywno |
| Świece | `GET /api/v1/candles?tf=` + `store.barTick[tf]`, `bar_closed` | symbol silnika `mt5.symbol`; BTC przy innym symbolu: `GET /api/v1/market-zones/bars?instrument=BTC&tf=` (`NO_SYMBOL` → stan pusty) – DO WERYFIKACJI w K0 |
| BID / ASK / SPREAD | store `quote` | |
| Status MT5 | store (`s.ws`, połączenie silnika) | `live / loading / offline / stale` |
| Wskaźniki | pola w `candles` lub obliczenia projektu (WtcTower / chartlab) | wzory wzorca tylko do kontroli zgodności (K2) |
| Kronos | `GET /api/v1/kronos`, `GET /api/v1/kronos/forecast?instrument=&tf=` | TF M1/M5/M15/M30/H1; inne → `TIMEFRAME_NOT_ALLOWED` |
| Katalog koszyków | `GET /api/v1/baskets/catalog` | nazwa, TF sygnału, reguły, `plan_type`, `tp_r` |
| Sygnały koszyków | `GET /api/v1/baskets/signals?basket=&limit=` | filtr instrumentu i TF w UI |
| Sygnały S01–S12 | `GET /api/v1/bot-signals?symbol=&limit=` (+ `/api/v1/setups`) | tylko XAUUSD; BTC → `UNSUPPORTED_ASSET` |
| Sygnały SH | `GET /api/v1/sh/signals?strategy=&tf=&symbol=&limit=` | TP1–TP3; BTC → stan z konfiguracji SH |
| Plan bota (gdy potrzebny) | `GET /api/v1/plans/chart`, `GET /api/v1/sh/chart` | wejście / SL / TP / RR jak zwraca backend |
| Strefy | `GET /api/v1/market-zones?instrument=` → `timeframes[tf]` | tylko wybrany TF; strefy istnieją dla M1–M30 |
| Profil widocznego zakresu | `GET /api/v1/svp/visible` | PMW-SVP-1 VISIBLE |
| Profile sesji | port `svpPort` na świecach z API | ZAŁOŻENIE (K5); zakaz automatycznego `POST /api/v1/svp/profiles` |
| Szanse modeli w karcie | `GET /api/v1/models/predictions?instrument=` (PMW-PRED-1) | % tylko `unit=probability` + `CALIBRATED_*` |

## 2. Odświeżanie
Świece na żywo ze store. Sygnały, strefy, profile, plan, szanse – po `bar_closed` wybranego TF. Polling najwyżej co 5 s. Tylko GET.

## 3. Model widoku (= struktury czytane przez kod wzorca)

Adaptery `toViewModel()` w `chartsData.ts` zamieniają odpowiedzi API na poniższe struktury. **Ten sam kształt mają fixtures testu 1:1** (`narzedzia/charts_1do1/fixtures/*.json`) – tryb testowy wczytuje je bez API.

### 3.1 Świeca (`candles[]`, `CH.data`)
`{ t: ms UTC otwarcia, o, h, l, c, v: tick volume, closed: bool }`

### 3.2 Sygnał (`signals[]`)
| Pole | Znaczenie | `BASKET` | `LEGACY` | `SH` |
|---|---|---|---|---|
| `sid` | id strategii (`FX_SMC_01`, `S03`, `SH_SCALPING`) | ✓ | ✓ | ✓ |
| `src` | `BASKET` / `LEGACY` / `SH` | ✓ | ✓ | ✓ |
| `tf` | TF sygnału | ✓ | ✓ | `M1` |
| `t` | ms czasu świecy sygnału | ✓ | ✓ | ✓ |
| `sd` | kierunek: 1 LONG, −1 SHORT | ✓ | ✓ | ✓ |
| `e`, `sl` | wejście, stop | ✓ | ✓ | ✓ |
| `tp[]` | cele w kolejności (długość = liczba celów w kontrakcie) | 2 | 1–2 | 3 |
| `inv` | unieważnienie | ✓ | ✓ | – |
| `res` | wynik / stan z API: `OTWARTY`, `TP1..TP3`, `SL`, `SL_PO_TP1/2`, `TIMEOUT`, `TIMEOUT_PO_TP1/2` | ✓ | ✓ | ✓ |
| `hit[]` | osiągnięte cele według API | ✓ | ✓ | ✓ |
| `et` | ms końca (wynik / wygaśnięcie) | ✓ | ✓ | ✓ |
| `rg`, `ro` | reżim przy sygnale; czy w routingu AUTO | ✓ | `rg` | – |
| `ev`, `tb`, `to` | zdarzenie reguły, typ celów (`STRUKTURA` / R), timeout w świecach | ✓ | `tb` | – |
| `sc`, `why[]`, `miss[]`, `trg` | wynik setupu 0–100 (heurystyka), powody, braki, trigger | – | ✓ | – |
| `sh[]`, `rr`, `be`, `hz` | udziały celów, RR netto, BE po, horyzont min | – | – | ✓ |

`res`/`hit`/`et` **wyłącznie** ze stanu w API. Brak → `res` = stan cyklu życia z API, `hit` = `[]`.

### 3.3 Stany strategii (`states[sid]`)
`{ st: { <stan>: liczba ocen }, un: null | "powód niedostępności z API" }`

### 3.4 Meta strategii (`meta[koszyk][]`, `SMETA`)
- koszyki `FX_*`: `id, nm, tf, ctx[], fam, grp, kind, need, plan, setup, trig, cancel, exit, tp_r[]` – z `baskets/catalog`;
- `LEGACY` (S01–S12): `id, nm, fam, tfs[], val, notrade, funnel{}` – z opisu strategii (`registry.describe()`);
- `SH`: `id, nm, tp_usd[], shares[], be, sl_usd[], hz, pos_max, regimes[], status{instrument: tekst}, counts{}` – z konfiguracji `sh`.

### 3.5 Strefa (`zones[tf][]`)
`{ ty: FVG_BULL|FVG_BEAR|OB_BULL|OB_BEAR|DEMAND|SUPPLY|SR_SUPPORT|SR_RESISTANCE|EQH|EQL, lo, up, st: PRELIMINARY|ACTIVE|TESTED|INVALIDATED|EXPIRED, t0, t1|null, q: jakość (heurystyka), why, v: 1 = wybrana przez silnik }`

### 3.6 Kronos (`kronos`)
`{ tf, mode, on{tf:bool}, onChart, state, candles[], forecast: { pred[] (świece prognozy), paths[][] (ścieżki niepewności), last_close, pred_close_h, delta, delta_pct, direction: UP|DOWN|FLAT, neutral_band, horizon, created_at (ms), is_current, atr } }`
Brak `paths` w API → brak wachlarza + komunikat (bez symulacji).

### 3.7 Szanse modeli (`probs`)
Klucze używane przez kartę: `win`, `tp2` (pozostałe – `scB`, `quant`, `mc`, `dir` – w zakładce PLAN · MODELE, jeśli wzorzec je pokazuje). Każdy: `{ name, task, v (0–1 albo null), state, cal, src }`.

### 3.8 Ustawienia widoku
`L` (włączniki warstw – nazwy jak we wzorcu), `str: { on[], sel, open{} }`, `tab`, `view`, `offset`, `cardMin`, `tz`, `serverOff`, `quote: { bid, ask, spread }`.
Tylko pole `test_texts` istnieje wyłącznie w fixtures (teksty pochodzenia danych w trybie testowym).
