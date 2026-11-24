"""`python -m masterquo train-all` - compatibility entry point of the 1.15 training pipeline (22_TRENUJ_WSZYSTKIE_MODELE.bat itself now
calls `training run` directly through tools/trening.cmd; this command keeps the old arguments working for own scripts).

Same mechanism as 00_TRENING_START.bat / TRENUJ_OBA.bat (masterquo/training): XAUUSD first, then BTC; export of the exact
broker symbol -> quality -> gold_candles -> scalp A/B/C -> legacy ML DT/XGB (APPROX only inside this job) -> lab families ->
activation of admitted models only -> reload of a running bot (never a second bot). Documented argument compatibility:
  --commission X     commission of XAUUSD per lot side (was used for every instrument - now XAUUSD only)
  --commission-btc   commission of BTC (otherwise from the account's deal history; unknown -> BTC scalp/ML skipped with reason)
  --months           history of the single export (--scalp-months is accepted and ignored)
  --ml-days, --lab-bars, --min-events, --ml-no-approx, --skip-candles (forecast + scalp_A + indicator_context), --skip-ml, --skip-lab,
  --quick (= profile TEST_INSTALACJI), --demo (synthetic terminal; technical models, never activated), --mt5-wait (ignored)
Nothing here sends orders; the execution mode is not touched; the bot's config is not changed (no persistent use_backfill_approx).
"""
from __future__ import annotations

from . import localapi
from .localapi import Bot  # noqa: F401 - 1.46 arch (I0075/I0080): the local-API client lives in masterquo/localapi.py; old name kept

# 1.46: LAB_FAMILIES / LAB_EXPERIMENTS and _wait removed - unused since train_all runs `training run` (families come from the training profile)


def say(msg: str) -> None:
    print(f"[Apollo23] {msg}", flush=True)


def _health(port: int) -> dict | None:
    """Old name (timeout 3 s as before); the one implementation is masterquo.localapi.health."""
    return localapi.health(port, 3)


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
