"""`python -m masterquo train-all` - compatibility entry point of the 1.15 training pipeline: an explicit SUBSET of `training run`.

1.46 (I0132): it is NOT what 22_TRENUJ_WSZYSTKIE_MODELE.bat does - the .bat calls `training run` without --tasks (every task of
training/runner.TASKS). train-all passes --tasks TRAIN_ALL_TASKS (10 model tasks; export, quality, activation and the bot reload always run);
scalp_B / scalp_C, sh_models, sh_pack, monte_carlo and master_models are trained only by `training run` without --tasks. The subset is
unchanged since 1.15 (extending it = which artifacts may be activated, an owner decision).
Same mechanism as 00_TRENING_START.bat / TRENUJ_OBA.bat (masterquo/training): XAUUSD first, then BTC; export of the exact
broker symbol -> quality -> the subset -> activation of admitted models only -> reload of a running bot (never a second bot).
Documented argument compatibility:
  --commission X     commission of XAUUSD per lot side (was used for every instrument - now XAUUSD only)
  --commission-btc   commission of BTC (otherwise from the account's deal history; unknown -> BTC scalp/ML skipped with reason)
  --months           history of the single export
  --ml-days, --lab-bars, --min-events, --ml-no-approx, --skip-candles (forecast + scalp_A + indicator_context),
  --skip-ml (ml + ml_scalp), --skip-lab (lab + neural_scalp + structure_intelligence + flow_context + context_indicators),
  --quick (= profile TEST_INSTALACJI), --demo (synthetic terminal; technical models, never activated)
  --scalp-months, --mt5-wait: deprecated, accepted and IGNORED (a console warning says so)
Nothing here sends orders; the execution mode is not touched; the bot's config is not changed (no persistent use_backfill_approx).
"""
from __future__ import annotations

import http.cookiejar
import json
import urllib.error
import urllib.request

# 1.46: LAB_FAMILIES / LAB_EXPERIMENTS and _wait removed - unused since train_all runs `training run` (families come from the training profile)

# 1.46 (I0132): the explicit subset of `training run` tasks (order and set unchanged) with the --skip-* flag that switches each off
TRAIN_ALL_TASKS = (("forecast", "skip_candles"), ("scalp_A", "skip_candles"), ("ml", "skip_ml"), ("lab", "skip_lab"),
                   ("indicator_context", "skip_candles"), ("ml_scalp", "skip_ml"), ("neural_scalp", "skip_lab"),
                   ("structure_intelligence", "skip_lab"), ("flow_context", "skip_lab"), ("context_indicators", "skip_lab"))
DEPRECATED_FLAGS = (("--scalp-months", "scalp_months"), ("--mt5-wait", "mt5_wait"))     # parsed for compatibility, never read


def say(msg: str) -> None:
    print(f"[Apollo23] {msg}", flush=True)


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


def train_all(a) -> int:
    from .training.cli import main as training_main
    for flag, attr in DEPRECATED_FLAGS:
        if getattr(a, attr, None) is not None:
            say(f"UWAGA: {flag} jest przestarzały i ignorowany (historia: --months; połączenie MT5 sprawdza `training run`)")
    tasks = [t for t, skip in TRAIN_ALL_TASKS if not getattr(a, skip)]
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
