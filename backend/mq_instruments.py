"""Instrument profiles shared by the bot (.venv) and the training runtime (.venv_candles) - stdlib only.

The active training/inference instrument is passed explicitly (argument) or through MQ_INSTRUMENT (subprocesses). Data of each
instrument lives in its own space: XAUUSD keeps the historical paths (data/forecast, data/scalp, data/ml) so existing models stay
readable; every other instrument uses data/instruments/<INST>/<kind>. Nothing here guesses a broker symbol from its name alone.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "instruments_v1.json"
DEFAULT = "XAUUSD"


def profiles() -> dict:
    return json.loads(CONFIG.read_text(encoding="utf-8"))["instruments"]


def profile(inst: str) -> dict:
    p = profiles()
    if inst not in p:
        raise ValueError(f"UNKNOWN_INSTRUMENT:{inst}")
    return p[inst]


def current(inst: str | None = None) -> str:
    v = inst or os.environ.get("MQ_INSTRUMENT") or DEFAULT
    profile(v)
    return v


def data_dir() -> Path:
    return Path(os.environ.get("MASTERQUO_DATA_DIR") or default_data_dir())


def default_data_dir(root: Path = ROOT) -> Path:
    """Data folder without MASTERQUO_DATA_DIR. In the folder of the Windows app (PepeMarketWizardDesktop.exe next to the program)
    the same rules as desktop/layout.go apply, so .bat scripts, the launcher and the app share one data folder:
    PMW_HOME, then portable.txt (data next to the program), then %LOCALAPPDATA%\\PepeMarketWizard. Classic folder: <root>/data."""
    if not (root / "PepeMarketWizardDesktop.exe").exists():
        return root / "data"
    if os.environ.get("PMW_HOME"):
        return Path(os.environ["PMW_HOME"]) / "data"
    if (root / "portable.txt").exists():
        return root / "data"
    if os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "PepeMarketWizard" / "data"
    return Path(os.environ.get("HOME") or Path.home()) / ".local" / "share" / "PepeMarketWizard" / "data"


def root(kind: str, inst: str | None = None) -> Path:
    """kind: forecast | scalp | ml | lab_datasets | training ..."""
    i = current(inst)
    d = data_dir() / kind if i == DEFAULT else data_dir() / "instruments" / i / kind
    d.mkdir(parents=True, exist_ok=True)
    return d


def file_prefix(inst: str | None = None) -> str:
    return profile(current(inst))["file_prefix"]


def check_metadata(inst: str, meta: dict) -> tuple[bool, list[str]]:
    """Metadata of a terminal symbol vs the instrument profile. Returns (ok, problems). USD and USDT stay different quote
    currencies: the quote currency is recorded with the dataset, never rewritten."""
    p = profile(inst)
    md = p["metadata"]
    base, prof = str(meta.get("currency_base") or "").upper(), str(meta.get("currency_profit") or "").upper()
    name = str(meta.get("name") or "").upper()
    text = " ".join(str(meta.get(k) or "") for k in ("name", "description", "path")).upper()
    problems = []
    if base in md["forbidden_base"] or any(f in name for f in md["forbidden_base"]):
        problems.append(f"LOOKALIKE_BASE_{base if base in md['forbidden_base'] else name}")
    elif base not in md["currency_base"]:
        # Many CFD brokers report currency_base = the account/quote currency (e.g. gold "XAUUSD-": base=USD, profit=USD). Accept that
        # only when base == profit currency AND the symbol name itself carries the instrument (name hint), never from description alone.
        cfd = base and base == prof and any(h in name for h in p["name_hints"]) and any(h in text for h in p["name_hints"])
        if not cfd:
            problems.append(f"BASE_{base or 'UNKNOWN'}_NOT_{'/'.join(md['currency_base'])}")
    if prof not in md["currency_profit"]:
        problems.append(f"PROFIT_{prof or 'UNKNOWN'}_NOT_{'/'.join(md['currency_profit'])}")
    return (not problems), problems


def candidates(inst: str, symbols: list[dict]) -> list[dict]:
    """Terminal symbols that may be this instrument: metadata match first, then name hints; look-alikes excluded."""
    p = profile(inst)
    out = []
    for s in symbols:
        name = str(s.get("name") or "")
        ok, probs = check_metadata(inst, s)
        named = any(h in name.upper() for h in p["name_hints"])
        if any(pr.startswith("LOOKALIKE") for pr in probs) or not (ok or named):
            continue
        out.append({"name": name, "metadata_ok": ok, "problems": probs, "visible": bool(s.get("visible")),
                    "currency_base": s.get("currency_base"), "currency_profit": s.get("currency_profit"),
                    "contract_size": s.get("trade_contract_size"), "description": s.get("description")})
    out.sort(key=lambda c: (not c["metadata_ok"], c["name"] != p["default_broker_symbol"], not c["visible"], c["name"]))
    return out
