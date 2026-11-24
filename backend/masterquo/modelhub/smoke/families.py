"""Smoke of the model families (modelhub/families, PMW-FAM-1) - area `families` of `python -m masterquo models check --smoke`.

One path per family, the same functions the CLI / panel / Training Center and the bot runtime call:

  SYNTHETIC_TEST data (FakeMT5 export into the marketdata Store through ctx.store; PAIR_COINT / STATARB legs written into the same
  Store with Store.merge; a synthetic book archive in the IndicatorService table book_snapshots; a synthetic labelled corpus imported
  with nlp.import_file)
  -> run.train(profile smoke; data read by run.load_data) -> artifact Store (SHA-256 verify)
  -> FamilyService.activate (re-load + the inference sample stored at training) -> ASSIST gate (a synthetic artifact is refused)
  -> FamilyService.predict (live bars of the FakeMT5 terminal through a bridge stand-in) -> PMW-PRED-2 + data_kind of the record.

PAIR_COINT / STATARB have no live data path for their legs (FamilyService.NO_LIVE_PATH -> DISABLED) and RL_PPO has no live position
(BLOCKED_DATA): the service state is checked as the documented one and the artifact is additionally predicted directly.
SEQ_LSTM / SEQ_GRU / RL_PPO need .venv_deep (deep_runtime worker process); without it they are NIEZWERYFIKOWANY, never a pass.
"""
from __future__ import annotations

import math
import time

from . import OK, Ctx, check, fail, ok, unverified

_LIVE_BARS = 760                     # closed bars of the bridge buffer: min(2000, max(500, 700 + 60))
_PAIR = ["XAUUSD", "BTC"]
_BASKET = ["XAUUSD", "BTC", "EURUSD"]
_T0 = 1_772_409_600                  # fixed epoch of the synthetic book archive (2026-03-02T00:00:00Z)
_BREAKOUT_STATES = {"NO_BREAKOUT", "BREAKOUT", "CONFIRMED", "RETEST", "FALSE_BREAKOUT", "TIMEOUT", "INVALIDATED"}


# ---------------------------------------------------------------------------------------------------------------- stand-ins of the sources
class _Bridge:
    """MarketBridge stand-in for FamilyService._live: closed bars of the FakeMT5 terminal in the bridge row format + its quote."""

    synthetic = True

    def __init__(self, ctx: Ctx, fake):
        self.ctx, self.fake = ctx, fake

    @property
    def quote(self) -> dict:
        t = self.fake.symbol_info_tick(self.fake.symbol)
        return {"bid": float(t.bid), "ask": float(t.ask)} if t else {}

    def bars(self, tf, limit=None, include_forming=True):
        return self.ctx.bars(tf, int(limit or _LIVE_BARS), history_days=40)


class _Indicators:
    """IndicatorService stand-in: current()['microstructure'] computed by indicators.ofi (normalize -> OFIAccumulator -> compute, as
    poll_book does) from the FakeMT5 market depth (market_book_get)."""

    def __init__(self, ctx: Ctx, fake):
        self.dir = ctx.data_dir / "indicators"
        self.fake = fake

    def current(self) -> dict:
        from ...indicators import ofi as OF
        from ..families.micro import live_ofi_window_s
        f = self.fake
        f.market_book_add(f.symbol)
        acc = OF.OFIAccumulator(window_s=live_ofi_window_s())
        t0, book = time.time(), None
        for k in range(3):
            book = OF.normalize(f.market_book_get(f.symbol), t0 + k)
            acc.add(book)
        return {"microstructure": OF.compute(book, acc, instrument="XAUUSD", broker_symbol=f.symbol, status="READY" if book else "NO_DATA",
                                             now=book["t"] if book else None)}


class _News:
    """News module stand-in: summary() with headlines only (the shape news/ returns), first seen `ages_s` seconds ago."""

    def __init__(self, ages_s=(600, 3600)):
        self.ages_s = ages_s

    def summary(self) -> dict:
        from ...indicators.contract import iso
        now = time.time()
        heads = ("Gold rallies as the dollar slips", "Bullion prices slump again")
        return {"news": [{"headline": h, "first_seen_at": iso(now - a)} for h, a in zip(heads, self.ages_s)]}


# ---------------------------------------------------------------------------------------------------------------- shared setup
def _env(ctx: Ctx) -> dict:
    env = getattr(ctx, "_families_env", None)
    if env is not None:
        return env
    import os

    from ...config import ConfigStore
    from ..families import base as B
    from ..families.service import FamilyService
    base = ctx.data_dir / "model_families"
    os.environ["PMW_FAMILIES_DIR"] = str(base)          # B.root() / the NLP corpus stay in the temporary data folder of the area
    ctx.store(timeframes=("M5", "H1"), lookback_days=30, history_days=40)     # MT5 export of the instrument: SYNTHETIC_TEST, point from symbol_spec
    fake = ctx.fake(40)
    store = B.Store(base)
    svc = FamilyService(ConfigStore(), _Bridge(ctx, fake), indicators=_Indicators(ctx, fake), news=_News(), store=store)
    env = {"store": store, "svc": svc, "fake": fake}
    ctx._families_env = env
    return env


def _store_legs(ctx: Ctx, names: list[str]) -> None:
    """PAIR_COINT / STATARB legs written into the marketdata Store with Store.merge (the exporter's storage call): synthetic H1 series tied
    log-linearly to the exported XAUUSD H1 closes plus noise. (An export of a second FakeMT5 market is not usable here:
    FakeMT5.copy_rates_range ignores the symbol, mt5/fake.py:468-474, so it would store the XAUUSD bars again.)"""
    import numpy as np

    from ...marketdata.store import Store
    st = Store()
    base = st.read(ctx.inst, "H1")
    t = [int(x) for x in base["time"]]
    la = np.log(np.asarray(base["close"], dtype=float))
    rel = {"BTC": ((la - 0.5) / 0.8, 1, 0.003), "EURUSD": (0.3 * la - 2.3, 2, 0.002)}
    for inst in names:
        if inst == ctx.inst or st.parts(inst, "H1"):
            continue
        x, seed, sd = rel[inst]
        c = np.exp(x + np.random.default_rng(seed).normal(0, sd, len(t)))
        st.merge(inst, "H1", [(t[i], float(c[i]), float(c[i]), float(c[i]), float(c[i]), 100, 10, 0, t[i] + 10800, 0) for i in range(len(t))])


def _legs_bars(names: list[str]) -> list[list[dict]]:
    from ...marketdata.store import Store
    from ..families import base as B
    st = Store()
    return [B.bars_from_store(st, s, "H1") for s in names]


def _books_db(ctx: Ctx, n: int = 6000) -> str:
    """Synthetic broker book archive (2 levels, 1 s) of the instrument's broker symbol in indicators.sqlite (IndicatorService schema)."""
    import json
    import sqlite3

    import numpy as np

    from ...indicators.service import SCHEMA
    p = ctx.data_dir / "indicators" / "indicators.sqlite"
    p.parent.mkdir(parents=True, exist_ok=True)
    sym = ctx.fake(40).symbol
    rng = np.random.default_rng(3)
    mid, rows = 2000.0, []
    for i in range(n):
        qb, qa = float(rng.integers(1, 10)), float(rng.integers(1, 10))
        rows.append((sym, float(_T0 + i), json.dumps([[mid - 0.05, qb], [mid - 0.15, 3.0]]), json.dumps([[mid + 0.05, qa], [mid + 0.15, 3.0]])))
        mid += 0.01 * float(np.sign(qb - qa)) + float(rng.normal(0, 0.002))
    con = sqlite3.connect(str(p))
    try:
        con.executescript(SCHEMA)
        con.execute("DELETE FROM book_snapshots WHERE symbol=?", (sym,))
        con.executemany("INSERT INTO book_snapshots(symbol, t, bids, asks) VALUES (?,?,?,?)", rows)
        con.commit()
    finally:
        con.close()
    return str(p)


def _corpus(ctx: Ctx, n: int = 600) -> dict:
    """Synthetic labelled corpus (JSONL in the temporary folder) imported with nlp.import_file - the corpus run.load_data reads."""
    import json

    import numpy as np

    from ..families import nlp as NL
    rng = np.random.default_rng(4)
    pos, neu, neg = (("gold rallies", "bullion surges", "strong demand lifts"), ("market waits", "traders eye data", "session opens quietly"),
                     ("gold plunges", "prices slump", "sell-off deepens"))
    p = ctx.data_dir / "nlp_corpus_synthetic.jsonl"
    with p.open("w", encoding="utf-8") as fh:
        for i in range(n):
            k = i % 3
            txt = (pos, neu, neg)[k][(i // 3) % 3] + f" item {i} " + " ".join(rng.choice(["today", "again", "now", "on fed"], 2))
            fh.write(json.dumps({"text": txt, "label": ("POSITIVE", "NEUTRAL", "NEGATIVE")[k], "source": "SYNTHETIC_TEST",
                                 "first_seen_at": f"2026-01-{1 + i % 28:02d}T00:{i % 60:02d}:00Z"}) + "\n")
    return NL.import_file(p, "SYNTHETIC_TEST")                  # 1.46 arch (I0469): the corpus records carry their own data kind


# ---------------------------------------------------------------------------------------------------------------- helpers
def _f(x, nd: int = 4) -> str:
    return f"{x:.{nd}g}" if isinstance(x, (int, float)) and not isinstance(x, bool) else str(x)


def _finite(*xs) -> bool:
    return all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in xs)


def _dist_err(d, keys) -> str | None:
    if not isinstance(d, dict) or any(k not in d for k in keys):
        return f"brak klas {keys} w {d}"
    if not _finite(*(d[k] for k in keys)) or abs(sum(d[k] for k in keys) - 1.0) > 1e-6:
        return f"rozkład nieznormalizowany: {d}"
    return None


def _where(exc: BaseException) -> str:
    """file:line of the innermost frame of the exception (relative to backend/)."""
    import traceback
    tb = traceback.extract_tb(exc.__traceback__)
    if not tb:
        return ""
    fr = tb[-1]
    fn = fr.filename.replace("\\", "/")
    return f"{fn.split('/backend/', 1)[-1]}:{fr.lineno}"


def _check_regression(rec: dict) -> tuple[str | None, str]:
    r = rec["result"]
    m, lo, hi = r.get("mean"), r.get("lo"), r.get("hi")
    if not _finite(m, lo, hi) or not lo <= m <= hi or sorted(r.get("horizons") or {}) != ["1", "3", "5"]:
        return f"wynik niespójny: mean={m}, lo={lo}, hi={hi}, horyzonty {sorted(r.get('horizons') or {})}", ""
    return None, f"log-zwrot h=1 mean={_f(m)} [{_f(lo)}, {_f(hi)}] (90%), horyzonty 1/3/5, cena {_f(r.get('price_now'), 6)}"


def _check_garch(rec: dict) -> tuple[str | None, str]:
    r = rec["result"]
    hb = (rec.get("horizon") or {}).get("bars")
    if not _finite(r.get("sigma"), r.get("sigma_bar")) or r["sigma"] <= 0 or r.get("scale") != "decimal":
        return f"wynik niespójny: sigma={r.get('sigma')}, scale={r.get('scale')}", ""
    if hb != r.get("horizon_bars"):
        return f"horyzont rekordu {hb} ≠ horyzont sigma w wyniku {r.get('horizon_bars')} (garch.py:105-110)", ""
    return None, f"sigma({hb} świec)={_f(r['sigma'])} (decimal), sigma_bar={_f(r['sigma_bar'])}, ruch 1σ={_f(r.get('price_move_1sigma'))}"


def _check_kalman(rec: dict) -> tuple[str | None, str]:
    r = rec["result"]
    if r.get("state") not in ("UP", "DOWN", "FLAT") or not _finite(r.get("level"), r.get("slope"), r.get("slope_var")) or r["slope_var"] < 0:
        return f"wynik niespójny: {r}", ""
    return None, f"stan {r['state']}, level={_f(r['level'], 6)}, slope={_f(r['slope'])}, slope_z={_f(r.get('slope_z'))}"


def _check_breakout(rec: dict) -> tuple[str | None, str]:
    r = rec["result"]
    if r.get("state") not in _BREAKOUT_STATES:
        return f"nieznany stan reguły: {r.get('state')}", ""
    return None, f"stan {r['state']}" + (f" {r.get('direction')}, krawędź {_f(r.get('edge'), 6)}, świec od zdarzenia {r.get('bars_since')}"
                                         if r["state"] != "NO_BREAKOUT" else "")


def _check_micro(rec: dict) -> tuple[str | None, str]:
    r = rec["result"]
    if r.get("classifier_state"):
        return f"klasyfikator reakcji niedostępny: {r.get('classifier_state')}: {r.get('classifier_reason')}", ""
    p = {"DOWN": r.get("p_down_10s"), "FLAT": r.get("p_flat_10s"), "UP": r.get("p_up_10s")}
    err = _dist_err(p, ("DOWN", "FLAT", "UP"))
    if err:
        return err, ""
    return None, (f"{r.get('capability')} (arkusz FakeMT5): best_imb={_f(r.get('best_imbalance'))}, depth_imb={_f(r.get('depth_imbalance'))}; "
                  f"klasyfikator 10 s P(down/flat/up)={_f(p['DOWN'], 3)}/{_f(p['FLAT'], 3)}/{_f(p['UP'], 3)}")


def _check_seq(rec: dict) -> tuple[str | None, str]:
    r = rec["result"]
    err = _dist_err(r, ("DOWN", "FLAT", "UP"))
    return err, "" if err else f"P(DOWN/FLAT/UP, H=6)={_f(r['DOWN'], 3)}/{_f(r['FLAT'], 3)}/{_f(r['UP'], 3)} (worker .venv_deep)"


def _check_nlp(rec: dict) -> tuple[str | None, str]:
    r = rec["result"]
    err = _dist_err(r.get("sentiment"), ("NEGATIVE", "NEUTRAL", "POSITIVE"))
    if err or r.get("texts") != 2:
        return err or f"liczba nagłówków {r.get('texts')} ≠ 2", ""
    s = r["sentiment"]
    return None, f"2 świeże nagłówki: NEG/NEU/POS={_f(s['NEGATIVE'], 3)}/{_f(s['NEUTRAL'], 3)}/{_f(s['POSITIVE'], 3)}"


def _nlp_old_news(ctx: Ctx, svc, fid: str) -> dict:
    """The same service path with headlines first seen 8-9 days ago (feed paused): the record must stay a usable state - READY with a
    normalised distribution, or a typed absence with its reason - never an internal contract error."""
    keep = svc.news
    svc.news = _News(ages_s=(8 * 86400, 9 * 86400))
    svc.invalidate(fid, ctx.inst)
    try:
        rec = svc.predict(fid, ctx.inst)
    finally:
        svc.news = keep
        svc.invalidate(fid, ctx.inst)
    st = rec.get("state") if rec else None
    if st == "READY":
        err = _dist_err((rec.get("result") or {}).get("sentiment"), ("NEGATIVE", "NEUTRAL", "POSITIVE"))
        return check(not err, "nagłówki sprzed 8-9 dni: READY, rozkład znormalizowany", f"nagłówki sprzed 8-9 dni: {err}")
    if st in ("BLOCKED_DATA", "STALE"):
        return ok(f"nagłówki sprzed 8-9 dni: {st} ({rec.get('unavailable_reason')})")
    return fail(f"nagłówki sprzed 8-9 dni -> {st}: {rec.get('unavailable_reason') if rec else None}; nlp.py:171 dzieli przez "
                "max(w.sum(), 1e-12) – wagi exp(-wiek/6 h) < 1e-12 po ~7 dniach, sentyment nie sumuje się do 1 -> ERROR zamiast braku świeżych danych")


# ---------------------------------------------------------------------------------------------------------------- direct predictions
def _direct_pair(ctx: Ctx, f, d, man) -> tuple[dict, str, dict]:
    """PAIR_COINT: the loaded artifact on the stored legs reproduces the z of the last common bar stored at training (sample.expected)."""
    smp = man.get("sample") or {}
    want, tol = (smp.get("expected") or {}).get("z_last"), float(smp.get("tolerance") or 0.0)
    res = f.predict(f.load(d), {"pair_bars": _legs_bars(_PAIR)})
    if not _finite(want, res.get("z")):
        return fail(f"brak z do porównania: z={res.get('z')}, z_last={want}"), "", {}
    diff = abs(res["z"] - want)
    note = (f"roundtrip: z z odczytanego artefaktu ({res['z']:.4g}) = z_last z treningu, diff {diff:.3g} (tol {tol}; activate tej próbki "
            "nie sprawdza – service.py:342-343)")
    return (check(diff <= tol + 1e-12, "", f"z po odczycie {res['z']:.6g} ≠ z_last z treningu {want:.6g} (diff {diff:.3g} > {tol})"), note,
            {"result": res, "data_time": res.get("last_common_time")})


def _direct_statarb(ctx: Ctx, f, d, man) -> tuple[dict, str, dict]:
    """STATARB has no inference sample (sample.expected None, pairs.py:155): the loaded artifact on the stored basket must give finite
    s-scores and weights normalised to gross 1."""
    legs = _legs_bars(_BASKET)
    res = f.predict(f.load(d), {"basket_bars": legs})
    good = len(res.get("s_scores") or []) == len(_BASKET) and _finite(*res["s_scores"], *res["weights"]) and abs(res["gross"] - 1.0) < 1e-9
    note = (f"brak próbki w manifeście (pairs.py:155) – odczyt + predykcja na koszyku z magazynu: s={[round(x, 3) for x in res['s_scores']]}, "
            f"gross={_f(res['gross'])}")
    return check(good, "", f"predykcja z odczytanego artefaktu niespójna: {res}"), note, {"result": res, "data_time": legs[0][-1]["t"]}


def _direct_ppo(ctx: Ctx, f, d, man) -> tuple[dict, str, dict]:
    """RL_PPO has no inference sample (rl.py:45): two separate loads of the artifact give the same policy output (deterministic)."""
    bars = ctx.bars("M5", _LIVE_BARS, history_days=40)
    live = {"bars": bars, "position": 0.0}
    r1, r2 = f.predict(f.load(d), live), f.predict(f.load(d), live)
    p1, p2 = r1["action_probabilities"], r2["action_probabilities"]
    diff = max(abs(p1[k] - p2[k]) for k in p1)
    err = _dist_err(p1, tuple(p1))
    pr = ", ".join(f"{k} {v:.3f}" for k, v in p1.items())
    note = f"brak próbki w manifeście (rl.py:45) – 2 odczyty polityki (worker .venv_deep, position=0.0): akcja {r1['action']}, P: {pr}, diff {diff:.3g}"
    return (check(not err and diff <= 1e-9 and r1["action"] == r2["action"], "", err or f"dwa odczyty dają inną politykę: {r1} vs {r2}"), note,
            {"result": r1, "data_time": bars[-1]["t"]})


# ---------------------------------------------------------------------------------------------------------------- the path of one family
def _family(ctx: Ctx, fid: str, **kw) -> dict:
    steps: dict = {}
    try:
        _path(ctx, fid, steps, **kw)
    except Exception as exc:  # noqa: BLE001 - a crash is a FAIL of the step being executed; the steps done before are kept
        steps[ctx.step] = fail(f"{type(exc).__name__}: {exc} ({_where(exc)})")
    return steps


def _path(ctx: Ctx, fid: str, steps: dict, *, src: str, cfg: dict | None = None, prepare=None, live_state: str = "READY", checker=None,
          direct=None, live_note: str = "", extra_predict=None) -> None:
    from ..families import base as B
    from ..families import run as RUN
    env = _env(ctx)
    store, svc = env["store"], env["svc"]
    f = svc.fams[fid]
    inst = ctx.inst
    if f.RUNTIME == "DEEP":
        ctx.step = "env"
        py = ctx.env_python(".venv_deep")
        if py is None:
            steps["env"] = unverified("brak .venv_deep (MQ_DEEP_PYTHON / <program>/.venv_deep) – trening i inferencja w workerze deep_runtime "
                                      "nie są sprawdzane; wynik nie jest udawany")
            return
        impl, why = f.implementation()                  # deep.available: health of the worker (torch / gymnasium / stable_baselines3)
        if impl != "AVAILABLE":
            steps["env"] = unverified(f".venv_deep niekompletne: {why}")
            return
        steps["env"] = ok(f".venv_deep: {py} (worker deep_runtime, zależności {', '.join(f.DEPS)} dostępne)")

    ctx.step = "train"
    cfg = dict(cfg or {})
    if prepare is not None:
        cfg.update(prepare(ctx) or {})
    t0 = time.monotonic()
    r = RUN.train(fid, inst, "smoke", cfg, store=store)
    if r.get("state") != "DONE":
        tail = (r.get("trace") or "").strip().splitlines()[-1:] or [""]
        steps["train"] = fail(f"run.train(profil smoke): {r.get('state')}: {r.get('reason')} {tail[0]}".strip())
        return
    rid = r["run_id"]
    d = store.run_dir(fid, inst, rid)
    man = B._read(d / "manifest.json", {}) or {}
    rows = (man.get("data") or {}).get("rows")
    steps["train"] = ok(f"run.train(profil smoke) DONE w {time.monotonic() - t0:.1f} s, run {rid}, walidacja {r.get('validation')} "
                        f"(technicznie, nie jakość); dane: {src}; data_kind {man.get('data_kind')}" + (f", świec {rows}" if rows else ""))

    ctx.step = "artifact"
    good, why = store.verify(fid, inst, rid)
    if not good:
        steps["artifact"] = fail(f"Store.verify: {why}")
        return
    a = svc.activate(fid, inst, rid)
    if not a.get("ok"):
        steps["artifact"] = fail(f"FamilyService.activate: {a.get('status')}: {a.get('reason')}")
        return
    chk = a.get("sample_check") or {}
    parts = [f"SHA-256 {len(man.get('files') or {})} plików OK, activate -> ACTIVE"]
    direct_rec = None
    if chk.get("checked"):
        parts.append(f"próbka inferencji po odczycie: max|diff| {_f(chk.get('max_abs_diff'), 3)} (tol {chk.get('tolerance')})")
    if direct is not None:
        verdict, note, direct_rec = direct(ctx, f, d, man)
        if verdict["status"] != OK:
            steps["artifact"] = fail(verdict["detail"])
            return
        parts.append(note)
    elif not chk.get("checked"):
        steps["artifact"] = fail(f"aktywacja bez sprawdzenia próbki inferencji: {chk.get('reason')}")
        return
    try:
        svc.set_use(fid, inst, "ASSIST")
        steps["artifact"] = fail("bramka ASSIST przepuściła artefakt na danych SYNTHETIC_TEST (base.py:278-285 assist_ok)")
        return
    except ValueError as exc:
        parts.append(f"ASSIST: odmowa zgodnie z bramką base.py:278-285 ({str(exc).split(' (')[0][:80]})")
    steps["artifact"] = ok("; ".join(parts))

    ctx.step = "predict"
    rec = svc.predict(fid, inst)
    if rec is None:
        steps["predict"] = fail("FamilyService.predict zwrócił None przy aktywnym artefakcie w roli SHADOW")
        return
    st = rec.get("state")
    if st != live_state:
        steps["predict"] = fail(f"FamilyService.predict: stan {st} ≠ oczekiwany {live_state}: {rec.get('unavailable_reason')}")
        return
    if st == "READY":
        err, summary = checker(rec)
        if err:
            steps["predict"] = fail(f"FamilyService.predict READY, ale {err}")
            return
        pred = ok(f"FamilyService.predict (bridge FakeMT5): READY, use {rec.get('use')}, {summary}, {_f(rec.get('compute_ms'))} ms")
    else:
        pred = ok(f"FamilyService.predict: {st} zgodnie z kodem ({live_note}): {rec.get('unavailable_reason')}; predykcja bezpośrednia "
                  "z odczytanego artefaktu READY (krok artifact)")
    if extra_predict is not None:
        more = extra_predict(ctx, svc, fid)
        pred = ok(f"{pred['detail']}; {more['detail']}") if more["status"] == OK else fail(f"{more['detail']} | świeże nagłówki: {pred['detail']}")
    steps["predict"] = pred

    ctx.step = "contract"
    recs = [rec]
    if direct_rec:                                      # the record the service would publish with the legs / the position (service.py:444)
        recs.append(f.pred(inst=inst, symbol=rec.get("symbol"), state="READY", result=direct_rec["result"], run_id=rid,
                           data_time=direct_rec["data_time"], data_kind=B.kind_class(man.get("data_kind")), extra={"use": rec.get("use")}))
    c = ctx.contract_step(recs)
    if c["status"] == OK and st == "READY":
        want = B.kind_class(man.get("data_kind"))
        if rec.get("data_kind") != want:
            c = fail(f"PMW-PRED-2 poprawny, ale data_kind rekordu {rec.get('data_kind')!r} ≠ {want!r} (manifest {man.get('data_kind')}): "
                     "service.py:435 przyjmuje tylko dosłowne 'REAL'/'SYNTHETIC' zamiast base.kind_class (base.py:50) – rekord z artefaktu "
                     "syntetycznego nie jest oznaczony i quant/checks.py:65-66 nie wykluczy go z migawki REAL")
    if c["status"] == OK and direct_rec:
        c = ok(f"{c['detail']} (rekord serwisu {st} + rekord READY z predykcji bezpośredniej przez {fid}.pred)")
    steps["contract"] = c


# ---------------------------------------------------------------------------------------------------------------- smoke functions
_SRC_M5 = "M5 z magazynu marketdata (eksport FakeMT5, run.load_data)"
_SRC_M5P = _SRC_M5 + ", punkt z symbol_spec"


def _ts_arima(ctx: Ctx) -> dict:
    return _family(ctx, "TS_ARIMA", src=_SRC_M5, checker=_check_regression)


def _ts_sarimax(ctx: Ctx) -> dict:
    return _family(ctx, "TS_SARIMAX", src="H1 z magazynu marketdata (eksport FakeMT5, run.load_data), exog kalendarza sesji",
                   checker=_check_regression)


def _vol_garch(ctx: Ctx) -> dict:
    return _family(ctx, "VOL_GARCH", src=_SRC_M5, checker=_check_garch)


def _microstructure(ctx: Ctx) -> dict:
    return _family(ctx, "MICROSTRUCTURE", src="archiwum arkusza book_snapshots (syntetyczne, 6000 snapshotów, run.books_from_archive)",
                   prepare=lambda c: {"indicators_db": _books_db(c)}, checker=_check_micro)


def _pair_coint(ctx: Ctx) -> dict:
    def prep(c):
        _store_legs(c, _PAIR)
        return {"pairs": [list(_PAIR)]}
    return _family(ctx, "PAIR_COINT", src="nogi H1 XAUUSD (eksport FakeMT5) + BTC (syntetyczna, Store.merge) z magazynu, run.load_data MULTI_SERIES",
                   prepare=prep, live_state="DISABLED", direct=_direct_pair, live_note="NO_LIVE_PATH, service.py:29-30,413-416")


def _statarb(ctx: Ctx) -> dict:
    def prep(c):
        _store_legs(c, _BASKET)
        return {"basket": list(_BASKET)}
    return _family(ctx, "STATARB", src="koszyk H1 XAUUSD (eksport FakeMT5) + BTC + EURUSD (syntetyczne, Store.merge), run.load_data MULTI_SERIES",
                   prepare=prep, live_state="DISABLED", direct=_direct_statarb, live_note="NO_LIVE_PATH, service.py:29-30,413-416")


def _kalman_ls(ctx: Ctx) -> dict:
    return _family(ctx, "KALMAN_LS", src=_SRC_M5, checker=_check_kalman)


def _breakout(ctx: Ctx) -> dict:
    return _family(ctx, "BREAKOUT", src=_SRC_M5P, checker=_check_breakout)


def _seq_lstm(ctx: Ctx) -> dict:
    return _family(ctx, "SEQ_LSTM", src=_SRC_M5P, checker=_check_seq)


def _seq_gru(ctx: Ctx) -> dict:
    return _family(ctx, "SEQ_GRU", src=_SRC_M5P, checker=_check_seq)


def _rl_ppo(ctx: Ctx) -> dict:
    return _family(ctx, "RL_PPO", src=_SRC_M5P, live_state="BLOCKED_DATA", direct=_direct_ppo,
                   live_note="brak źródła pozycji w FamilyService._live, service.py:370-386; rl.py:54-58")


def _nlp_sentiment(ctx: Ctx) -> dict:
    def prep(c):
        imp = _corpus(c)
        if imp.get("total", 0) < 300:
            raise RuntimeError(f"import korpusu nlp.import_file: {imp}")
        return {}
    return _family(ctx, "NLP_SENTIMENT", src="korpus syntetyczny 600 tekstów zaimportowany nlp.import_file (run.load_data TEXT)",
                   prepare=prep, checker=_check_nlp, extra_predict=_nlp_old_news)


SMOKES = {
    "family:TS_ARIMA": _ts_arima,
    "family:TS_SARIMAX": _ts_sarimax,
    "family:VOL_GARCH": _vol_garch,
    "family:MICROSTRUCTURE": _microstructure,
    "family:PAIR_COINT": _pair_coint,
    "family:STATARB": _statarb,
    "family:KALMAN_LS": _kalman_ls,
    "family:BREAKOUT": _breakout,
    "family:SEQ_LSTM": _seq_lstm,
    "family:SEQ_GRU": _seq_gru,
    "family:RL_PPO": _rl_ppo,
    "family:NLP_SENTIMENT": _nlp_sentiment,
}
