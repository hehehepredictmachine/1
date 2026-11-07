"""python -m masterquo.studio.verify <package_dir> - CLEAN process check that the BOT's loader reads the artifact and reproduces the
inference sample (trainhub: compatibility + prediction_test incl. the calibrated final output; families: FamilyService.activate with the
sample check). Prints one JSON line. Works on a temporary copy, never on the bot's registry."""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

from .package import ARTIFACT


def verify(pkg: Path) -> dict:
    res = json.loads((pkg / ARTIFACT / "train_result.json").read_text(encoding="utf-8"))
    task = json.loads((pkg / "manifest.json").read_text(encoding="utf-8"))["task"]
    inst = task["instrument"]
    with tempfile.TemporaryDirectory() as td:
        os.environ["MASTERQUO_DATA_DIR"] = td
        if res["kind"] == "TRAINHUB":
            from ..trainhub import registry as R
            dst = R.root() / "models" / inst / res["model_key"] / res["version"]
            shutil.copytree(pkg / ARTIFACT / "trainhub" / res["model_key"] / res["version"], dst)
            comp = R.compatibility(inst, res["model_key"], res["version"])
            if not comp["ok"]:
                return {"ok": False, "reason": "niezgodność", "compatibility": comp}
            pt = R.prediction_test(inst, res["model_key"], res["version"])
            return {"ok": bool(pt["ok"]), "loader": "trainhub.registry", "prediction_test": pt}
        if res["kind"] == "FAMILY":
            from ..config import ConfigStore
            from ..modelhub.families import base as FB
            from ..modelhub.families.service import FamilyService
            st = FB.Store(Path(td) / "fam")
            shutil.copytree(pkg / ARTIFACT / "families" / task["model_id"] / inst / res["run_id"], st.fam_dir(task["model_id"], inst) / res["run_id"])
            a = FamilyService(ConfigStore(), None, store=st).activate(task["model_id"], inst, res["run_id"])
            return {"ok": bool(a.get("ok")), "loader": "FamilyService.activate", "detail": a.get("sample_check") or a.get("reason")}
    return {"ok": True, "loader": None, "note": f"adapter {res['kind']}: rejestr własny zadania"}


if __name__ == "__main__":
    try:
        out = verify(Path(sys.argv[1]))
    except Exception as exc:  # noqa: BLE001
        out = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:400]}
    print(json.dumps(out, ensure_ascii=False, default=str))
