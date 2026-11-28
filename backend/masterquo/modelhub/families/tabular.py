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

    def capabilities(self) -> dict:
        """1.46 arch (I0007): TF / HORIZONS above describe the reference configuration (M5, h=6) only - trainhub trains any base TF of
        its feature schema and any horizon (one package per model_key <MODEL>_<TF>_H<h>). The allowed set is added as NEW descriptive
        fields (read from trainhub.features); tf / horizons keep their meaning and type."""
        from ...trainhub import features as TF
        return {**super().capabilities(), "tf_allowed": list(TF.HTF_OF),
                "horizon_source": "h świec z paczki trainhub (model_key <MODEL>_<TF>_H<h>); aktywna konfiguracja: trainhub_state(inst)['active_config']"}

    def implementation(self):
        from ...trainhub import learn as L
        return ("AVAILABLE", None) if L.available().get(self.TH_ID) else ("MISSING_DEPENDENCY", "biblioteka niedostępna (np. xgboost)")

    def trainhub_state(self, inst: str) -> dict:
        from ...trainhub import registry as R
        s = R.summary(inst)
        mine = [v for v in s["versions"] if str(v.get("model_key", "")).startswith(self.TH_ID)]
        act = {k: v for k, v in (s.get("active") or {}).items() if k.startswith(self.TH_ID)}
        return {"artifact": "CANDIDATE" if mine else "NOT_TRAINED", "versions": len(mine), "active": act,
                "use": "SHADOW" if act else "OFF", "note": "trening / aktywacja w Centrum treningu (trainhub)",
                "active_config": [c for c in (self._parse_key(k, v) for k, v in sorted(act.items())) if c]}   # 1.46 arch (I0007), read-only

    def _parse_key(self, key: str, version) -> dict | None:
        """model_key <TH_ID>_<TF>_H<h> (trainhub.registry.model_key) -> its base TF and horizon (description only)."""
        rest = key[len(self.TH_ID) + 1:] if key.startswith(self.TH_ID + "_") else ""
        tf, _, h = rest.rpartition("_H")
        return {"model_key": key, "version": version, "base_tf": tf, "horizon": int(h)} if tf and h.isdigit() else None


class RF(Tabular):
    ID, TH_ID, NAME = "TH_RF", "TH_RF", "Random Forest (trainhub)"


class XGB(Tabular):
    ID, TH_ID, NAME = "TH_XGB", "TH_XGB", "XGBoost (trainhub, eksport natywny JSON)"
    # 1.46 (I0446): the capabilities / model card said "no additional libraries"; availability itself stays trainhub.learn.available()
    DEPS = ("xgboost",)


class SVM(Tabular):
    ID, TH_ID, NAME = "TH_SVM", "TH_SVM", "SVM (trainhub, kalibracja chronologiczna)"
