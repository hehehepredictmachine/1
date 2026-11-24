# Pakiet 20 strategii XAUUSD (1.38) – research i źródła

**Status dowodowy:** 20 wariantów to **kandydaci do implementacji i walidacji**, nie ranking osiągniętych wyników. Numeracja jest
identyfikatorem. W tym wdrożeniu nie wykonano backtestu na historii MT5 użytkownika – każdy wariant ma status `IMPLEMENTED / NOT_VALIDATED`
(albo `INSUFFICIENT_EVIDENCE` / `REJECTED_OOS` / `VALIDATED` dopiero po replayu na `REAL_USER_DATA`, patrz `RUNBOOK_PL.md`).

## Co pochodzi ze źródeł, a co jest autorską adaptacją PMW

| Element | Źródło (mechanizm) | Adaptacja PMW (hipoteza do testu) |
|---|---|---|
| Hedging jako częściowe, czasowe ograniczenie ekspozycji; koszty i ograniczenie zysków | B02 (IG), B01 (MetaQuotes – hedging vs netting) | 10 polityk HG: warunki aktywacji/powrotu, ratio 0,25/0,50, limity czasu, jedna aktywacja |
| Wsparcie/opór, wybicie, zmiana roli poziomu | B06 (CME) | HG02, HG07, SC06 – poziomy z potwierdzonych pivotów 2/2, retest w 3 świecach, bufor b |
| VWAP i kotwice; opóźnienie wskaźnika | B07 (TradingView) | HG05, SC02 – kotwica = doba handlowa 17:00 New York; tick volume = aktywność feedu |
| Volume profile, value area, POC; tick volume ≠ wolumen globalny | B08 (TradingView) | HG08, SC10 – profil zakończonej poprzedniej doby (PMW-SVP-1) |
| Kanały Donchiana | B09 (IG) | HG03, SC04 – 20 poprzednich świec (bez bieżącej), retest |
| Opening Range Breakout | B10 (FOREX.com) – opis dla forex | HG04, SC03 – okna 08:00–08:15 Londyn i 08:20–08:35 Nowy Jork (IANA, DST) |
| ADX jako siła trendu (progi 20/25) | B11 (Fidelity) | filtry ADX≥25 (HG03, SC04), Range(M15): ADX<20 |
| Bollinger Bands: dotknięcie ≠ sygnał, BandWidth / squeeze | B12 (Bollinger) | HG06, SC05, SC07 – percentyl 20 ze 120, retest / powrót do pasm |
| ATR jako miara zmienności | B13 (Fidelity) | bufor `b = max(2 tick, 0,10 ATR14)`, heurystyka zasięgu TP2 |
| Rodziny wskaźników scalpingowych, waga kosztów | B14 (IG) | SC01, SC08 – pullback EMA20 / Stochastic |
| Stochastic %K/%D | B15 (Fidelity) | SC08 – %K<20 w korekcie, przecięcie %K/%D |
| Relacja gold/silver jako dwie nogi | B16 (CME) | **odrzucone** z podstawowych 20 (inna ekspozycja i inny sizing) |
| MACD: linia, sygnał, histogram | B17 (TradingView) | SC09 – reset histogramu przy linii > 0 |
| Przeuczenie backtestu, PBO, Deflated Sharpe | B18, B19 | raport replayu pokazuje wszystkie warianty × TF (wielokrotne testowanie jawne) |
| Lightweight Charts v5.2 | B20 | wykres planów (linie cen, znaczniki strzałek) |
| Brak trwałej przewagi intraday na złocie po kosztach (Chiny, 5 min, 2018–2021) | B21 (abstrakt) | ostrzeżenie: parametry wymagają testu na feedzie użytkownika |
| Brak predykcyjności standardowych parametrów średnich na metalach, część innych parametrów tak | B22 (abstrakt) | j.w. – nie wynik dla tych 20 profili |

Źródła B01–B22: lista z adresami w masterprompcie 1.37→1.38 (§12), sprawdzone przez autora masterpromptu 9.11.2026. W tym wdrożeniu nie
reprodukowano wyników B21/B22. Jednostki: konwencja produktu **1 pip XAUUSD = 0,10 USD/oz** (`PMW_XAU_PRICE_0_10_V1`) – w repozytorium
nie było innej jawnej definicji pipsa dla XAUUSD (`quant/units.py` ma `pip_size` tylko opcjonalnie i bez wartości dla złota), więc
konfliktu nie zgłoszono. Tick, point, digits, lot i wartość ticka pochodzą z terminala MT5 (B03, B04, B05).

## Odrzucone

Grid, martingale, bezstopowy recovery hedge, zwiększanie wolumenu po stracie; gold/silver, DXY jako druga noga, opcje i kalendarze (inne
instrumenty i inne wykonanie niż koszyk SH na jednym symbolu). REDUCE na rachunku NETTING dla pakietu nie jest włączony (osobny wariant
z własną walidacją – pakiet na NETTING blokuje HG z powodem).
