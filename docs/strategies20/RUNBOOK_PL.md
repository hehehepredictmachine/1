# Pakiet 20 strategii XAUUSD – instrukcja (1.38)

## 1. Gdzie to jest w aplikacji

* **Strategie** (`#/strategie`) → panel **„Pakiet 20 strategii XAUUSD”**: tabela 20 wariantów (z backendu), filtr Scalp/Hedge, stan
  każdego wariantu na każdym TF sygnału (READY / WAIT / NO_TRADE / INVALIDATED / EXPIRED + kod powodu), polityka hedge, status walidacji.
  Kliknięcie `TF: stan` otwiera szczegóły: plan (Entry, SL, TP1, TP2 z odległością w USD i pipsach i udziałem), RR planu netto, RR koszyka
  (HG), status kosztów, warunek hedge i jego postęp, checklistę, wykres ze strzałką sygnału i historię sygnałów wariantu.
* **Wykresy** – przycisk warstwy **„Pakiet 20”** w pasku warstw (obok Scalp Plan / Hedge Plan / AVWAP / SVP): wybór Scalp/Hedge,
  konkretnej strategii, „hist.” (aktywne / historia) i „E/SL/TP”. Domyślnie rysowany jest wybrany plan i aktywne pozycje – nigdy 20
  kompletów linii. Strzałka BUY pod świecą / SELL nad świecą z etykietą `PMW_SC01 / M3` stoi na świecy, na której informacja była dostępna;
  WATCH/WAIT = neutralne kółko.
* **PEPE$SIGNAL** – sygnały SH mają tożsamość wariantu i TF (`PMW_HG03 / M15`), stare = `LEGACY_SCALPING` / `LEGACY_HEDGING`; poziomy
  z zapisanego planu sygnału; wykres sygnału na jego TF (M3 = 180 s, brak zastępczego M15).

## 2. Jak działa wykonanie

Pakiet liczy się analitycznie w każdym trybie (cykl SH po każdej zamkniętej M1, ciągły feed MT5 – niezależnie od tego, czy panel jest
otwarty). Zlecenia przechodzą wyłącznie istniejącą ścieżką: koordynator SH → silnik ryzyka → DecisionCoordinator → IntentLedger /
RiskBook → executor SH, w **bieżącym trybie** rachunku:

| Tryb | Pakiet |
|---|---|
| SIGNALS / SHADOW | tylko sygnały i plany – **zero zleceń** |
| PAPER | jawne symulowane fille (źródło „PAPER”) |
| AUTO_DEMO | jak legacy SH – wymaga znanej prowizji |
| AUTO_LIVE | dodatkowo raport wariantu **VALIDATED** na danych użytkownika – bez niego wejście jest odrzucane z powodem |

Bot nie przełącza trybu. STOP blokuje nowe wejścia i nowe hedge, nie blokuje wyjść ani rekonsyliacji. HG na rachunku NETTING – blokada
(REDUCE dla pakietu nie jest włączony).

## 3. Ustawienia

`config/sh_strategy_pack_v2.json` (domyślne) + nadpisania przez API `POST /api/v1/sh/strategies/config` (np.
`{"variants": {"PMW_SC05": {"enabled": false}}}` albo `{"variants": {"PMW_HG01": {"signal_tfs": ["M5"]}}}`). Walidacja odrzuca: ratio
> 0,50, TP1 / RR poniżej specyfikacji, inne niż dwa TP, TF niezaimplementowany dla wariantu. Każda zmiana zmienia hash wariantu; otwarte
plany zachowują zamrożony wariant. Historia nadpisań: `data/sh/pack_override.json`.

## 4. Walidacja na Twoich danych MT5

1. Eksport historii XAUUSD (centrum treningu albo `11_EKSPORT_HISTORII_XAUUSD.bat`) – najlepiej ≥ 6 miesięcy M1 (H1 wymaga 1000
   zamkniętych świec rozgrzewki, czyli ~42 dni, zanim warianty HG mogą dać sygnał).
2. `39_PAKIET_20_WALIDACJA.bat` (zadanie `sh_pack` runnera) albo ręcznie:

```bat
cd backend
..\.venv\Scripts\python.exe -m masterquo sh pack-replay --dataset <katalog eksportu> --commission-per-lot-side 3.5
```

3. Raport: `data\sh\pack_validation\runs\PKR-*.json` (wszystkie warianty × TF: liczba planów, wartość oczekiwana w R z przedziałem
   bootstrap blokami dziennymi, PF, win rate z przedziałem Wilsona, drawdown, ścieżki TP1/TP2/SL/TIMEOUT, MAE/MFE, niejednoznaczne świece
   STOP_FIRST, 3 odcinki walk-forward, stres kosztów; dla HG porównanie HEDGE / NO_HEDGE / REDUCE na tych samych wejściach).
4. Werdykt per wariant (`data\sh\pack_validation\<ID>.json`, czytany przez katalog i panel): `VALIDATED` tylko na `REAL_USER_DATA` ze
   znaną prowizją, ≥ 200 planów OOS, wszystkie 3 odcinki dodatnie, dolna granica bootstrapu > 0 i (HG) brak dominacji REDUCE / NO_HEDGE.
   Inaczej `INSUFFICIENT_EVIDENCE` / `REJECTED_OOS`; dane syntetyczne → `NOT_VALIDATED`.

Replay używa tych samych detektorów, solvera i polityk co bot; fill na następnym otwarciu M1 (BUY po Ask = Bid + spread świecy), STOP_FIRST
przy świecy dotykającej SL i TP. Parametry nie są dopasowywane (wartości startowe badania), więc cały zakres jest poza próbą dla nich.

## 5. Ograniczenia

* Nie wykonano walidacji na historii MT5 użytkownika – wszystkie warianty `NOT_VALIDATED`. Wynik na danych syntetycznych nie mówi nic
  o rynku. Pakiet nie jest „gotowy do zyskownego handlu”.
* Brak ticków w eksporcie → kolejność TP/SL w jednej świecy rozstrzygana konserwatywnie (STOP_FIRST), raport pokazuje wrażliwość.
* Koszty historyczne: spread ze świec, poślizg – założenie, prowizja – parametr lub scenariusz; swap nie jest modelowany (pozycje ≤ 6 h,
  ale przejście przez rollover jest możliwe – ryzyko raportowane w opisie, nie w liczbach).
* Profil wolumenu i VWAP z tick volume = aktywność feedu brokera, nie globalny wolumen złota.
* Bez skalibrowanego modelu zdarzenia prawdopodobieństwa (P(TP1/TP2 przed SL), P(wynik > 0), oczekiwane R) są `null`.
