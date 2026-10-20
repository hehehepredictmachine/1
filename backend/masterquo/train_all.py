"""`python -m masterquo train-all` (22_TRENUJ_WSZYSTKIE_MODELE.bat) - compatibility entry point of the 1.15 training pipeline.

Same mechanism as 00_TRENING_START.bat / TRENUJ_OBA.bat (masterquo/training): XAUUSD first, then BTC; export of the exact
broker symbol -> quality -> gold_candles -> scalp A/B/C -> legacy ML DT/XGB (APPROX only inside this job) -> lab families ->
activation of admitted models only -> reload of a running bot (never a second bot). Documented argument compatibility:
  --commission X     commission of XAUUSD per lot side (was used for every instrument - now XAUUSD only)
  --commission-btc   commission of BTC (otherwise from the account's deal history; unknown -> BTC scalp/ML skipped with reason)
  --months           history of the single export (--scalp-months is accepted and ignored)
  --ml-days, --lab-bars, --min-events, --ml-no-approx, --skip-candles (forecast + scalp), --skip-ml, --skip-lab,
  --quick (= profile TEST_INSTALACJI), --demo (synthetic terminal; technical models, never activated), --mt5-wait (ignored)
Nothing here sends orders; Execution Lock is not touched; the bot's config is not changed (no persistent use_backfill_approx).
"""
from __future__ import annotations

import http.cookiejar
import json
import time
import urllib.error
import urllib.request


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


def train_all(a) -> int:
    from .training.cli import main as training_main
    tasks = [t for t, skip in (("forecast", a.skip_candles), ("scalp_A", a.skip_candles), ("ml", a.skip_ml), ("lab", a.skip_lab),
                               ("indicator_context", a.skip_candles), ("ml_scalp", a.skip_ml), ("neural_scalp", a.skip_lab),
                               ("structure_intelligence", a.skip_lab), ("flow_context", a.skip_lab),
                               ("context_indicators", a.skip_lab)) if not skip]
    argv = ["run", "--instruments", a.instruments, "--profile", "TEST_INSTALACJI" if a.quick else "PELNY_TRENING", "--origin", "train-all",
            "--tasks", ",".join(tasks) or "none"]
    for flag, v in (("--months", a.months), ("--commission-xauusd", a.commission), ("--commission-btc", a.commission_btc), ("--ml-days", a.ml_days),
                    ("--lab-bars", a.lab_bars), ("--min-events", a.min_events)):
        if v is not None:
            argv += [flag, str(v)]
    if a.ml_no_approx:
        argv.append("--no-approx")
    if a.demo:
        argv.append("--demo")
    say("trening przez wspólny mechanizm (masterquo training run): " + " ".join(argv[1:]))
    return training_main(argv)
