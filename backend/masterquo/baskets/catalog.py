"""Manifest of the ACTIVE 6 baskets x 10 = 60 canonical strategies (CATALOG-1.45.0, TASK 020: OTC retired) + the LEGACY/CUSTOM section (the existing gold strategies,
outside the 60 counter - first-class, untouched, never re-routed through the baskets).

Every entry carries the full contract of spec section 3 (strategy_id, version, basket_id, profile_id, family_id, correlation_group,
supported_product_types, required_capabilities, required_inputs, signal_timeframe, context_timeframes, min_history, parameter_schema,
regime_rule, setup_rule, trigger_rule, entry_policy, cancellation_rule, plan_type, exit_policy_or_expiry_policy, risk_policy,
model_feature_schema, reason_codes, config_hash, detector_version). Parameters are real configuration consumed by the rule families
(rules.py) and hedge planners (hedge.py) - not UI text.
"""
from __future__ import annotations

import hashlib
import json

from . import detectors as D

VERSION = "CATALOG-1.45.0"          # 1.45 (TASK 020): 60 active / 6 baskets / 2 profiles; OTC = RETIRED (history only)
PROFILES = {
    "FOREX_MT5": {"name": "FOREX / MT5", "venue": "MT5", "products": ["CFD", "FX_SPOT_CFD", "METAL_CFD"], "settlement": "POSITION",
                  "execution_capability": "AUTO_VIA_SH_PATH",
                  "execution_note": "1.42: plany koszyków FX trafiają do istniejącej ścieżki SH bota (ryzyko, STOP, tryb wykonania, deduplikacja) – bez nowej, równoległej trasy"},
    "CRYPTO_FOMO_PERPS": {"name": "CRYPTO PERPS / FOMO (fomo.family)", "venue": "HYPERLIQUID (perps używane przez FOMO)", "products": ["PERPETUAL"],
                          "settlement": "PERPETUAL", "execution_capability": "MANUAL_ONLY",
                          "execution_note": "brak udokumentowanego API rachunku FOMO – ticket do ręcznego wykonania w FOMO; dane: publiczne Hyperliquid Info API"},
}
# TASK 020: the OTC line is RETIRED. Kept ONLY so old history rows keep their original identifiers (read-only); never consulted by
# selection, scanning, SFB, rankers or the API candidate lists.
LEGACY_RETIRED_PROFILES = {
    "OTC_GOLD_POCKETOPTION": {"name": "OTC GOLD / Pocket Option (WYCOFANY)", "venue": "POCKET_OPTION", "products": ["FIXED_EXPIRY"], "settlement": "FIXED_EXPIRY",
                              "execution_capability": "MANUAL_ONLY",
                              "execution_note": "brak dopuszczonego interfejsu zleceń – sygnał + ticket ręczny; feed wyłącznie własny Gold OTC (import / konektor)"},
}
BASKETS = {
    "FX_SMC": ("FOREX_MT5", "SMC"), "FX_SCALP": ("FOREX_MT5", "SCALP"), "FX_HEDGE": ("FOREX_MT5", "HEDGING"),
    "CP_SMC": ("CRYPTO_FOMO_PERPS", "SMC"), "CP_SCALP": ("CRYPTO_FOMO_PERPS", "SCALP"), "CP_HEDGE": ("CRYPTO_FOMO_PERPS", "HEDGING"),
}
LEGACY_RETIRED_BASKETS = {
    "OTC_SMC": ("OTC_GOLD_POCKETOPTION", "SMC"), "OTC_SCALP": ("OTC_GOLD_POCKETOPTION", "SCALP"), "OTC_HEDGE": ("OTC_GOLD_POCKETOPTION", "HEDGING"),
}
RETIRED_PROFILE_IDS = frozenset(LEGACY_RETIRED_PROFILES)
RETIRED_BASKET_IDS = frozenset(LEGACY_RETIRED_BASKETS)
RETIRED_STRATEGY_PREFIXES = ("OTC_SMC_", "OTC_SCALP_", "OTC_HEDGE_")


# id, name, family, signal_tf, context_tfs, params, required_inputs(extra), correlation_group, setup, trigger, cancel, [D seconds for OTC]
_FX_SMC = [
    ("FX_SMC_01", "Sweep → CHoCH → Retest", "sweep_choch_retest", "M5", ["M15", "H1"], {}, [], "SWEEP_RECLAIM",
     "sweep ostatniego potwierdzonego swingu; w 3 świecach CHoCH", "pierwszy retest złamanej struktury z potwierdzeniem", "ponowne naruszenie ekstremum sweepu"),
    ("FX_SMC_02", "BOS → Order Block", "bos_ob_retest", "M5", ["M15", "H1"], {}, [], "BOS_OB",
     "kierunek HTF zgodny; displacement z BOS; OB", "pierwszy retest w 6 świecach, close ponad środkiem OB", "close za distal edge OB"),
    ("FX_SMC_03", "FVG Continuation", "fvg_continuation", "M5", ["M15"], {"max_wait": 6}, [], "FVG",
     "FVG po displacement zgodne z trendem", "pierwszy retest w 6 świecach, close wraca za strefę", "close za dalszą granicą strefy"),
    ("FX_SMC_04", "Inverse FVG Reversal", "ifvg_reversal", "M5", ["M15"], {}, [], "IFVG",
     "przeciwne FVG złamane close po CHoCH", "retest iFVG od drugiej strony", "powrót close za strefę"),
    ("FX_SMC_05", "Breaker Block Retest", "breaker_retest", "M5", ["M15", "H1"], {}, [], "BREAKER",
     "przeciwny OB złamany displacement + BOS", "pierwszy retest byłego OB", "ponowne złamanie breakera"),
    ("FX_SMC_06", "Second Mitigation Continuation", "second_mitigation", "M15", ["H1"], {}, [], "BOS_OB",
     "ważny OB po 1. reteście i nowym BOS", "drugi retest z potwierdzeniem (maks. 2)", "close poza OB"),
    ("FX_SMC_07", "Equal Lows Raid", "eq_raid", "M5", ["M15"], {}, [], "SWEEP_RECLAIM",
     "znane EQL naruszone, close wraca", "kolejna świeca > high sweepu + b (maks. 2 świece)", "brak triggera w 2 świecach"),
    ("FX_SMC_08", "Discount OTE Continuation", "ote_continuation", "M5", ["M15", "H1"], {"ote": [0.62, 0.79]}, [], "OTE",
     "impuls BOS, zamrożony zakres, retracement 0.62–0.79 w discount", "displacement na TF wejścia", "zmiana zakresu / utrata początku impulsu"),
    ("FX_SMC_09", "Session Range Sweep", "range_sweep", "M5", ["M15"], {"range": "SESSION", "anchors": [["Europe/London", "08:00"], ["America/New_York", "08:00"]]},
     ["session_calendar"], "SWEEP_RECLAIM", "zakres 60 min przed sesją; sweep do 120 min po kotwicy", "MSS + pierwszy retest", "jeden event / kierunek / zakres"),
    ("FX_SMC_10", "Internal to External Liquidity", "internal_external", "M5", ["H1"], {"min_rr": 1.0}, [], "SWEEP_RECLAIM",
     "cena w discount zakresu H1; internal sweep + BOS M5", "retest; zewnętrzny swing H1 niewybity", "za mało przestrzeni po kosztach"),
]
_FX_SCALP = [
    ("FX_SCALP_01", "EMA9/21 Pullback", "ema_pullback", "M3", ["M15"], {}, [], "TREND_PULLBACK",
     "EMA9 > EMA21, M15 zgodny; dotknięcie EMA9 w 3 świecach", "close > high[t−1] + b", "close za EMA21"),
    ("FX_SCALP_02", "Bollinger Reentry", "bb_reentry", "M5", ["M15"], {"adx_max": 20}, [], "MEAN_REVERSION",
     "BB20/2, ADX14 < 20, low poza wstęgą", "bullish close z powrotem wewnątrz", "timeout 8 świec"),
    ("FX_SCALP_03", "Session VWAP Reclaim", "vwap_reclaim", "M5", ["M15"], {"anchor": "SESSION", "session": ["Europe/London", "08:00"], "tick_proxy": True},
     ["tick_activity_proxy"], "VWAP", "2 close pod VWAP (proxy aktywności tickowej – jawnie)", "reclaim i retest w 3 świecach", "close pod VWAP"),
    ("FX_SCALP_04", "Opening Range Retest", "level_breakout_retest", "M1", ["M5"], {"level": "OPENING_RANGE", "session": ["Europe/London", "08:00"],
                                                                                 "retest_within": 3}, ["session_calendar"], "BREAKOUT",
     "zakres pierwszych 15 min sesji; close > OR_high + b", "retest do 3 świec, bullish close nad poziomem", "jeden event / kierunek / sesję"),
    ("FX_SCALP_05", "Donchian20 Expansion", "donchian", "M3", ["M15"], {"adx_min": 25}, [], "BREAKOUT",
     "trend, ADX14 ≥ 25, ATR rośnie", "close > HH20 + b", "powrót do kanału przed wejściem"),
    ("FX_SCALP_06", "ATR Compression Breakout", "compression_breakout", "M3", ["M5"], {"k_range": 0.6, "k_body": 1.0}, [], "COMPRESSION",
     "≥3 z 5 zakresów ≤ 0.6A", "close nad zamrożonym high, body ≥ A", "powrót do kompresji"),
    ("FX_SCALP_07", "RSI2 Trend Snapback", "rsi2_snapback", "M3", ["M15"], {}, [], "TREND_PULLBACK",
     "trend EMA20/50; RSI2[t−1] < 10", "RSI2 > 20 i close > high[t−1]", "utrata dołka pullbacku"),
    ("FX_SCALP_08", "Engulfing at Known Support", "engulfing_support", "M5", ["M15"], {"support": "HTF_SWINGS"}, [], "SUPPORT_REJECTION",
     "znane wsparcie M15 (±b)", "bullish engulfing, close > high[t−1]", "utrata wsparcia"),
    ("FX_SCALP_09", "Micro Double Bottom", "double_bottom", "M3", ["M5"], {"tol_atr": 0.2}, [], "DOUBLE_BOTTOM",
     "2 potwierdzone dołki (0.2A, 3–12 świec)", "close > neckline + b", "utrata niższego dołka"),
    ("FX_SCALP_10", "Two-Bar Momentum Continuation", "two_bar_momentum", "M1", ["M5"], {}, [], "MOMENTUM",
     "trend; 2 świece body ≥ 0.5A, close w skrajnych 20%", "druga zamyka się ponad high pierwszej", "timeout 4 świece"),
]
_CP_SMC = [
    ("CP_SMC_01", "Perps Sweep & CHoCH", "sweep_choch_retest", "M5", ["M15", "H1"], {}, [], "SWEEP_RECLAIM",
     "sweep dołka kontraktu, CHoCH w 3 świecach", "retest", "ponowne naruszenie sweepu"),
    ("CP_SMC_02", "Volume-Confirmed Order Block", "bos_ob_retest", "M5", ["M15", "H1"], {"rvol_min": 1.5}, ["real_volume"], "BOS_OB",
     "BOS z displacement i RVOL ≥ 1.5", "pierwszy retest OB z odrzuceniem", "close pod OB"),
    ("CP_SMC_03", "FVG Trend Continuation", "fvg_continuation", "M5", ["M15"], {"max_wait": 6}, [], "FVG",
     "FVG po displacement zgodnym z trendem", "pierwszy retest w 6 świecach", "close za strefą"),
    ("CP_SMC_04", "iFVG Regime Shift", "ifvg_reversal", "M5", ["M15"], {}, [], "IFVG", "przeciwne FVG złamane z CHoCH", "retest", "close za dalszą granicą"),
    ("CP_SMC_05", "Breaker after Failed Breakdown", "breaker_retest", "M5", ["M15", "H1"], {"need_failed_break": True}, [], "BREAKER",
     "przeciwny OB po zapisanym wybiciu, przełamany BOS", "retest breakera", "ponowne złamanie"),
    ("CP_SMC_06", "Mitigation with OI Participation", "second_mitigation", "M15", ["H1"], {"oi_delta": True}, ["open_interest"], "BOS_OB",
     "drugi retest OB po nowym BOS; ΔOI 5 min > 0", "potwierdzony retest", "close poza OB"),
    ("CP_SMC_07", "Equal-Low Liquidity Raid", "eq_raid", "M5", ["M15"], {}, [], "SWEEP_RECLAIM", "sweep EQL", "close > high sweepu + b", "brak triggera w 2 świecach"),
    ("CP_SMC_08", "Discount OTE with Trend", "ote_continuation", "M5", ["M15", "H1"], {"ote": [0.62, 0.79]}, [], "OTE",
     "retracement 0.62–0.79 impulsu BOS w discount", "displacement", "utrata początku impulsu"),
    ("CP_SMC_09", "Previous UTC Day Sweep", "range_sweep", "M5", ["M15"], {"range": "PREV_UTC_DAY"}, [], "SWEEP_RECLAIM",
     "low poprzedniej doby UTC naruszony", "reclaim, MSS, pierwszy retest", "nowe low"),
    ("CP_SMC_10", "Cross-Asset Structure Divergence", "cross_asset_divergence", "M5", ["M15"], {"window": 8}, ["benchmark_btc"], "XASSET",
     "BTC narusza LL20, kontrakt nie", "CHoCH + retest", "utrata własnej struktury"),
]
_CP_SCALP = [
    ("CP_SCALP_01", "EMA Microtrend Pullback", "ema_pullback", "M3", ["M15"], {}, [], "TREND_PULLBACK", "EMA9 > EMA21; dotknięcie EMA9", "close > high[t−1] + b", "close za EMA21"),
    ("CP_SCALP_02", "Volume Breakout Retest", "level_breakout_retest", "M5", ["M15"], {"level": "HH20", "rvol_min": 1.5, "retest_within": 3}, ["real_volume"],
     "BREAKOUT", "close > HH20 + b i RVOL ≥ 1.5", "retest w 3 świecach", "close pod poziomem − b"),
    ("CP_SCALP_03", "UTC VWAP Reclaim", "vwap_reclaim", "M5", ["M15"], {"anchor": "UTC_DAY", "max_crosses": 3}, ["real_volume"], "VWAP",
     "2 close pod VWAP od 00:00 UTC, ≤ 3 przecięcia w 10 świecach", "reclaim i retest", "close pod VWAP"),
    ("CP_SCALP_04", "Bollinger Range Snapback", "bb_reentry", "M5", ["M15"], {"adx_max": 20}, [], "MEAN_REVERSION",
     "ADX14 < 20, low poza lower BB", "bullish powrót wewnątrz", "timeout 8"),
    ("CP_SCALP_05", "Donchian Momentum", "donchian", "M3", ["M15"], {"adx_min": 25}, [], "BREAKOUT", "trend, ADX ≥ 25, ATR rośnie", "close > HH20 + b", "powrót do kanału"),
    ("CP_SCALP_06", "Squeeze with Volume Expansion", "squeeze_volume", "M5", ["M15"], {"rvol_min": 1.5}, ["real_volume"], "COMPRESSION",
     "3 z 5 bandwidth < 20. percentyla z 200 wcześniejszych", "wybicie HH10 i RVOL ≥ 1.5", "powrót do kompresji"),
    ("CP_SCALP_07", "RSI2 Trend Recovery", "rsi2_snapback", "M3", ["M15"], {}, [], "TREND_PULLBACK", "trend EMA20/50; RSI2 < 10", "RSI2 > 20, close > high[t−1]", "utrata dołka"),
    ("CP_SCALP_08", "Relative Strength Breakout", "relative_strength", "M5", ["M15"], {"z_min": 0.5}, ["benchmark_btc"], "XASSET",
     "r15 własny i BTC > 0, z_asset − z_BTC ≥ 0.5", "wybicie HH20", "utrata 3 świec"),
    ("CP_SCALP_09", "L2 & Aggressor Breakout", "l2_aggressor", "M1", ["M5"], {}, ["l2_orderbook", "trades_aggressor"], "ORDERFLOW",
     "close > HH10", "imbalance top5 ≥ 0.20 i agresywny buy ≥ 0.60 (30 s) przez 2 s", "reconnect unieważnia"),
    ("CP_SCALP_10", "OI-Supported Expansion", "oi_expansion", "M5", ["M15"], {}, ["real_volume", "open_interest"], "BREAKOUT",
     "close > HH20 + b, RVOL ≥ 1.5, ΔOI 5 min > 0", "kierunek M15 zgodny", "powrót pod zakres"),
]
_OTC_SMC = [
    ("OTC_SMC_01", "Micro Sweep & CHoCH", "sweep_choch_retest", "S15", ["M1", "M5"], {}, [], "SWEEP_RECLAIM", "sweep dołka; CHoCH w 3 świecach", "pierwszy retest", "utrata ekstremum / deadline", 120),
    ("OTC_SMC_02", "Micro Order Block Retest", "bos_ob_retest", "S30", ["M1"], {}, [], "BOS_OB", "displacement z BOS tworzy OB", "retest, close ponad środkiem", "close pod distal edge", 120),
    ("OTC_SMC_03", "Local FVG Continuation", "fvg_continuation", "S15", ["M1"], {"max_wait": 6}, [], "FVG", "własne FVG zgodne z M1", "retest, close za strefą", "powrót poniżej strefy", 60),
    ("OTC_SMC_04", "Micro iFVG Reversal", "ifvg_reversal", "S30", ["M1"], {}, [], "IFVG", "przeciwne FVG złamane po CHoCH", "retest od góry", "utrata strefy", 120),
    ("OTC_SMC_05", "Local Breaker Block", "breaker_retest", "S30", ["M1", "M5"], {}, [], "BREAKER", "złamany przeciwny OB, BOS", "retest dawnej strefy", "close poza breakerem", 180),
    ("OTC_SMC_06", "Second Mitigation Pattern", "second_mitigation", "S30", ["M1"], {}, [], "BOS_OB", "drugi retest OB po nowym BOS", "retest (maks. 2)", "brak nowego BOS", 120),
    ("OTC_SMC_07", "Equal-Low Raid", "eq_raid", "S15", ["M1"], {}, [], "SWEEP_RECLAIM", "sweep 2 EQL; reclaim", "close > high sweepu + b", "brak potwierdzenia w 2 świecach", 60),
    ("OTC_SMC_08", "Discount OTE Microtrend", "ote_continuation", "S30", ["M1", "M5"], {"ote": [0.62, 0.79]}, [], "OTE", "impuls BOS, OTE w discount", "displacement", "utrata początku impulsu", 180),
    ("OTC_SMC_09", "Rolling Range Sweep", "range_sweep", "S15", ["M1"], {"range": "ROLLING20"}, [], "SWEEP_RECLAIM", "zakres 20 świec; sweep low", "powrót, MSS, retest", "ten sam zakres przez event", 120),
    ("OTC_SMC_10", "Nested Structure Continuation", "nested_structure", "S15", ["M1", "M5"], {}, [], "NESTED", "test OB M1 w trendzie M5", "BOS S15 + retest", "utrata strefy nadrzędnej", 120),
]
_OTC_SCALP = [
    ("OTC_SCALP_01", "EMA9/21 Micro Pullback", "ema_pullback", "S15", ["M1"], {"ema21_rising": True}, [], "TREND_PULLBACK", "EMA9 > EMA21, EMA21 rośnie", "close > high[t−1] + b", "utrata dołka pullbacku", 60),
    ("OTC_SCALP_02", "Bollinger Wick Reentry", "bb_reentry", "S15", ["M1"], {"adx_max": 20, "wick_ratio": 1.5}, [], "MEAN_REVERSION", "ADX < 20; low poza BB", "bullish close wewnątrz, knot ≥ 1.5 × body", "nowe low", 60),
    ("OTC_SCALP_03", "EMA20 Mean Reclaim", "ema20_mean_reclaim", "S30", ["M1"], {}, [], "MEAN_REVERSION", "range ADX < 20; odchylenie ≤ −1A", "redukcja odchylenia ≥ 0.5A", "naruszenie min. 2 świec", 120),
    ("OTC_SCALP_04", "Range20 Breakout Retest", "level_breakout_retest", "S15", ["M1"], {"level": "HH20", "retest_within": 2}, [], "BREAKOUT", "close > HH20 + b", "retest w 2 świecach", "close pod poziomem − b", 120),
    ("OTC_SCALP_05", "Compression Price Expansion", "compression_breakout", "S15", ["M1"], {"k_range": 0.6, "k_body": 0.8, "close_extreme": True}, [], "COMPRESSION",
     "3 z 5 zakresów ≤ 0.6A", "close nad high, body ≥ 0.8A, close w górnych 20%", "powrót do kompresji", 120),
    ("OTC_SCALP_06", "RSI2 Trend Recovery", "rsi2_snapback", "S15", ["M1"], {"htf_trend": True}, [], "TREND_PULLBACK", "trend M1; RSI2 < 10", "RSI2 > 20, close > high[t−1]", "utrata dołka", 60),
    ("OTC_SCALP_07", "Engulfing at Local Support", "engulfing_support", "S30", ["M1"], {"support": "LOCAL20"}, [], "SUPPORT_REJECTION", "wsparcie z 20 M1", "engulfing, close > high[t−1]", "utrata poziomu", 180),
    ("OTC_SCALP_08", "Micro Double Bottom Break", "double_bottom", "S15", ["M1"], {"tol_atr": 0.2}, [], "DOUBLE_BOTTOM", "2 dołki (0.2A, 3–12 świec)", "close > neckline + b", "utrata niższego dołka", 120),
    ("OTC_SCALP_09", "Inside-Bar Release", "inside_bar", "S15", ["M1"], {}, [], "MOMENTUM", "inside bar w świecy matce; kontekst zgodny", "close > high matki + b", "utrata low matki", 60),
    ("OTC_SCALP_10", "Failed Breakdown Snapback", "failed_breakdown", "S15", ["M1"], {}, [], "SWEEP_RECLAIM", "low < LL20 − b, close wraca", "close > high świecy sweepu", "nowe low", 60),
]
# hedge planners: id, name, planner, tf, ctx, params, required_inputs, trigger, plan, exit
_FX_HEDGE = [
    ("FX_HEDGE_01", "Structural CHoCH Shield", "structural_choch", "M5", ["H1"], {"ratio": 0.5}, ["account_hedging_mode"], "long + bearish CHoCH M5, H1 wciąż wzrostowy",
     "częściowy short tego samego instrumentu (konto hedging)", "bullish BOS M5, 6 świec lub zamknięcie rodzica"),
    ("FX_HEDGE_02", "Range Boundary Profit Shield", "range_profit", "M5", ["M15"], {"ratio": 0.5}, ["account_hedging_mode"], "long z zyskiem przy oporze; sweep + odrzucenie",
     "częściowy short z własnym unieważnieniem", "reclaim oporu, środek range lub timeout"),
    ("FX_HEDGE_03", "Volatility Shock Shield", "vol_shock", "M1", [], {"pct": 0.95, "lookback": 200, "ratio": 0.5}, ["account_hedging_mode"],
     "range M1 > 95. percentyla z 200, close przeciw rodzicowi", "jednorazowy hedge (limit kosztu i margin)", "3 zakresy poniżej mediany, struktura lub timeout"),
    ("FX_HEDGE_04", "Session Transition Shield", "session_transition", "M5", [], {"spread_mult": 2.0, "ratio": 0.5}, ["account_hedging_mode", "session_calendar"],
     "zmiana sesji; spread / zmienność ponad próg", "częściowa ochrona tego samego symbolu", "3 stabilne świece; brak wykonalności = NO_HEDGE"),
    ("FX_HEDGE_05", "Multi-Timeframe Countermove", "mtf_countermove", "M5", ["H1"], {"ratio": 0.5, "timeout": 4}, ["account_hedging_mode"],
     "H1 utrzymuje kierunek; M5 dwie przeciwne sekwencje swingów + retest", "krótka ochrona korekty", "zgodność M5/H1 lub 4 świece"),
    ("FX_HEDGE_06", "Scheduled Event Shield", "event_shield", "M5", [], {"before_min": 5, "ratio": 0.5}, ["account_hedging_mode", "economic_calendar"],
     "ekspozycja + wydarzenie z kalendarza za ≤ 5 min", "częściowa ochrona przy kwotowaniach", "koniec okna i normalizacja spreadu"),
    ("FX_HEDGE_07", "Currency Factor Hedge", "currency_factor", "M15", [], {"limit_ccy_notional": None}, ["fx_pairs", "currency_matrix"],
     "ekspozycja jednej waluty ponad limit", "przeciwny dostępny instrument FX z macierzy walut", "powrót do limitu"),
    ("FX_HEDGE_08", "Gold–Silver Beta Hedge", "beta_pair", "M15", [], {"partner": "XAGUSD", "ratio": 0.5, "window": 120, "window2": 60, "corr_min": 0.5}, ["partner_symbol"],
     "XAUUSD + dostępny XAGUSD, dodatnia beta", "przeciwna XAGUSD z beta i ekspozycji pieniężnej", "wyjście rodzica, rozpad relacji, timeout"),
    ("FX_HEDGE_09", "FX Pair Relative Exposure", "pair_relative", "M15", [], {"partner": None, "ratio": 0.5, "window": 120, "window2": 60, "corr_min": 0.5}, ["partner_symbol"],
     "pozycja na skonfigurowanej parze; druga ma dodatnią betę", "przeciwna ekspozycja w parze porównawczej", "residual w limicie / rozpad relacji"),
    ("FX_HEDGE_10", "Portfolio Minimum-Variance Hedge", "min_variance", "M15", [], {"max_instruments": 2, "risk_limit": None}, ["fx_pairs"],
     "≥ 2 pozycje FX; ryzyko koszyka ponad limit", "do 2 instrumentów minimalizujących wariancję", "rebalans po przekroczeniu pasma"),
]
_CP_HEDGE = [
    ("CP_HEDGE_01", "Single-Alt BTC Beta Hedge", "crypto_beta", "M15", ["M5"], {"factor": "BTC", "ratio": 0.5, "window": 120, "window2": 60, "corr_min": 0.5, "trigger": "BENCH_CHOCH"},
     ["declared_exposure", "benchmark_btc"], "alt long + bearish CHoCH BTC M5", "short BTC perp z beta", "bullish BOS BTC, timeout, zamknięcie rodzica"),
    ("CP_HEDGE_02", "ETH Ecosystem Hedge", "eth_ecosystem", "M15", ["M5"], {"factor": "ETH", "ratio": 0.5, "window": 120, "window2": 60, "corr_min": 0.5, "trigger": "BENCH_CHOCH",
                                                                         "require_tag": "ETH"}, ["declared_exposure"], "ekspozycja oznaczona ETH; ETH zmienia strukturę",
     "przeciwny ETH perp z bety", "odbudowa struktury / spadek jakości relacji"),
    ("CP_HEDGE_03", "Alt-Basket Market Beta", "basket_beta", "M15", [], {"factor": "BTC", "ratio": 0.5, "band": 0.25}, ["declared_exposure"],
     "≥ 2 alty; suma beta-exposure ponad limit", "jedna noga BTC", "rebalans po przekroczeniu pasma"),
    ("CP_HEDGE_04", "Two-Factor BTC/ETH Hedge", "two_factor", "M15", [], {"ratio": 0.5, "max_cond": 30.0}, ["declared_exposure"],
     "portfel altów z ekspozycją na BTC i ETH", "dwa notionals z modelu dwuczynnikowego", "brak stabilnego rozwiązania = NO_HEDGE"),
    ("CP_HEDGE_05", "Sector Relative-Value Protection", "residual_pair", "M15", [], {"z_in": 2.0, "z_out": 0.5, "window": 120}, ["declared_exposure", "partner_symbol"],
     "residual z-score log-cen > 2 przy dodatniej becie", "przeciwny perp drugiego instrumentu", "residual 0.5 / rozpad / timeout"),
    ("CP_HEDGE_06", "Volatility Shock Beta Shield", "crypto_vol_shock", "M1", [], {"pct": 0.95, "lookback": 200, "ratio": 0.5}, ["declared_exposure", "benchmark_btc"],
     "range BTC M1 > 95. percentyla z 200, close przeciw ekspozycji", "jednorazowy czasowy BTC hedge", "3 normalne zakresy / timeout"),
    ("CP_HEDGE_07", "Same-Underlying Cross-Market Hedge", "cross_market", "M15", [], {"basis_limit_bps": 50}, ["declared_exposure", "second_market_same_underlying"],
     "perp + drugi kontrakt tego samego underlying w innym namespace", "przeciwna noga w drugim rynku", "limit basis / koszt / timeout"),
    ("CP_HEDGE_08", "Owned Spot Inventory Hedge", "spot_inventory", "M15", [], {"ratio": 0.5}, ["declared_spot_inventory"],
     "zweryfikowane saldo spot + odpowiadający perp", "short perp do części inventory", "zmniejszenie inventory / limit margin"),
    ("CP_HEDGE_09", "Portfolio Stress-Loss Hedge", "stress_loss", "M15", [], {"scenarios": [-0.05, -0.10, -0.20], "loss_limit": None}, ["declared_exposure"],
     "strata scenariuszowa ponad limit", "do 2 instrumentów minimalizujących najgorszą stratę", "powrót do limitu"),
    ("CP_HEDGE_10", "Funding-Aware Hedge Selection", "funding_aware", "M15", [], {"holding_h": 8}, ["declared_exposure", "funding"],
     "ekspozycja wymaga hedge; ≥ 2 instrumenty spełniają warunek", "tańszy zestaw po fees i funding", "zmiana kosztów > koszt przebudowy"),
]
_OTC_HEDGE = [
    ("OTC_HEDGE_01", "Structure-Shift Protection", "otc_structure", "S15", [], {}, ["declared_otc_contracts", "otc_feed"], "cena nad strike, bearish CHoCH S15",
     "PUT z tym samym expiry, stake z planera", "gate dla skrajnych cen"),
    ("OTC_HEDGE_02", "Liquidity-Sweep Profit Protection", "otc_sweep", "S15", [], {}, ["declared_otc_contracts", "otc_feed"], "korzystny ruch, sweep oporu, bearish close",
     "PUT z nowym strike", "przedział między strikes sprawdzony"),
    ("OTC_HEDGE_03", "Volatility-Shock Protection", "otc_vol_shock", "S15", [], {"pct": 0.95, "lookback": 200}, ["declared_otc_contracts", "otc_feed"],
     "range S15 > 95. percentyla, close przeciw CALL", "jednorazowa przeciwna noga", "bez dokładania"),
    ("OTC_HEDGE_04", "Late-Expiry Risk Lock", "otc_late_lock", "S15", [], {"remaining": [0.25, 0.40]}, ["declared_otc_contracts", "otc_feed"],
     "pozostało 25–40% czasu, cena po korzystnej stronie", "PUT o identycznym końcu", "lock ujemnego wyniku widoczny"),
    ("OTC_HEDGE_05", "Payout Repricing Protection", "otc_payout_reprice", "S15", [], {}, ["declared_otc_contracts", "otc_payout"],
     "payout przeciwnej nogi wzrósł", "najmniejsza stawka dająca poprawę", "odrzuć nieaktualny payout"),
    ("OTC_HEDGE_06", "Momentum-Stall Protection", "otc_stall", "S15", [], {}, ["declared_otc_contracts", "otc_feed"], "3 S15 bez nowego high, body ≤ 0.3A",
     "częściowa przeciwna noga", "jedno uzbrojenie na ciąg"),
    ("OTC_HEDGE_07", "Same-Expiry Directional Basket", "otc_basket", "S15", [], {"limit": None}, ["declared_otc_contracts"], "≥ 2 CALL o wspólnym expiry ponad limit",
     "jedna zagregowana noga PUT", "limit grupy nie mnoży się"),
    ("OTC_HEDGE_08", "Expiry-Group Loss Budget", "otc_loss_budget", "S15", [], {"loss_limit": None}, ["declared_otc_contracts"], "maks. strata grupy ponad limit",
     "przeciwna noga minimalizująca przekroczenie", "NO_HEDGE gdy brak poprawy"),
    ("OTC_HEDGE_09", "Two-Step Corridor Protection", "otc_corridor", "S15", [], {"max_layers": 1}, ["declared_otc_contracts", "otc_feed"],
     "po 1. ochronie kolejny ruch ≥ 0.5A", "druga warstwa tylko przy jawnej konfiguracji", "domyślnie 1 warstwa"),
    ("OTC_HEDGE_10", "Mixed-Strike Residual Hedge", "otc_residual", "S15", [], {}, ["declared_otc_contracts"], "CALL i PUT o tym samym expiry, nierówny ogon",
     "najmniejsza noga zmniejszająca gorszy ogon", "zakaz naprzemiennego dokładania"),
]

_PROFILE_INPUTS = {"FOREX_MT5": ["mt5_closed_bars", "symbol_spec", "bid_ask"], "CRYPTO_FOMO_PERPS": ["hyperliquid_candles", "asset_meta", "mark_price"],
                   "OTC_GOLD_POCKETOPTION": ["gold_otc_feed", "otc_payout", "otc_expiries"]}
_MIN_HISTORY = {"SMC": 260, "SCALP": 230, "HEDGING": 260}


def _hash(d: dict) -> str:
    return hashlib.sha256(json.dumps(d, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _entry(basket: str, row: tuple, kind: str) -> dict:
    profile = {**BASKETS, **LEGACY_RETIRED_BASKETS}[basket][0]
    pdef = {**PROFILES, **LEGACY_RETIRED_PROFILES}[profile]
    otc = profile == "OTC_GOLD_POCKETOPTION"
    if kind == "HEDGING":
        sid, name, fam, tf, ctx, params, req, trig, plan, ext = row
        e = {"setup_rule": trig, "trigger_rule": trig, "entry_policy": "HEDGE_PLANNER: tylko istniejąca, zidentyfikowana ekspozycja; brak = NO_EXPOSURE",
             "cancellation_rule": ext, "plan_type": "HedgePlan", "exit_policy_or_expiry_policy": ext, "hedge_plan": plan,
             "regime_rule": "ochrona istniejącej ekspozycji (priorytet zasobów, ocena kosztu przez risk engine)"}
        params = {"timeout_bars": 6, "max_layers": 1, **params}
    else:
        sid, name, fam, tf, ctx, params, req, cg, setup, trig, cancel, *dd = row
        smc = kind == "SMC"
        e = {"setup_rule": setup, "trigger_rule": trig, "cancellation_rule": cancel,
             "entry_policy": ("CALL/PUT po potwierdzeniu, deadline = min(½ świecy, 10% D)" if otc else "wejście po potwierdzeniu na dostępnej cenie (bez fill po close)"),
             "regime_rule": {"SMC": "trend → continuation; range → sweep/reversal; zmiana struktury → reversal",
                             "SCALP": "trend → pullback/momentum; range → mean reversion; kompresja → wybicie"}[kind]}
        if otc:
            dsec = int(dd[0])
            e.update(plan_type="FixedExpiryPlan", exit_policy_or_expiry_policy=f"expiry D={dsec} s (obsługiwany termin w [0.8D, 1.2D]); unieważnienie dotyczy tylko sygnału przed otwarciem",
                     expiry_target_s=dsec)
        else:
            e.update(plan_type="PerpetualPlan" if profile == "CRYPTO_FOMO_PERPS" else "PositionPlan",
                     exit_policy_or_expiry_policy=("SL za unieważnieniem + b; TP1 = 2R, TP2 = 3R po 50%; timeout 20 świec" if smc else
                                                   "SL za ekstremum + b; TP1 = 1R, TP2 = 2R po 50%; timeout 8 świec"))
            params = {"tp_r": [2.0, 3.0] if smc else [1.0, 2.0], "partial": 0.5, "timeout_bars": 20 if smc else 8, **params}
        e["correlation_group"] = cg
    e.update(strategy_id=sid, name=name, version="1.0.0", basket_id=basket, profile_id=profile, family_id=fam, kind=kind,
             supported_product_types=pdef["products"], required_capabilities=["closed_bars"] + req,
             required_inputs=_PROFILE_INPUTS[profile] + req, signal_timeframe=tf, context_timeframes=ctx, min_history=_MIN_HISTORY[kind],
             parameter_schema=params, risk_policy=("wspólny budżet konta; ilość/stawka = null bez skonfigurowanego kapitału profilu"),
             model_feature_schema="BASKET-FEAT-1 (setup_score, model_agreement, p_event_raw – osobne pola)",
             reason_codes=["NO_SETUP", "WAITING_FOR_DATA", "WARMUP", "UNSUPPORTED_INPUT", "CONFLICT", "DUPLICATE_EVENT"] + (["NO_EXPOSURE", "NO_HEDGE"] if kind == "HEDGING" else []),
             detector_version=D.VERSION)
    if kind == "HEDGING":
        e["correlation_group"] = f"HEDGE_{basket}"
    e["config_hash"] = _hash({k: e[k] for k in ("strategy_id", "version", "family_id", "signal_timeframe", "context_timeframes", "parameter_schema")})
    return e


def strategies() -> list[dict]:
    """The 60 ACTIVE strategies (FX_* + CP_*), unchanged definitions / order / config hashes."""
    out = []
    for basket, rows in (("FX_SMC", _FX_SMC), ("FX_SCALP", _FX_SCALP), ("FX_HEDGE", _FX_HEDGE), ("CP_SMC", _CP_SMC), ("CP_SCALP", _CP_SCALP),
                         ("CP_HEDGE", _CP_HEDGE)):
        kind = BASKETS[basket][1]
        out += [_entry(basket, r, kind) for r in rows]
    return out


def _retired() -> list[dict]:
    out = []
    for basket, rows in (("OTC_SMC", _OTC_SMC), ("OTC_SCALP", _OTC_SCALP), ("OTC_HEDGE", _OTC_HEDGE)):
        out += [{**_entry(basket, r, LEGACY_RETIRED_BASKETS[basket][1]), "runtime_status": "RETIRED", "history_label": "RETIRED_OTC"} for r in rows]
    return out


CATALOG = strategies()
BY_ID = {s["strategy_id"]: s for s in CATALOG}
# TASK 020: the 30 retired OTC definitions - read-only labels for historical rows (journal / ROI / old snapshots). NOT a selection source.
HISTORICAL_STRATEGIES = {s["strategy_id"]: s for s in _retired()}


def retired_reason(strategy_id: str | None = None, *, basket_id: str | None = None, profile_id: str | None = None) -> str | None:
    """RETIRED_PROFILE / RETIRED_STRATEGY_ID for a retired OTC identifier, None for anything else (TASK 020)."""
    if profile_id and profile_id in RETIRED_PROFILE_IDS:
        return "RETIRED_PROFILE"
    if basket_id and basket_id in RETIRED_BASKET_IDS:
        return "RETIRED_STRATEGY_ID"
    if strategy_id and (strategy_id in HISTORICAL_STRATEGIES or str(strategy_id).startswith(RETIRED_STRATEGY_PREFIXES)):
        return "RETIRED_STRATEGY_ID"
    return None


def active_only(strategy_ids) -> list[str]:
    """Hard allowlist for every candidate consumer (SFB, rankers, rules, selectors): only ids of the active catalog survive."""
    return [s for s in strategy_ids if s in BY_ID]


def baskets() -> list[dict]:
    out = []
    for b, (profile, fam) in BASKETS.items():
        ids = [s["strategy_id"] for s in CATALOG if s["basket_id"] == b]
        out.append({"basket_id": b, "profile_id": profile, "family": fam, "strategy_ids": ids, "execution_capability": PROFILES[profile]["execution_capability"]})
    return out


def validate() -> dict:
    ids = [s["strategy_id"] for s in CATALOG]
    per = {b: sum(1 for s in CATALOG if s["basket_id"] == b) for b in BASKETS}
    fams = {b: len({s["family_id"] for s in CATALOG if s["basket_id"] == b}) for b in BASKETS}
    required = ("strategy_id", "version", "basket_id", "profile_id", "family_id", "correlation_group", "supported_product_types", "required_capabilities",
                "required_inputs", "signal_timeframe", "context_timeframes", "min_history", "parameter_schema", "regime_rule", "setup_rule", "trigger_rule",
                "entry_policy", "cancellation_rule", "plan_type", "exit_policy_or_expiry_policy", "risk_policy", "model_feature_schema", "reason_codes",
                "config_hash", "detector_version")
    missing = {s["strategy_id"]: [k for k in required if k not in s] for s in CATALOG if any(k not in s for k in required)}
    return {"total": len(ids), "unique": len(set(ids)), "baskets": len(per), "per_basket": per, "distinct_families_per_basket": fams, "missing_fields": missing,
            "retired_in_active": sorted(i for i in ids if retired_reason(i)),
            "profiles": len(PROFILES),
            "ok": len(ids) == 60 and len(set(ids)) == 60 and len(per) == 6 and len(PROFILES) == 2 and not any(retired_reason(i) for i in ids) and all(v == 10 for v in per.values()) and not missing and all(v == 10 for v in fams.values())}


def manifest() -> dict:
    return {"version": VERSION, "profiles": PROFILES, "baskets": baskets(), "strategies": CATALOG, "validation": validate(),
            "retired": {"profiles": sorted(RETIRED_PROFILE_IDS), "baskets": sorted(RETIRED_BASKET_IDS), "strategy_count": len(HISTORICAL_STRATEGIES),
                        "status": "RETIRED", "history": "PRESERVE_READ_ONLY"}}


# 1.46: preservation_view declared execution_route SIGNALS_ONLY for all 60, although the FX PositionPlans go to the SH path (AUTO_SH)
def _execution_route(s: dict, fx_execution: str) -> str:
    """The route a plan of this strategy really takes (mirrors BasketService._exec_status / sh_candidates): FOREX_MT5 PositionPlans
    -> the existing SH execution path when execution = AUTO_SH; hedge plans are plans only; CRYPTO = ticket for manual execution."""
    if s["plan_type"] == "HedgePlan":
        return "PLAN_ONLY"
    if s["profile_id"] == "FOREX_MT5" and s["plan_type"] == "PositionPlan":
        return "SH_PATH (AUTO_SH)" if fx_execution == "AUTO_SH" else "SIGNALS_ONLY"
    return "MANUAL_TICKET"


def preservation_view(fx_execution: str = "AUTO_SH") -> list[dict]:
    """For upgrade.preservation.compare(new_catalog=...): the 60 active canonical entries with their execution route and legacy aliases.
    No gold strategy is aliased into a basket (the multi-market strategies did not exist before 1.41), so no basket route duplicates
    the route of a preserved gold strategy. The FOREX_MT5 PositionPlans use the EXISTING SH path (1.42, no new parallel route);
    fx_execution = the baskets setting profiles.FOREX_MT5.execution (default AUTO_SH; SIGNALS_ONLY = 1.41 behaviour)."""
    return [{"strategy_id": s["strategy_id"], "basket_id": s["basket_id"], "legacy_aliases": [], "execution_route": _execution_route(s, fx_execution)}
            for s in CATALOG]
