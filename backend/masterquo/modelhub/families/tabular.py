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
        # arch146 I0010: the one trainhub state (registry.status_of; package keys matched as '<TH_ID>_', the prefix without '_' also matched
        # other models' keys); artifact / use as before, state + reason of the trainhub view added. The family service has no live view
        # (no rt): for an ACTIVE package status_of says DISABLED "serwis inferencji ... nie działa" (cause NO_LIVE_VIEW) even while the bot
        # runs and the model catalog shows READY - that state / reason is NOT a fact about the model, so the family view leaves it out
        # (the live state is the one of the model catalog); the states that do not need a live view (NO_LIBRARY, NO_ACTIVE, NOT_TRAINED) stay.
        from ...trainhub import registry as R
        st = R.status_of(inst, self.TH_ID)
        act = st["active"]
        live = {} if st.get("cause") == "NO_LIVE_VIEW" else {"state": st["state"], "reason": st["reason"]}
        return {"artifact": "CANDIDATE" if st["n_versions"] else "NOT_TRAINED", "versions": st["n_versions"], "active": act,
                "use": "SHADOW" if act else "OFF", **live, "note": "trening / aktywacja w Centrum treningu (trainhub)"}


class RF(Tabular):
    ID, TH_ID, NAME = "TH_RF", "TH_RF", "Random Forest (trainhub)"


class XGB(Tabular):
    ID, TH_ID, NAME = "TH_XGB", "TH_XGB", "XGBoost (trainhub, eksport natywny JSON)"


class SVM(Tabular):
    ID, TH_ID, NAME = "TH_SVM", "TH_SVM", "SVM (trainhub, kalibracja chronologiczna)"
