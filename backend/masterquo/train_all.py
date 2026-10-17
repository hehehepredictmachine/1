"""`python -m masterquo train-all` (22_TRENUJ_WSZYSTKIE_MODELE.bat): trains every model family of the bot in one run and hands
the results to the running bot so all of them work immediately.

Order (each step reuses the existing, tested path; a blocked step never stops the next one):
  1. bot running? - otherwise it is started in the background (`serve --no-browser`) and the script waits for MT5;
  2. gold_candles forecasts: export-candles -> gold_candles_runtime.plan_train --latest (activates) -> /forecast/reload;
  3. scalp ML/NN (A/B/C): export-scalp -> gold_candles_runtime.scalp_train --latest (activates) -> scalp-replay report;
  4. ML Decision Tree / XGBoost: /ml/backfill (history) -> /ml/train (validation blocks decide; champion/challenger rules);
  5. lab models for XAUUSD and BTC (all families incl. MiniRocket, ResNet1D, SEW-SNN): /lab/train with artifact_family=ALL
     - every family is saved and the bot runs all of them on each closed M5 bar;
  6. the previously active asset is restored; report data/logs/trening_wszystkiego_<czas>.json.
Nothing here sends orders; Execution Lock is not touched.
"""
from __future__ import annotations

import http.cookiejar
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from . import paths

LAB_FAMILIES = ["DUMMY", "RULE", "LOGREG", "TREE", "MINIROCKET", "XGB", "RESNET1D", "SEW_SNN"]
LAB_EXPERIMENTS = ["LOGREG_PCA", "LOGREG_GMM_AUG", "LOGREG_NEUTRALIZED"]


def say(msg: str) -> None:
    print(f"[PepeMarketWizard] {msg}", flush=True)


class Bot:
    """Same-origin client of the local API (session cookie + CSRF token, as the monitor uses)."""

    def __init__(self, port: int):
        self.base = f"http://127.0.0.1:{port}"
        self.jar = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.csrf = None

    def _req(self, method: str, path: str, body=None, timeout: float = 30):
        data = None if body is None else json.dumps(body).encode()
        r = urllib.request.Request(self.base + path, data=data, method=method)
        r.add_header("Origin", self.base)
        if data is not None:
            r.add_header("Content-Type", "application/json")
        if self.csrf and method != "GET":
            r.add_header("X-MQ-CSRF", self.csrf)
        try:
            with self.op.open(r, timeout=timeout) as resp:
                txt = resp.read().decode("utf-8", "replace")
                return resp.status, (json.loads(txt) if txt.strip().startswith(("{", "[")) else txt)
        except urllib.error.HTTPError as e:
            txt = e.read().decode("utf-8", "replace")
            try:
                return e.code, json.loads(txt)
            except ValueError:
                return e.code, txt

    def login(self) -> None:
        self._req("GET", "/")
        st, j = self._req("GET", "/api/v1/session")
        if st != 200 or not isinstance(j, dict):
            raise RuntimeError(f"SESSION_FAILED {st}")
        self.csrf = j.get("csrf")

    def get(self, path, timeout=30):
        return self._req("GET", path, timeout=timeout)

    def post(self, path, body=None, timeout=60):
        return self._req("POST", path, body or {}, timeout=timeout)


def _health(port: int) -> dict | None:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/v1/health", timeout=3) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


def _wait(pred, timeout: float, step: float = 2.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            if pred():
                return True
        except Exception:
            pass
        time.sleep(step)
    return False


def _candles_python() -> str | None:
    env = os.environ.get("MQ_CANDLES_PYTHON")
    if env and Path(env).exists():
        return env
    for p in (paths.ROOT_DIR / ".venv_candles" / "Scripts" / "python.exe", paths.ROOT_DIR / ".venv_candles" / "bin" / "python"):
        if p.exists():
            return str(p)
    return None


def _run(cmd: list[str], env: dict | None = None, timeout: float = 4 * 3600) -> int:
    say("uruchamiam: " + " ".join(Path(c).name if i == 0 else c for i, c in enumerate(cmd)))
    try:
        return subprocess.run(cmd, cwd=str(paths.ROOT_DIR / "backend"), env=env, timeout=timeout).returncode
    except subprocess.TimeoutExpired:
        return 124


def train_all(a) -> int:
    from .__main__ import _port
    port = _port()
    report: dict = {"started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "steps": []}

    def step(name: str, status: str, **kw):
        report["steps"].append({"step": name, "status": status, **kw})
        say(f"{'OK ' if status == 'OK' else status + ' '}– {name}" + (f": {kw.get('detail')}" if kw.get("detail") else ""))

    # ---------------------------------------------------------------- 1. bot
    h = _health(port)
    if not h:
        say("Bot nie działa – uruchamiam go w tle (serve --no-browser)…")
        log = open(paths.data_dir() / "logs" / "train_all_server.log", "a", encoding="utf-8") if (paths.data_dir() / "logs").exists() else subprocess.DEVNULL
        kw = {"creationflags": getattr(subprocess, "CREATE_NEW_CONSOLE", 0)} if os.name == "nt" else {"start_new_session": True}
        cmd = [sys.executable, "-m", "masterquo", "serve", "--no-browser"] + (["--demo"] if a.demo else [])
        subprocess.Popen(cmd, cwd=str(paths.ROOT_DIR / "backend"), stdout=log, stderr=subprocess.STDOUT, **kw)
        if not _wait(lambda: _health(port), 180, 1.0):
            step("start bota", "BŁĄD", detail="bot nie odpowiedział w 3 min – sprawdź 03_START_MASTERQUO.bat")
            return _finish(report, 2)
    bot = Bot(port)
    bot.login()
    st = bot.get("/api/v1/state")[1]
    if not _wait(lambda: (bot.get("/api/v1/state")[1].get("connection") or {}).get("state") == "CONNECTED", a.mt5_wait, 3):
        step("połączenie MT5", "BŁĄD", detail="MT5 niepołączony – uruchom i zaloguj terminal, potem ponów")
        return _finish(report, 2)
    st = bot.get("/api/v1/state")[1]
    synthetic = bool(st.get("synthetic"))
    step("bot i MT5", "OK", detail=f"{st.get('symbol', {}).get('symbol')} · {'DANE SYNTETYCZNE' if synthetic else 'MT5'}")
    report["synthetic"] = synthetic
    orig_asset = (st.get("assets") or {}).get("active") or "XAUUSD"

    # ---------------------------------------------------------------- 2-3. forecasts + scalp (separate processes, direct MT5)
    cpy = _candles_python()
    env = dict(os.environ, PYTHONPATH=str(paths.ROOT_DIR / "backend"))
    if a.skip_candles:
        step("prognozy gold_candles + scalp", "POMINIĘTE", detail="--skip-candles")
    elif synthetic:
        step("prognozy gold_candles + scalp", "POMINIĘTE", detail="tryb demo: eksport historii wymaga prawdziwego MT5")
    else:
        rc = _run([sys.executable, "-m", "masterquo", "export-candles", "--months", str(a.months)], env)
        step("eksport historii M5/M30 (prognozy)", "OK" if rc == 0 else "BŁĄD", rc=rc)
        if cpy is None:
            step("trening prognoz gold_candles", "POMINIĘTE", detail="brak .venv_candles – uruchom 10_PROGNOZY_INSTALUJ.bat")
        elif rc == 0:
            rc2 = _run([cpy, "-m", "gold_candles_runtime.plan_train", "--latest"], env)
            step("trening prognoz gold_candles", "OK" if rc2 == 0 else "BLOKADA", rc=rc2,
                 detail=None if rc2 == 0 else "np. za mało danych – szczegóły w oknie powyżej")
            if rc2 == 0:
                bot.post("/api/v1/forecast/reload")
        rc = _run([sys.executable, "-m", "masterquo", "export-scalp", "--months", str(a.scalp_months)], env)
        step("eksport historii M1–H1 (scalp)", "OK" if rc == 0 else "BŁĄD", rc=rc)
        if cpy is None:
            step("trening scalp ML/NN", "POMINIĘTE", detail="brak .venv_candles – uruchom 10_PROGNOZY_INSTALUJ.bat")
        elif rc == 0:
            rc2 = _run([cpy, "-m", "gold_candles_runtime.scalp_train", "--latest", "--commission-per-lot-side", str(a.commission)], env)
            step("trening scalp ML/NN (modele A/B/C)", "OK" if rc2 == 0 else "BLOKADA", rc=rc2,
                 detail=None if rc2 == 0 else "np. BLOCKED_NO_REAL_DATA / INSUFFICIENT_DATA")
            rc3 = _run([sys.executable, "-m", "masterquo", "scalp-replay", "--commission-per-lot-side", str(a.commission), "--variants"], env)
            step("replay scalp (raport wariantów)", "OK" if rc3 == 0 else "BŁĄD", rc=rc3)

    # ---------------------------------------------------------------- 4. ML DT / XGBoost
    if a.skip_ml:
        step("ML Decision Tree / XGBoost", "POMINIĘTE", detail="--skip-ml")
    else:
        if orig_asset != "XAUUSD":
            bot.post("/api/v1/assets/active", {"asset": "XAUUSD"})
        if not a.ml_no_approx:                 # history-reconstructed samples (quality APPROX) are needed for a first training
            s, _ = bot._req("PUT", "/api/v1/config", {"ml": {"use_backfill_approx": True}})
            step("ML: próbki z historii (APPROX) włączone do treningu", "OK" if s == 200 else "BŁĄD",
                 detail="jawna decyzja treningu wszystkich modeli; wyłączysz: --ml-no-approx lub Ustawienia ML")
        s, j = bot.post("/api/v1/ml/backfill", {"days": a.ml_days})
        if s == 200 and isinstance(j, dict) and j.get("started"):
            _wait(lambda: (bot.get("/api/v1/ml/status")[1].get("backfill") or {}).get("status") in ("DONE", "FAILED"), 3 * 3600, 5)
        bf = bot.get("/api/v1/ml/status")[1].get("backfill") or {}
        step("ML: próbki z historii (backfill)", "OK" if bf.get("status") == "DONE" else "BLOKADA", detail=json.dumps(bf.get("result") or bf.get("reason"), default=str)[:200])
        s, j = bot.post("/api/v1/ml/train")
        if s == 200 and isinstance(j, dict) and j.get("started"):
            _wait(lambda: not bot.get("/api/v1/ml/status")[1].get("job"), 4 * 3600, 10)
            mst = bot.get("/api/v1/ml/status")[1]
            step("ML: trening DT + XGBoost", "OK", detail=f"status {mst.get('status')} · champion {((mst.get('champion') or {}) if isinstance(mst.get('champion'), dict) else mst.get('champion'))}"[:200])
        else:
            step("ML: trening DT + XGBoost", "BLOKADA", detail=(j.get("reason") if isinstance(j, dict) else str(j))[:200])

    # ---------------------------------------------------------------- 5. lab models for both assets
    fams = LAB_FAMILIES if not a.quick else ["DUMMY", "LOGREG", "SEW_SNN"]
    exps = LAB_EXPERIMENTS if not a.quick else []
    for asset in ("XAUUSD", "BTC"):
        if a.skip_lab:
            step(f"modele lab {asset}", "POMINIĘTE", detail="--skip-lab")
            continue
        s, j = bot.post("/api/v1/assets/active", {"asset": asset})
        if s != 200:
            step(f"modele lab {asset}", "BLOKADA", detail=f"brak symbolu {asset} na rachunku ({j})"[:200])
            continue
        if not _wait(lambda: bot.get(f"/api/v1/lab?asset={asset}")[1].get("modules") and not bot.get(f"/api/v1/lab?asset={asset}")[1].get("stale"), a.mt5_wait, 3):
            step(f"modele lab {asset}", "BLOKADA", detail="brak świeżych danych po przełączeniu aktywa")
            continue
        s, j = bot.post("/api/v1/lab/train", {"asset": asset, "families": fams, "experiments": exps, "artifact_family": "ALL",
                                              "bars": a.lab_bars, "min_events": a.min_events})
        if s != 200 or not (isinstance(j, dict) and j.get("started")):
            step(f"modele lab {asset}", "BLOKADA", detail=str(j)[:200])
            continue
        jid = j["job_id"]

        def job():
            return next((x for x in bot.get("/api/v1/lab/jobs")[1]["jobs"] if x["job_id"] == jid), {})
        last = [0.0]

        def done():
            jj = job()
            if time.monotonic() - last[0] > 60:
                last[0] = time.monotonic()
                say(f"  {asset}: {jj.get('progress')}/{jj.get('total')} {jj.get('stage')}")
            return jj.get("status") in ("COMPLETED", "FAILED", "CANCELLED")
        _wait(done, 8 * 3600, 5)
        jj = job()
        step(f"modele lab {asset} (wszystkie rodziny)", "OK" if jj.get("status") == "COMPLETED" else "BŁĄD",
             detail=f"werdykt {jj.get('verdict')} · artefakty {len(jj.get('model_ids') or [])} · {jj.get('error') or ''}"[:200],
             verdict=jj.get("verdict"), models=jj.get("model_ids"))
    if not a.skip_lab or not a.skip_ml:
        bot.post("/api/v1/assets/active", {"asset": orig_asset})
        step("przywrócenie aktywa", "OK", detail=orig_asset)
    return _finish(report, 0 if not any(s["status"] == "BŁĄD" for s in report["steps"]) else 2)


def _finish(report: dict, rc: int) -> int:
    report["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    d = paths.data_dir() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"trening_wszystkiego_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    f.write_text(json.dumps(report, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    say("PODSUMOWANIE:")
    for s in report["steps"]:
        say(f"  {s['status']:<10} {s['step']}" + (f" – {s['detail']}" if s.get("detail") else ""))
    say(f"Raport: {f}")
    say("Wytrenowane modele działają w bocie (tryb cienia – bez zleceń). Pulpit → „Wszystkie modele”; ML/prognozy/scalp w swoich zakładkach.")
    return rc
