# Karty 90 strategii (CATALOG-1.41.0)

Generowane z backendu (masterquo/baskets/catalog.py) – jedyne źródło katalogu. Parametry: MANIFEST_9_KOSZYKOW_90_STRATEGII.json.
Aliasy wcześniejszych strategii: brak – strategie złota (S01–S12, SH, paczka PMW, profil scalp, DOUBLE_RETEST_V2) pozostają poza licznikiem 90, bez zmian i bez drugiej trasy wykonania.

| ID | Koszyk | Strategia | Rodzina (wspólny detektor) | TF / kontekst | Setup | Trigger | Unieważnienie / wyjście | Plan |
|---|---|---|---|---|---|---|---|---|
| FX_SMC_01 | FX_SMC | Sweep → CHoCH → Retest | sweep_choch_retest | M5 / M15,H1 | sweep ostatniego potwierdzonego swingu; w 3 świecach CHoCH | pierwszy retest złamanej struktury z potwierdzeniem | ponowne naruszenie ekstremum sweepu | PositionPlan |
| FX_SMC_02 | FX_SMC | BOS → Order Block | bos_ob_retest | M5 / M15,H1 | kierunek HTF zgodny; displacement z BOS; OB | pierwszy retest w 6 świecach, close ponad środkiem OB | close za distal edge OB | PositionPlan |
| FX_SMC_03 | FX_SMC | FVG Continuation | fvg_continuation | M5 / M15 | FVG po displacement zgodne z trendem | pierwszy retest w 6 świecach, close wraca za strefę | close za dalszą granicą strefy | PositionPlan |
| FX_SMC_04 | FX_SMC | Inverse FVG Reversal | ifvg_reversal | M5 / M15 | przeciwne FVG złamane close po CHoCH | retest iFVG od drugiej strony | powrót close za strefę | PositionPlan |
| FX_SMC_05 | FX_SMC | Breaker Block Retest | breaker_retest | M5 / M15,H1 | przeciwny OB złamany displacement + BOS | pierwszy retest byłego OB | ponowne złamanie breakera | PositionPlan |
| FX_SMC_06 | FX_SMC | Second Mitigation Continuation | second_mitigation | M15 / H1 | ważny OB po 1. reteście i nowym BOS | drugi retest z potwierdzeniem (maks. 2) | close poza OB | PositionPlan |
| FX_SMC_07 | FX_SMC | Equal Lows Raid | eq_raid | M5 / M15 | znane EQL naruszone, close wraca | kolejna świeca > high sweepu + b (maks. 2 świece) | brak triggera w 2 świecach | PositionPlan |
| FX_SMC_08 | FX_SMC | Discount OTE Continuation | ote_continuation | M5 / M15,H1 | impuls BOS, zamrożony zakres, retracement 0.62–0.79 w discount | displacement na TF wejścia | zmiana zakresu / utrata początku impulsu | PositionPlan |
| FX_SMC_09 | FX_SMC | Session Range Sweep | range_sweep | M5 / M15 | zakres 60 min przed sesją; sweep do 120 min po kotwicy | MSS + pierwszy retest | jeden event / kierunek / zakres | PositionPlan |
| FX_SMC_10 | FX_SMC | Internal to External Liquidity | internal_external | M5 / H1 | cena w discount zakresu H1; internal sweep + BOS M5 | retest; zewnętrzny swing H1 niewybity | za mało przestrzeni po kosztach | PositionPlan |
| FX_SCALP_01 | FX_SCALP | EMA9/21 Pullback | ema_pullback | M3 / M15 | EMA9 > EMA21, M15 zgodny; dotknięcie EMA9 w 3 świecach | close > high[t−1] + b | close za EMA21 | PositionPlan |
| FX_SCALP_02 | FX_SCALP | Bollinger Reentry | bb_reentry | M5 / M15 | BB20/2, ADX14 < 20, low poza wstęgą | bullish close z powrotem wewnątrz | timeout 8 świec | PositionPlan |
| FX_SCALP_03 | FX_SCALP | Session VWAP Reclaim | vwap_reclaim | M5 / M15 | 2 close pod VWAP (proxy aktywności tickowej – jawnie) | reclaim i retest w 3 świecach | close pod VWAP | PositionPlan |
| FX_SCALP_04 | FX_SCALP | Opening Range Retest | level_breakout_retest | M1 / M5 | zakres pierwszych 15 min sesji; close > OR_high + b | retest do 3 świec, bullish close nad poziomem | jeden event / kierunek / sesję | PositionPlan |
| FX_SCALP_05 | FX_SCALP | Donchian20 Expansion | donchian | M3 / M15 | trend, ADX14 ≥ 25, ATR rośnie | close > HH20 + b | powrót do kanału przed wejściem | PositionPlan |
| FX_SCALP_06 | FX_SCALP | ATR Compression Breakout | compression_breakout | M3 / M5 | ≥3 z 5 zakresów ≤ 0.6A | close nad zamrożonym high, body ≥ A | powrót do kompresji | PositionPlan |
| FX_SCALP_07 | FX_SCALP | RSI2 Trend Snapback | rsi2_snapback | M3 / M15 | trend EMA20/50; RSI2[t−1] < 10 | RSI2 > 20 i close > high[t−1] | utrata dołka pullbacku | PositionPlan |
| FX_SCALP_08 | FX_SCALP | Engulfing at Known Support | engulfing_support | M5 / M15 | znane wsparcie M15 (±b) | bullish engulfing, close > high[t−1] | utrata wsparcia | PositionPlan |
| FX_SCALP_09 | FX_SCALP | Micro Double Bottom | double_bottom | M3 / M5 | 2 potwierdzone dołki (0.2A, 3–12 świec) | close > neckline + b | utrata niższego dołka | PositionPlan |
| FX_SCALP_10 | FX_SCALP | Two-Bar Momentum Continuation | two_bar_momentum | M1 / M5 | trend; 2 świece body ≥ 0.5A, close w skrajnych 20% | druga zamyka się ponad high pierwszej | timeout 4 świece | PositionPlan |
| FX_HEDGE_01 | FX_HEDGE | Structural CHoCH Shield | structural_choch | M5 / H1 | long + bearish CHoCH M5, H1 wciąż wzrostowy | long + bearish CHoCH M5, H1 wciąż wzrostowy | bullish BOS M5, 6 świec lub zamknięcie rodzica | HedgePlan |
| FX_HEDGE_02 | FX_HEDGE | Range Boundary Profit Shield | range_profit | M5 / M15 | long z zyskiem przy oporze; sweep + odrzucenie | long z zyskiem przy oporze; sweep + odrzucenie | reclaim oporu, środek range lub timeout | HedgePlan |
| FX_HEDGE_03 | FX_HEDGE | Volatility Shock Shield | vol_shock | M1 / — | range M1 > 95. percentyla z 200, close przeciw rodzicowi | range M1 > 95. percentyla z 200, close przeciw rodzicowi | 3 zakresy poniżej mediany, struktura lub timeout | HedgePlan |
| FX_HEDGE_04 | FX_HEDGE | Session Transition Shield | session_transition | M5 / — | zmiana sesji; spread / zmienność ponad próg | zmiana sesji; spread / zmienność ponad próg | 3 stabilne świece; brak wykonalności = NO_HEDGE | HedgePlan |
| FX_HEDGE_05 | FX_HEDGE | Multi-Timeframe Countermove | mtf_countermove | M5 / H1 | H1 utrzymuje kierunek; M5 dwie przeciwne sekwencje swingów + retest | H1 utrzymuje kierunek; M5 dwie przeciwne sekwencje swingów + retest | zgodność M5/H1 lub 4 świece | HedgePlan |
| FX_HEDGE_06 | FX_HEDGE | Scheduled Event Shield | event_shield | M5 / — | ekspozycja + wydarzenie z kalendarza za ≤ 5 min | ekspozycja + wydarzenie z kalendarza za ≤ 5 min | koniec okna i normalizacja spreadu | HedgePlan |
| FX_HEDGE_07 | FX_HEDGE | Currency Factor Hedge | currency_factor | M15 / — | ekspozycja jednej waluty ponad limit | ekspozycja jednej waluty ponad limit | powrót do limitu | HedgePlan |
| FX_HEDGE_08 | FX_HEDGE | Gold–Silver Beta Hedge | beta_pair | M15 / — | XAUUSD + dostępny XAGUSD, dodatnia beta | XAUUSD + dostępny XAGUSD, dodatnia beta | wyjście rodzica, rozpad relacji, timeout | HedgePlan |
| FX_HEDGE_09 | FX_HEDGE | FX Pair Relative Exposure | pair_relative | M15 / — | pozycja na skonfigurowanej parze; druga ma dodatnią betę | pozycja na skonfigurowanej parze; druga ma dodatnią betę | residual w limicie / rozpad relacji | HedgePlan |
| FX_HEDGE_10 | FX_HEDGE | Portfolio Minimum-Variance Hedge | min_variance | M15 / — | ≥ 2 pozycje FX; ryzyko koszyka ponad limit | ≥ 2 pozycje FX; ryzyko koszyka ponad limit | rebalans po przekroczeniu pasma | HedgePlan |
| CP_SMC_01 | CP_SMC | Perps Sweep & CHoCH | sweep_choch_retest | M5 / M15,H1 | sweep dołka kontraktu, CHoCH w 3 świecach | retest | ponowne naruszenie sweepu | PerpetualPlan |
| CP_SMC_02 | CP_SMC | Volume-Confirmed Order Block | bos_ob_retest | M5 / M15,H1 | BOS z displacement i RVOL ≥ 1.5 | pierwszy retest OB z odrzuceniem | close pod OB | PerpetualPlan |
| CP_SMC_03 | CP_SMC | FVG Trend Continuation | fvg_continuation | M5 / M15 | FVG po displacement zgodnym z trendem | pierwszy retest w 6 świecach | close za strefą | PerpetualPlan |
| CP_SMC_04 | CP_SMC | iFVG Regime Shift | ifvg_reversal | M5 / M15 | przeciwne FVG złamane z CHoCH | retest | close za dalszą granicą | PerpetualPlan |
| CP_SMC_05 | CP_SMC | Breaker after Failed Breakdown | breaker_retest | M5 / M15,H1 | przeciwny OB po zapisanym wybiciu, przełamany BOS | retest breakera | ponowne złamanie | PerpetualPlan |
| CP_SMC_06 | CP_SMC | Mitigation with OI Participation | second_mitigation | M15 / H1 | drugi retest OB po nowym BOS; ΔOI 5 min > 0 | potwierdzony retest | close poza OB | PerpetualPlan |
| CP_SMC_07 | CP_SMC | Equal-Low Liquidity Raid | eq_raid | M5 / M15 | sweep EQL | close > high sweepu + b | brak triggera w 2 świecach | PerpetualPlan |
| CP_SMC_08 | CP_SMC | Discount OTE with Trend | ote_continuation | M5 / M15,H1 | retracement 0.62–0.79 impulsu BOS w discount | displacement | utrata początku impulsu | PerpetualPlan |
| CP_SMC_09 | CP_SMC | Previous UTC Day Sweep | range_sweep | M5 / M15 | low poprzedniej doby UTC naruszony | reclaim, MSS, pierwszy retest | nowe low | PerpetualPlan |
| CP_SMC_10 | CP_SMC | Cross-Asset Structure Divergence | cross_asset_divergence | M5 / M15 | BTC narusza LL20, kontrakt nie | CHoCH + retest | utrata własnej struktury | PerpetualPlan |
| CP_SCALP_01 | CP_SCALP | EMA Microtrend Pullback | ema_pullback | M3 / M15 | EMA9 > EMA21; dotknięcie EMA9 | close > high[t−1] + b | close za EMA21 | PerpetualPlan |
| CP_SCALP_02 | CP_SCALP | Volume Breakout Retest | level_breakout_retest | M5 / M15 | close > HH20 + b i RVOL ≥ 1.5 | retest w 3 świecach | close pod poziomem − b | PerpetualPlan |
| CP_SCALP_03 | CP_SCALP | UTC VWAP Reclaim | vwap_reclaim | M5 / M15 | 2 close pod VWAP od 00:00 UTC, ≤ 3 przecięcia w 10 świecach | reclaim i retest | close pod VWAP | PerpetualPlan |
| CP_SCALP_04 | CP_SCALP | Bollinger Range Snapback | bb_reentry | M5 / M15 | ADX14 < 20, low poza lower BB | bullish powrót wewnątrz | timeout 8 | PerpetualPlan |
| CP_SCALP_05 | CP_SCALP | Donchian Momentum | donchian | M3 / M15 | trend, ADX ≥ 25, ATR rośnie | close > HH20 + b | powrót do kanału | PerpetualPlan |
| CP_SCALP_06 | CP_SCALP | Squeeze with Volume Expansion | squeeze_volume | M5 / M15 | 3 z 5 bandwidth < 20. percentyla z 200 wcześniejszych | wybicie HH10 i RVOL ≥ 1.5 | powrót do kompresji | PerpetualPlan |
| CP_SCALP_07 | CP_SCALP | RSI2 Trend Recovery | rsi2_snapback | M3 / M15 | trend EMA20/50; RSI2 < 10 | RSI2 > 20, close > high[t−1] | utrata dołka | PerpetualPlan |
| CP_SCALP_08 | CP_SCALP | Relative Strength Breakout | relative_strength | M5 / M15 | r15 własny i BTC > 0, z_asset − z_BTC ≥ 0.5 | wybicie HH20 | utrata 3 świec | PerpetualPlan |
| CP_SCALP_09 | CP_SCALP | L2 & Aggressor Breakout | l2_aggressor | M1 / M5 | close > HH10 | imbalance top5 ≥ 0.20 i agresywny buy ≥ 0.60 (30 s) przez 2 s | reconnect unieważnia | PerpetualPlan |
| CP_SCALP_10 | CP_SCALP | OI-Supported Expansion | oi_expansion | M5 / M15 | close > HH20 + b, RVOL ≥ 1.5, ΔOI 5 min > 0 | kierunek M15 zgodny | powrót pod zakres | PerpetualPlan |
| CP_HEDGE_01 | CP_HEDGE | Single-Alt BTC Beta Hedge | crypto_beta | M15 / M5 | alt long + bearish CHoCH BTC M5 | alt long + bearish CHoCH BTC M5 | bullish BOS BTC, timeout, zamknięcie rodzica | HedgePlan |
| CP_HEDGE_02 | CP_HEDGE | ETH Ecosystem Hedge | eth_ecosystem | M15 / M5 | ekspozycja oznaczona ETH; ETH zmienia strukturę | ekspozycja oznaczona ETH; ETH zmienia strukturę | odbudowa struktury / spadek jakości relacji | HedgePlan |
| CP_HEDGE_03 | CP_HEDGE | Alt-Basket Market Beta | basket_beta | M15 / — | ≥ 2 alty; suma beta-exposure ponad limit | ≥ 2 alty; suma beta-exposure ponad limit | rebalans po przekroczeniu pasma | HedgePlan |
| CP_HEDGE_04 | CP_HEDGE | Two-Factor BTC/ETH Hedge | two_factor | M15 / — | portfel altów z ekspozycją na BTC i ETH | portfel altów z ekspozycją na BTC i ETH | brak stabilnego rozwiązania = NO_HEDGE | HedgePlan |
| CP_HEDGE_05 | CP_HEDGE | Sector Relative-Value Protection | residual_pair | M15 / — | residual z-score log-cen > 2 przy dodatniej becie | residual z-score log-cen > 2 przy dodatniej becie | residual 0.5 / rozpad / timeout | HedgePlan |
| CP_HEDGE_06 | CP_HEDGE | Volatility Shock Beta Shield | crypto_vol_shock | M1 / — | range BTC M1 > 95. percentyla z 200, close przeciw ekspozycji | range BTC M1 > 95. percentyla z 200, close przeciw ekspozycji | 3 normalne zakresy / timeout | HedgePlan |
| CP_HEDGE_07 | CP_HEDGE | Same-Underlying Cross-Market Hedge | cross_market | M15 / — | perp + drugi kontrakt tego samego underlying w innym namespace | perp + drugi kontrakt tego samego underlying w innym namespace | limit basis / koszt / timeout | HedgePlan |
| CP_HEDGE_08 | CP_HEDGE | Owned Spot Inventory Hedge | spot_inventory | M15 / — | zweryfikowane saldo spot + odpowiadający perp | zweryfikowane saldo spot + odpowiadający perp | zmniejszenie inventory / limit margin | HedgePlan |
| CP_HEDGE_09 | CP_HEDGE | Portfolio Stress-Loss Hedge | stress_loss | M15 / — | strata scenariuszowa ponad limit | strata scenariuszowa ponad limit | powrót do limitu | HedgePlan |
| CP_HEDGE_10 | CP_HEDGE | Funding-Aware Hedge Selection | funding_aware | M15 / — | ekspozycja wymaga hedge; ≥ 2 instrumenty spełniają warunek | ekspozycja wymaga hedge; ≥ 2 instrumenty spełniają warunek | zmiana kosztów > koszt przebudowy | HedgePlan |
| OTC_SMC_01 | OTC_SMC | Micro Sweep & CHoCH | sweep_choch_retest | S15 / M1,M5 | sweep dołka; CHoCH w 3 świecach | pierwszy retest | utrata ekstremum / deadline | FixedExpiryPlan |
| OTC_SMC_02 | OTC_SMC | Micro Order Block Retest | bos_ob_retest | S30 / M1 | displacement z BOS tworzy OB | retest, close ponad środkiem | close pod distal edge | FixedExpiryPlan |
| OTC_SMC_03 | OTC_SMC | Local FVG Continuation | fvg_continuation | S15 / M1 | własne FVG zgodne z M1 | retest, close za strefą | powrót poniżej strefy | FixedExpiryPlan |
| OTC_SMC_04 | OTC_SMC | Micro iFVG Reversal | ifvg_reversal | S30 / M1 | przeciwne FVG złamane po CHoCH | retest od góry | utrata strefy | FixedExpiryPlan |
| OTC_SMC_05 | OTC_SMC | Local Breaker Block | breaker_retest | S30 / M1,M5 | złamany przeciwny OB, BOS | retest dawnej strefy | close poza breakerem | FixedExpiryPlan |
| OTC_SMC_06 | OTC_SMC | Second Mitigation Pattern | second_mitigation | S30 / M1 | drugi retest OB po nowym BOS | retest (maks. 2) | brak nowego BOS | FixedExpiryPlan |
| OTC_SMC_07 | OTC_SMC | Equal-Low Raid | eq_raid | S15 / M1 | sweep 2 EQL; reclaim | close > high sweepu + b | brak potwierdzenia w 2 świecach | FixedExpiryPlan |
| OTC_SMC_08 | OTC_SMC | Discount OTE Microtrend | ote_continuation | S30 / M1,M5 | impuls BOS, OTE w discount | displacement | utrata początku impulsu | FixedExpiryPlan |
| OTC_SMC_09 | OTC_SMC | Rolling Range Sweep | range_sweep | S15 / M1 | zakres 20 świec; sweep low | powrót, MSS, retest | ten sam zakres przez event | FixedExpiryPlan |
| OTC_SMC_10 | OTC_SMC | Nested Structure Continuation | nested_structure | S15 / M1,M5 | test OB M1 w trendzie M5 | BOS S15 + retest | utrata strefy nadrzędnej | FixedExpiryPlan |
| OTC_SCALP_01 | OTC_SCALP | EMA9/21 Micro Pullback | ema_pullback | S15 / M1 | EMA9 > EMA21, EMA21 rośnie | close > high[t−1] + b | utrata dołka pullbacku | FixedExpiryPlan |
| OTC_SCALP_02 | OTC_SCALP | Bollinger Wick Reentry | bb_reentry | S15 / M1 | ADX < 20; low poza BB | bullish close wewnątrz, knot ≥ 1.5 × body | nowe low | FixedExpiryPlan |
| OTC_SCALP_03 | OTC_SCALP | EMA20 Mean Reclaim | ema20_mean_reclaim | S30 / M1 | range ADX < 20; odchylenie ≤ −1A | redukcja odchylenia ≥ 0.5A | naruszenie min. 2 świec | FixedExpiryPlan |
| OTC_SCALP_04 | OTC_SCALP | Range20 Breakout Retest | level_breakout_retest | S15 / M1 | close > HH20 + b | retest w 2 świecach | close pod poziomem − b | FixedExpiryPlan |
| OTC_SCALP_05 | OTC_SCALP | Compression Price Expansion | compression_breakout | S15 / M1 | 3 z 5 zakresów ≤ 0.6A | close nad high, body ≥ 0.8A, close w górnych 20% | powrót do kompresji | FixedExpiryPlan |
| OTC_SCALP_06 | OTC_SCALP | RSI2 Trend Recovery | rsi2_snapback | S15 / M1 | trend M1; RSI2 < 10 | RSI2 > 20, close > high[t−1] | utrata dołka | FixedExpiryPlan |
| OTC_SCALP_07 | OTC_SCALP | Engulfing at Local Support | engulfing_support | S30 / M1 | wsparcie z 20 M1 | engulfing, close > high[t−1] | utrata poziomu | FixedExpiryPlan |
| OTC_SCALP_08 | OTC_SCALP | Micro Double Bottom Break | double_bottom | S15 / M1 | 2 dołki (0.2A, 3–12 świec) | close > neckline + b | utrata niższego dołka | FixedExpiryPlan |
| OTC_SCALP_09 | OTC_SCALP | Inside-Bar Release | inside_bar | S15 / M1 | inside bar w świecy matce; kontekst zgodny | close > high matki + b | utrata low matki | FixedExpiryPlan |
| OTC_SCALP_10 | OTC_SCALP | Failed Breakdown Snapback | failed_breakdown | S15 / M1 | low < LL20 − b, close wraca | close > high świecy sweepu | nowe low | FixedExpiryPlan |
| OTC_HEDGE_01 | OTC_HEDGE | Structure-Shift Protection | otc_structure | S15 / — | cena nad strike, bearish CHoCH S15 | cena nad strike, bearish CHoCH S15 | gate dla skrajnych cen | HedgePlan |
| OTC_HEDGE_02 | OTC_HEDGE | Liquidity-Sweep Profit Protection | otc_sweep | S15 / — | korzystny ruch, sweep oporu, bearish close | korzystny ruch, sweep oporu, bearish close | przedział między strikes sprawdzony | HedgePlan |
| OTC_HEDGE_03 | OTC_HEDGE | Volatility-Shock Protection | otc_vol_shock | S15 / — | range S15 > 95. percentyla, close przeciw CALL | range S15 > 95. percentyla, close przeciw CALL | bez dokładania | HedgePlan |
| OTC_HEDGE_04 | OTC_HEDGE | Late-Expiry Risk Lock | otc_late_lock | S15 / — | pozostało 25–40% czasu, cena po korzystnej stronie | pozostało 25–40% czasu, cena po korzystnej stronie | lock ujemnego wyniku widoczny | HedgePlan |
| OTC_HEDGE_05 | OTC_HEDGE | Payout Repricing Protection | otc_payout_reprice | S15 / — | payout przeciwnej nogi wzrósł | payout przeciwnej nogi wzrósł | odrzuć nieaktualny payout | HedgePlan |
| OTC_HEDGE_06 | OTC_HEDGE | Momentum-Stall Protection | otc_stall | S15 / — | 3 S15 bez nowego high, body ≤ 0.3A | 3 S15 bez nowego high, body ≤ 0.3A | jedno uzbrojenie na ciąg | HedgePlan |
| OTC_HEDGE_07 | OTC_HEDGE | Same-Expiry Directional Basket | otc_basket | S15 / — | ≥ 2 CALL o wspólnym expiry ponad limit | ≥ 2 CALL o wspólnym expiry ponad limit | limit grupy nie mnoży się | HedgePlan |
| OTC_HEDGE_08 | OTC_HEDGE | Expiry-Group Loss Budget | otc_loss_budget | S15 / — | maks. strata grupy ponad limit | maks. strata grupy ponad limit | NO_HEDGE gdy brak poprawy | HedgePlan |
| OTC_HEDGE_09 | OTC_HEDGE | Two-Step Corridor Protection | otc_corridor | S15 / — | po 1. ochronie kolejny ruch ≥ 0.5A | po 1. ochronie kolejny ruch ≥ 0.5A | domyślnie 1 warstwa | HedgePlan |
| OTC_HEDGE_10 | OTC_HEDGE | Mixed-Strike Residual Hedge | otc_residual | S15 / — | CALL i PUT o tym samym expiry, nierówny ogon | CALL i PUT o tym samym expiry, nierówny ogon | zakaz naprzemiennego dokładania | HedgePlan |
