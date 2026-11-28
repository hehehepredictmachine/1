"""PMW-FEAT-DICT-1: canonical feature dictionary (1.46 arch, I0021; docs/arch146/ETAP2_PROJEKT.md §3 features/catalog.py).

The same feature NAME means different formulas and units in different registries (range_rel = (H-L)/ATR14 in lab, (H-L)/C in mm;
ret_1 = simple return in lab, log return in mm, side-signed change / ATR in ml; RSI centred, in points, side-flipped or with another
seed; seven formulas of tick activity; signed vs absolute candle body; hour of the bar open, close or decision). Each registry is
consistent between its own training and inference, so no number is wrong today - the risk is joining or comparing features by name.

This module ONLY maps and documents. Nothing is recomputed, no artifact is renamed (artifacts keep their own names):
* CANONICAL  explicit entries: a canonical name carrying unit, window and seed (range_over_atr14_wilder, range_over_close, ret_log_1,
             ret_simple_1, rsi14_wilder_centered, ...), the formula, `impl` = the ONE function that computes it, and the aliases
             {registry: (old names)}. Two aliases share a canonical name only when the value formula is the same (tests compare the
             numbers); a different missing-value policy is an alias note, not another feature;
* every other registry name gets a registry-scoped entry '<registry>:<name>' (no equivalence claimed) with the registry's own metadata;
* resolve(registry, name) -> the entry (a timeframe prefix 'M5_' / 'H1_' of the ml and trainhub registries is the TF it is computed on).
Registries: lab (FS-1.0.0), mm (PMW-MM-FEATURES-1), ml (MQ-FEAT-1.3.0), trainhub (PMW-TH-FEAT-1), scalp (gold_candles_runtime
SCALP-FEAT-1.0.0).
"""
from __future__ import annotations

from dataclasses import dataclass, field

VERSION = "PMW-FEAT-DICT-1"
REGISTRIES = {
    "lab": "masterquo.lab.features.FEATURES (FS-1.0.0)",
    "mm": "masterquo.mm.features.FEATURES (PMW-MM-FEATURES-1)",
    "ml": "masterquo.ml.features.FEATURE_NAMES (MQ-FEAT-1.3.0)",
    "trainhub": "masterquo.trainhub.features.names(base_tf) (PMW-TH-FEAT-1)",
    "scalp": "gold_candles_runtime.scalp_features.FEATURES (SCALP-FEAT-1.0.0)",
}
TF_PREFIXED = ("ml", "trainhub")                       # names '<TF>_<base>': the base feature computed on that timeframe
TFS = ("M1", "M3", "M5", "M15", "M30", "H1", "H4", "D1")

ATR = "ATR14_wilder = Wilder RMA(14) of the true range seeded with the mean of the first 14 TR (TR[0] = H-L)"


@dataclass(frozen=True)
class Entry:
    name: str
    unit: str
    formula: str
    window: str
    seed: str
    impl: str                                          # dotted path of the ONE function computing it: 'module:function'
    aliases: dict = field(default_factory=dict)        # registry -> tuple of base names
    notes: str = ""


_LAB = "masterquo.lab.features:feature_matrix"
_MM = "masterquo.mm.features:features"
_ML = "masterquo.ml.features:tf_block"
_MLC = "masterquo.ml.features:compute"
_TH = "masterquo.trainhub.features:_base"
_SC = "gold_candles_runtime.scalp_features:build"

CANONICAL: tuple[Entry, ...] = (
    # ------------------------------------------------------------------ returns
    *(Entry(f"ret_simple_{k}", "relative return", f"C[i]/C[i-{k}] - 1", f"{k} bars", "-", _LAB, {"lab": (f"ret_{k}",)}) for k in (1, 3, 12)),
    *(Entry(f"ret_log_{k}", "log return", f"ln(C[i]/C[i-{k}])", f"{k} bars", "-", "masterquo.trainhub.features:_lr",
            {**({"mm": (f"ret_{k}",)} if k in (1, 3, 12) else {}), "trainhub": (f"r{k}",)},
            "mm.features.features liczy to samo wyrażeniem ln(C) - ln(C[-k])") for k in (1, 3, 6, 12)),
    *(Entry(f"ret_over_atr14_signed_{k}", "ATR", f"side * (C[i] - C[i-{k}]) / ATR14_wilder[i]; side = +1 LONG, -1 SHORT", f"{k} bars",
            ATR, _ML, {"ml": (f"ret{k}",)}, "znak zależny od kierunku setupu") for k in (1, 3, 12)),
    *(Entry(f"ret_over_atr14_{k}", "ATR", f"(C[i] - C[i-{k}]) / ATR14_wilder[i]", f"{k} bars", ATR, _SC, {"scalp": (f"ret{k}",)})
      for k in (1, 2, 3, 5, 10, 15)),
    # ------------------------------------------------------------------ range / volatility
    Entry("range_over_atr14_wilder", "ATR", "(H[i] - L[i]) / ATR14_wilder[i]", "14 bars", ATR, _LAB,
          {"lab": ("range_rel",), "ml": ("range_atr",), "trainhub": ("rng_atr",), "scalp": ("r_atr",)},
          "brak wartości: lab NaN przy ATR=0; ml NaN przy H==L; scalp 0 przy H==L (+ flaga zero_range)"),
    Entry("range_over_close", "relative", "(H[i] - L[i]) / C[i]", "0", "-", _MM, {"mm": ("range_rel",)}),
    Entry("atr14_over_close", "relative", "ATR14_wilder[i] / C[i]", "14 bars", ATR, _LAB,
          {"lab": ("atr_rel",), "mm": ("atr_rel_14",), "trainhub": ("atr_rel",)}),
    Entry("atr14_over_close_pct", "%", "100 * ATR14_wilder[i] / C[i]", "14 bars", ATR, _ML, {"ml": ("atr_pct",)}),
    Entry("atr14_over_close_bp", "bp", "1e4 * ATR14_wilder[i] / C[i]", "14 bars", ATR, _SC, {"scalp": ("atr_bp",)}),
    # ------------------------------------------------------------------ RSI
    Entry("rsi14_wilder_centered", "[-0.5, 0.5]", "strategies.indicators.rsi(C, 14)[i] / 100 - 0.5", "15 bars",
          "Wilder: średnie zysków/strat z pierwszych 14 zmian (C[1..14]-C[0..13])", _MM, {"mm": ("rsi_14",)}),
    Entry("rsi14_wilder_centered_th_seed", "[-0.5, 0.5]", "trainhub _rsi(C)[i] = RSI14 / 100 - 0.5", "15 bars",
          "Wilder z zalążkiem średnich o 1 świecę wcześniej (pierwsza zmiana = 0) - inne wartości niż rsi14_wilder_centered na początku "
          "historii (pomiar ETAP1: 2.96e-3 na świecy 14, 1.18e-5 na świecy 100)", "masterquo.trainhub.features:_rsi", {"trainhub": ("rsi14",)}),
    Entry("rsi14_wilder_points_side", "pkt 0-100", "RSI14 = strategies.indicators.rsi(C, 14)[i]; dla SHORT 100 - RSI14", "15 bars",
          "Wilder (strategies.indicators.rsi)", _ML, {"ml": ("rsi",)}, "odwrócone dla SHORT"),
    # ------------------------------------------------------------------ tick activity (tick volume = feed activity, not traded volume)
    Entry("tick_pct_rank100", "0-1", "udział świec okna TV[i-99..i] z TV < TV[i]", "100 bars", "-", _LAB, {"lab": ("tv_pct",)}),
    Entry("tick_log_ratio_median48", "log ratio", "ln(TV[i] / median(TV[i-47..i])); NaN gdy mediana 0", "48 bars (z bieżącą)", "-", _MM,
          {"mm": ("tv_rel_48",)}),
    Entry("tick_log_ratio_mean48_plus1", "log ratio", "ln((TV[i] + 1) / (mean(TV[i-47..i]) + 1))", "48 bars (z bieżącą)", "-", _TH,
          {"trainhub": ("tick_ratio",)}),
    Entry("tick_ratio_mean20_prev", "ratio", "TV[i] / mean(TV[i-20..i-1])", "20 poprzednich", "-", _ML, {"ml": ("tick_activity",)}),
    Entry("tick_log_ratio_median20_prev", "log ratio", "ln(TV[i] / median(TV[i-20..i-1])); 0 i tv_missing=1 gdy brak", "20 poprzednich", "-",
          _SC, {"scalp": ("tv_log_ratio",)}),
    # ------------------------------------------------------------------ candle body
    Entry("body_over_range_signed", "[-1, 1]", "(C[i] - O[i]) / (H[i] - L[i]); 0 gdy H==L", "0", "-", _MM, {"mm": ("body_rel",)}),
    Entry("body_over_range_abs", "0-1", "|C[i] - O[i]| / (H[i] - L[i])", "0", "-", _ML, {"ml": ("body",), "scalp": ("body_ratio",)},
          "brak wartości: ml NaN przy H==L; scalp 0 przy H==L (+ flaga zero_range)"),
    Entry("body_over_atr14_signed", "ATR", "(C[i] - O[i]) / ATR14_wilder[i]", "14 bars", ATR, _TH, {"trainhub": ("body_atr",)}),
    # ------------------------------------------------------------------ time of day
    Entry("hour_of_close_sin", "-", "sin(2*pi * godzina UTC zamknięcia świecy / 24)", "-", "-", _LAB,
          {"lab": ("hour_sin",), "trainhub": ("tod_sin",)}),
    Entry("hour_of_close_cos", "-", "cos(2*pi * godzina UTC zamknięcia świecy / 24)", "-", "-", _LAB,
          {"lab": ("hour_cos",), "trainhub": ("tod_cos",)}),
    Entry("hour_of_decision_sin", "-", "sin(2*pi * godzina UTC chwili decyzji asof / 24)", "-", "-", _MLC, {"ml": ("hour_sin",)}),
    Entry("hour_of_decision_cos", "-", "cos(2*pi * godzina UTC chwili decyzji asof / 24)", "-", "-", _MLC, {"ml": ("hour_cos",)}),
    Entry("hour_of_open_sin", "-", "sin(2*pi * godzina UTC OTWARCIA świecy / 24)", "-", "-", _SC, {"scalp": ("hour_sin",)}),
    Entry("hour_of_open_cos", "-", "cos(2*pi * godzina UTC OTWARCIA świecy / 24)", "-", "-", _SC, {"scalp": ("hour_cos",)}),
    # ------------------------------------------------------------------ Bollinger %b
    Entry("bb_pctb_sma20_2sd", "0-1 (poza pasmem <0 / >1)", "(C[i] - (SMA20 - 2*sd20)) / (4*sd20), sd populacyjne (ddof=0)", "20 bars", "-",
          _LAB, {"lab": ("bb_pctb",), "scalp": ("bb_pctb",)},
          "I0026: w lab bb_pctb = z20/4 + 0.5 - liniowa funkcja z20 (ta sama informacja dwa razy w FS-1.0.0); brak wartości: lab NaN przy "
          "sd ~ 0, scalp 0.5 gdy pasmo zerowe"),
)


def _split_tf(registry: str, name: str) -> tuple[str | None, str]:
    if registry in TF_PREFIXED and "_" in name:
        tf, base = name.split("_", 1)
        if tf in TFS:
            return tf, base
    return None, name


def registry_names() -> dict[str, list[str]]:
    """Live names of every registry (imports the registries; trainhub = names of every base TF)."""
    from gold_candles_runtime import scalp_features as SF

    from ..lab import features as LF
    from ..ml import features as MF
    from ..mm import features as MMF
    from ..trainhub import features as TF
    th: list[str] = []
    for b in TF.HTF_OF:
        th += [n for n in TF.names(b) if n not in th]
    return {"lab": list(LF.FEATURES), "mm": list(MMF.FEATURES), "ml": list(MF.FEATURE_NAMES), "trainhub": th, "scalp": list(SF.FEATURES)}


def _explicit_index() -> dict[tuple[str, str], Entry]:
    idx: dict[tuple[str, str], Entry] = {}
    for e in CANONICAL:
        for reg, names in e.aliases.items():
            for n in names:
                if (reg, n) in idx:
                    raise ValueError(f"DUPLICATE_ALIAS:{reg}:{n}")
                idx[(reg, n)] = e
    return idx


def _scoped(registry: str, base: str) -> Entry:
    """Registry-scoped entry of a name without an explicit canonical entry: its own definition only, no equivalence claimed."""
    unit, formula, impl = "-", "definicja w rejestrze " + REGISTRIES[registry], ""
    try:
        if registry == "mm":
            from ..mm import features as MMF
            m = MMF.FEATURES.get(base) or {}
            unit, formula, impl = m.get("unit", unit), m.get("formula", formula), _MM
        elif registry == "ml":
            from ..ml import features as MF
            d = {n: (u, txt) for n, u, txt in MF._TF_BLOCK}
            d.update({f["name"]: (f.get("unit", "-"), f.get("desc", "")) for f in MF.SCHEMA})
            if base in d:
                unit, formula = d[base][0], d[base][1] or formula
            impl = _ML if base in {n for n, _u, _t in MF._TF_BLOCK} else _MLC
        else:
            impl = {"lab": _LAB, "trainhub": _TH, "scalp": _SC}[registry]
    except ImportError:
        pass
    return Entry(f"{registry}:{base}", unit, formula, "-", "-", impl, {registry: (base,)}, "wpis zakresu rejestru – brak deklarowanej równoważności")


def resolve(registry: str, name: str) -> dict:
    """{canonical, tf, explicit, entry} of one registry name ('M5_ret1' -> base 'ret1' computed on M5)."""
    if registry not in REGISTRIES:
        raise KeyError(f"UNKNOWN_REGISTRY:{registry}")
    tf, base = _split_tf(registry, name)
    e = _explicit_index().get((registry, base))
    if e is None:
        e = _scoped(registry, base)
        return {"canonical": e.name, "tf": tf, "explicit": False, "entry": e}
    return {"canonical": e.name, "tf": tf, "explicit": True, "entry": e}


def dictionary() -> dict:
    """The whole dictionary: explicit entries + registry-scoped ones for every live registry name (metadata only)."""
    names = registry_names()
    out: dict[str, dict] = {}
    for reg, ns in names.items():
        for n in ns:
            r = resolve(reg, n)
            e = r["entry"]
            d = out.setdefault(e.name, {"name": e.name, "unit": e.unit, "formula": e.formula, "window": e.window, "seed": e.seed, "impl": e.impl,
                                        "notes": e.notes, "explicit": r["explicit"], "aliases": {}})
            base = _split_tf(reg, n)[1]
            if base not in d["aliases"].setdefault(reg, []):
                d["aliases"][reg].append(base)
    return {"version": VERSION, "registries": REGISTRIES, "entries": dict(sorted(out.items()))}
