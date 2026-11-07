"""TH_RF / TH_XGB / TH_SVM - adapters of the existing trainhub tabular pipeline (training, registry, activation, rollback and inference
stay in trainhub; the family view only reads their real state - no second training centre)."""
from __future__ import annotations

from . import base as B


class Tabular(B.Family):
    KIND = "TRAINED"
    TASK_TYPE = "CLASS_PROBABILITIES"
    UNIT = "probability"
    TASK = "DIRECTION_H"
    TF = "M5"
    HORIZONS = (6,)
    RECEIVERS = ("MODELHUB:trainhub_inference -> all_predictions", "SH_CONTEXT:direction_distribution", "PANEL:training_center")
    DATA = {"kind": "BARS", "tf": "M5", "pipeline": "trainhub (eksport MT5 -> dataset -> walk-forward -> holdout -> paczka)"}
    TH_ID = "?"

    def implementation(self):
        from ...trainhub import learn as L
        return ("AVAILABLE", None) if L.available().get(self.TH_ID) else ("MISSING_DEPENDENCY", "biblioteka niedostępna (np. xgboost)")

    def trainhub_state(self, inst: str) -> dict:
        from ...trainhub import registry as R
        s = R.summary(inst)
        mine = [v for v in s["versions"] if str(v.get("model_key", "")).startswith(self.TH_ID)]
        act = {k: v for k, v in (s.get("active") or {}).items() if k.startswith(self.TH_ID)}
        return {"artifact": "CANDIDATE" if mine else "NOT_TRAINED", "versions": len(mine), "active": act,
                "use": "SHADOW" if act else "OFF", "note": "trening / aktywacja w Centrum treningu (trainhub)"}


class RF(Tabular):
    ID, TH_ID, NAME = "TH_RF", "TH_RF", "Random Forest (trainhub)"


class XGB(Tabular):
    ID, TH_ID, NAME = "TH_XGB", "TH_XGB", "XGBoost (trainhub, eksport natywny JSON)"


class SVM(Tabular):
    ID, TH_ID, NAME = "TH_SVM", "TH_SVM", "SVM (trainhub, kalibracja chronologiczna)"
