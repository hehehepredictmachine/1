"""Centrum Treningowe Pepe (1.42.10, PMW-TCP-1) – jeden prosty punkt treningu wszystkich modeli bota.

Dla użytkownika: lista modeli z prostym stanem (nie trenowany / w kolejce / w toku / wytrenowany / pominięty / błąd) per instrument,
przycisk „Trenuj” przy każdym modelu i „Trenuj wszystko”. Pod spodem nic nowego nie jest wymyślane – każda jednostka używa SWOJEGO,
istniejącego mechanizmu (te same sprawdzenia danych, walidacje i reguły aktywacji):
  * modele głównego treningu (prognozy świec, Scalp A/B/C, Legacy ML, Lab, kontekst wskaźników, Scalp ML, Neural Scalp, Structure
    Intelligence, Flow context, kontekst VAMD/FD/SMC, SH, pakiet 20 strategii, Monte Carlo, master models) -> `masterquo training run
    --tasks ...` (zawsze eksport historii z MT5 + kontrola jakości przed modelem, aktywacja i przeładowanie bota po nim – dzięki temu
    trening z panelu nie kończy się już „brak eksportu – uruchom 00_TRENING_START.bat”);
  * Centrum TH (BASELINE / LOGREG / HGB) -> trainhub FULL (eksport + zbiór + walk-forward + ocena);
  * rodziny modeli (ARIMA, GARCH, Kalman …) -> FamilyService.train_all (najwyżej 2 procesy naraz);
  * Granite TTM -> granite_train.start; SDformerFlow -> research.start_training.
Kolejka wykonuje JEDNO zadanie naraz (na komputerach 8–16 GB równoległe treningi kończyły się brakiem pamięci). Nic tutaj nie składa
zleceń i nie zmienia trybu wykonania. Stan kolejki żyje w procesie bota (restart = pusta kolejka); historia w data/training_center.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from .. import paths
from . import core as tc

INSTRUMENTS = ("XAUUSD", "BTC")
# modele głównego treningu: id zadania `training run` -> (krótka nazwa, grupa)
PIPELINE = (
    ("forecast", "Prognozy świec 5/15/30 min", "Prognozy i kierunek"),
    ("scalp_A", "Scalp A – kierunek 1/3/5 min", "Scalp"),
    ("scalp_B", "Scalp B – jakość setupu", "Scalp"),
    ("scalp_C", "Scalp C – polityka hedge", "Scalp"),
    ("ml", "Legacy ML – setupy S01–S12", "Strategie"),
    ("lab", "Lab – LOGREG / TREE / XGB / ResNet / SNN", "Laboratorium"),
    ("indicator_context", "Kontekst wskaźników SAR / IQ / PAL", "Kontekst rynku"),
    ("ml_scalp", "Scalp ML – XGBoost wynik netto", "Scalp"),
    ("neural_scalp", "Neural Scalp – sieć TCN", "Scalp"),
    ("structure_intelligence", "Structure Intelligence – ruch M1", "Laboratorium"),
    ("flow_context", "Flow context – reakcja M1", "Kontekst rynku"),
    ("context_indicators", "Kontekst VAMD / FD / SMC", "Kontekst rynku"),
    ("sh_models", "SCALPING / HEDGING – model zdarzenia", "Strategie"),
    ("sh_pack", "Pakiet 20 strategii SC / HG", "Strategie"),
    ("monte_carlo", "Monte Carlo ścieżek", "Strategie"),
    ("master_models", "Master models – HDC / GPR / STE", "Laboratorium"),
)
EXTRA = (
    ("trainhub", "Kierunek TH – BASELINE / LOGREG / HGB", "Prognozy i kierunek"),
    ("families", "Rodziny modeli – ARIMA / GARCH / Kalman …", "Rodziny modeli"),
    ("granite", "Granite TTM – dostrojenie do Twoich danych", "Modele prognoz AI"),
    ("sdformer", "SDformerFlow – model badawczy", "Modele prognoz AI"),
)
TH_DEFAULT = {"models": ["TH_BASELINE", "TH_LOGREG", "TH_HGB"], "base_tf": "M5", "horizon": 6, "k_atr": 0.25, "mode": "incremental",
              "timeframes": ["M1", "M5", "M15", "M30"], "lookback_days": 90}
STATE_PL = {"NOT_TRAINED": "nie trenowany", "QUEUED": "w kolejce", "RUNNING": "trenuje się", "DONE": "wytrenowany", "SKIPPED": "pominięty",
            "FAILED": "błąd", "CANCELLED": "anulowany", "UNAVAILABLE": "niedostępny"}
QUALITY_PL = {"ZWALIDOWANY_SHADOW": "zwalidowany", "CZESCIOWO_ZWALIDOWANY": "częściowo zwalidowany", "NIEZWALIDOWANY": "bez pełnej walidacji",
              "ODRZUCONY": "odrzucony – nie lepszy od bazy", "BRAK_PRZESLANEK": "za mało danych / zdarzeń",
              "TEST_TECHNICZNY": "test techniczny (dane syntetyczne)", "NIE_DOTYCZY": "",
              "DO_OCENY_NA_DEV": "wytrenowany – do oceny (holdout jeszcze nie otwarty)"}      # 1.46: was shown as raw "do_oceny_na_dev"
EXEC_STATE = {"W_TOKU": "RUNNING", "UKONCZONE": "DONE", "POMINIETE": "SKIPPED", "BLAD_TECHNICZNY": "FAILED", "ANULOWANE": "CANCELLED"}
TERMINAL = ("DONE", "FAILED", "CANCELLED", "SKIPPED")
CANDLES_UNITS = ("forecast", "scalp_A", "scalp_B", "scalp_C")      # jednostki na .venv_candles
# limity oczekiwania na zadanie (h). 1.46 (I0070): po limicie zadanie jest ANULOWANE i kolejka czeka na jego koniec (było: stan FAILED,
# a rodziny nawet DONE, bez anulowania – następne zadanie startowało obok wciąż trenującego, wbrew „jedno zadanie naraz”)
TIMEOUT_H = {"trainhub": 6, "families": 8, "granite": 6, "export": 2}


def _candles_autoinstall() -> bool:
    """core.ensure_candles installs a missing / broken .venv_candles itself only on Windows with 10_PROGNOZY_INSTALUJ.bat."""
    return os.name == "nt" and (paths.ROOT_DIR / "10_PROGNOZY_INSTALUJ.bat").exists()


def center_dir() -> Path:
    d = paths.data_dir() / "training_center"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _st(state: str, detail: str = "", at=None, **kw) -> dict:
    return {"state": state, "state_pl": STATE_PL.get(state, state), "detail": (detail or "")[:400], "at": at, **kw}


def pipeline_status(limit_runs: int = 40) -> dict:
    """{(task, inst): status} z ostatnich przebiegów `training run` (najnowszy wpis, w którym zadanie było w planie)."""
    out: dict = {}
    try:
        runs = sorted((p for p in tc.runs_dir().iterdir() if p.is_dir()), key=lambda p: p.name, reverse=True)[:limit_runs]
    except OSError:
        runs = []
    lock_alive = _lock_alive()
    for d in runs:
        try:
            st = json.loads((d / "state.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        live = st.get("status") == "RUNNING" and lock_alive == st.get("run_id")
        exp_err = {t.get("instrument"): _short(t.get("detail")) for t in st.get("tasks") or []          # 1.42.11: przyczyna nieudanego eksportu
                   if t.get("kind") == "export" and t.get("execution") == "BLAD_TECHNICZNY"}
        for t in st.get("tasks") or []:
            key = (t.get("kind"), t.get("instrument"))
            if key in out:
                continue
            ex, det = t.get("execution"), t.get("detail") or ""
            if ex == "POMINIETE" and det == "nie wybrano w planie":
                continue
            if ex == "NIE_URUCHOMIONE":
                if live:
                    out[key] = _st("QUEUED", "czeka na swoją kolej w bieżącym treningu", t.get("updated_at"), run_id=st.get("run_id"))
                continue
            if ex == "W_TOKU" and not live:
                out[key] = _st("FAILED", "trening przerwany (zamknięte okno / restart) – uruchom ponownie", t.get("updated_at"), run_id=st.get("run_id"))
                continue
            q = t.get("quality") or ""
            state = EXEC_STATE.get(ex, "NOT_TRAINED")
            if state == "DONE" and q in ("BRAK_PRZESLANEK",):
                state = "SKIPPED"
            msg = QUALITY_PL.get(q, q.lower()) if state == "DONE" else det
            if state == "SKIPPED" and q == "BRAK_PRZESLANEK":
                msg = "za mało danych / zdarzeń" + (f" – {det}" if det else "")
            if state == "SKIPPED" and det.startswith("brak danych (eksport") and exp_err.get(t.get("instrument")):
                msg = f"{det}: {exp_err[t.get('instrument')]}"
            out[key] = _st(state, msg, t.get("updated_at"), run_id=st.get("run_id"), quality=q or None, integration=t.get("integration"),
                           model_id=t.get("model_id"))
    return out


def _short(detail: str | None, n: int = 220) -> str:
    """Pierwsza istotna linia błędu procesu (bez ścieżki logu) – do pokazania przy modelu."""
    d = (detail or "").split(" (log: ")[0]
    parts = [x.strip() for x in d.split(" | ") if x.strip() and not x.strip().startswith("Traceback")]
    return (" | ".join(parts[-2:]) if parts else d)[:n]


def _lock_alive() -> str | None:
    try:
        cur = json.loads(tc.lock_path().read_text(encoding="utf-8"))
        return cur.get("run_id") if tc.lock_owner_alive(cur) else None      # 1.46: pid + start time (a reused pid is not a live training)
    except (OSError, ValueError, AttributeError):
        return None


class PepeTrainingCenter:
    def __init__(self, rt, clock=time.time):
        self.rt, self.clock = rt, clock
        self._lock = threading.RLock()
        self.queue: list[dict] = []
        self.current: dict | None = None
        self._thread: threading.Thread | None = None
        self._cancel = threading.Event()
        self._proc: subprocess.Popen | None = None
        self.history: list[dict] = self._load_history()
        self._granite_inst: str | None = None                # instrument bieżącego / ostatniego dostrajania Granite z Centrum

    # ------------------------------------------------------------------ ustawienia (prowizja – bez niej Scalp / ML po kosztach są pomijane)
    def settings(self) -> dict:
        try:
            d = json.loads((center_dir() / "settings.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            d = {}
        return {"commission_xauusd": d.get("commission_xauusd"), "commission_btc": d.get("commission_btc")}

    def set_settings(self, body: dict) -> dict:
        cur = self.settings()
        for k in ("commission_xauusd", "commission_btc"):
            if k in body:
                v = body[k]
                if v in (None, ""):
                    cur[k] = None
                    continue
                v = float(str(v).replace(",", "."))
                if not (0 <= v <= 1000):
                    raise ValueError(f"{k}: 0–1000 (waluta konta za 1 lot na stronę)")
                cur[k] = v
        tc.write_json_atomic(center_dir() / "settings.json", cur)
        return cur

    # ------------------------------------------------------------------ meta / availability
    def units(self) -> list[dict]:
        u = [{"id": k, "name": n, "group": g, "via": "pipeline", "instruments": list(INSTRUMENTS)} for k, n, g in PIPELINE]
        u += [{"id": k, "name": n, "group": g, "via": k, "instruments": ["*"] if k == "sdformer" else list(INSTRUMENTS)} for k, n, g in EXTRA]
        return u

    def availability(self) -> dict:
        """Jednostki, których nie da się dziś trenować (brak środowiska / modułu) – z instrukcją, co zrobić."""
        out = {}
        if not self._candles_ok():
            for k in CANDLES_UNITS:
                out[k] = "brak sprawnego środowiska .venv_candles – uruchom INSTALUJ_TRENING.bat (albo 10_PROGNOZY_INSTALUJ.bat)"
        try:
            from ..tsfm.settings import find_python
            s = self.rt.tsfm.settings.get()
            if not find_python("granite_ttm", s.models["granite_ttm"]):
                out["granite"] = "Granite TTM nie jest zainstalowany – uruchom 38_MODELE_CHRONOS2_GRANITE.bat"
            else:                                               # 1.42.10: środowisko bez wag = trening skończyłby się błędem po eksporcie
                from tsfm_runtime import manifest as TM
                if TM.read(self.rt.tsfm.weights_root(), "granite_ttm") is None:
                    out["granite"] = "brak wag Granite TTM (instalacja niedokończona) – uruchom 38_MODELE_CHRONOS2_GRANITE.bat"
        except Exception:  # noqa: BLE001
            out["granite"] = "moduł modeli prognoz niedostępny"
        try:
            from ..research.service import torch_python
            if getattr(self.rt, "research", None) is None:
                out["sdformer"] = "moduły badawcze niedostępne"
            elif not torch_python():
                out["sdformer"] = "brak środowiska z torch – uruchom 41_AI_TABICL_TIREX_INSTALUJ.bat"
        except Exception:  # noqa: BLE001
            out["sdformer"] = "moduły badawcze niedostępne"
        if getattr(self.rt, "trainhub", None) is None:
            out["trainhub"] = "Centrum TH niedostępne (błąd startu)"
        if getattr(self.rt, "families", None) is None:
            out["families"] = "rodziny modeli niedostępne (błąd startu)"
        return out

    def _candles_ok(self) -> bool:
        """1.46 (I0074): the RUNNER's rules (core.ensure_candles), not only the existence of .venv_candles: the interpreter from
        core.candles_python() (MQ_CANDLES_PYTHON or .venv_candles) that is not known to be broken, or - when it is missing / broken - the
        runner installs it itself (Windows + 10_PROGNOZY_INSTALUJ.bat). Before, a missing .venv_candles blocked forecast / scalp A/B/C
        here although the runner would install it, and MQ_CANDLES_PYTHON was ignored."""
        py = tc.candles_python()
        if py is not None and self._candles_health(py) is not False:
            return True
        return _candles_autoinstall()

    def _candles_note(self) -> str:
        """Informacja przy jednostkach prognoz / scalp, gdy środowisko zainstaluje się (albo naprawi) dopiero przy treningu."""
        py = tc.candles_python()
        if py is None:
            return "środowisko .venv_candles zainstaluje się automatycznie przy treningu (kilka minut)" if _candles_autoinstall() else ""
        if self._candles_health(py) is False:
            return ("środowisko .venv_candles niesprawne (brak pakietów) – trening spróbuje je zainstalować ponownie"
                    if _candles_autoinstall() else "środowisko .venv_candles niesprawne (brak pakietów)")
        return ""

    CANDLES_HEALTH_TTL_S = 600.0

    def _candles_health(self, py: str) -> bool | None:
        """core.candles_healthy(py) cached for CANDLES_HEALTH_TTL_S and refreshed in a background thread (a status poll never waits for the
        import check, up to 120 s). None = not checked yet (treated as usable - the runner checks again before training)."""
        h = getattr(self, "_candles_h", None) or {}
        fresh = h.get("py") == py and self.clock() - float(h.get("at") or 0) <= self.CANDLES_HEALTH_TTL_S
        if not fresh:
            t = getattr(self, "_candles_thread", None)
            if t is None or not t.is_alive():
                self._candles_thread = threading.Thread(target=self._check_candles, args=(py,), name="pepe-candles-check", daemon=True)
                self._candles_thread.start()
        return h.get("ok") if h.get("py") == py else None

    def _check_candles(self, py: str) -> None:
        try:
            ok = bool(tc.candles_healthy(py, max_age_s=0.0))
        except Exception:  # noqa: BLE001 - a failed check is "unknown", never a crash of the status
            return
        self._candles_h = {"py": py, "ok": ok, "at": self.clock()}

    # ------------------------------------------------------------------ status
    def status(self) -> dict:
        pipe = pipeline_status()
        unavailable = self.availability()
        cnote = "" if any(k in unavailable for k in CANDLES_UNITS) else self._candles_note()     # 1.46 (I0074): info, not a block
        with self._lock:
            queued = {(u, i) for q in self.queue for u in self._covers(q) for i in q["instruments"]}
            cur = self.current
        running = {(u, i) for u in self._covers(cur) for i in cur["instruments"]} if cur else set()
        rows = []
        for u in self.units():
            st = {}
            for inst in u["instruments"]:
                if u["id"] in unavailable:
                    s = _st("UNAVAILABLE", unavailable[u["id"]])
                elif u["via"] == "pipeline":
                    s = pipe.get((u["id"], inst)) or _st("NOT_TRAINED", "jeszcze nie trenowany na tym komputerze")
                    if cnote and u["id"] in CANDLES_UNITS and s["state"] in ("NOT_TRAINED", "FAILED", "SKIPPED"):
                        s = {**s, "detail": f"{s.get('detail') or ''} – {cnote}".strip(" –")[:400]}
                else:
                    s = self._extra_status(u["id"], inst)
                    s = self._last_attempt(u["id"], inst, s)
                if (u["id"], inst) in running and s["state"] not in ("RUNNING",):
                    s = _st("RUNNING", (cur.get("detail") or "start…") if u["via"] != "pipeline" or s["state"] != "QUEUED" else s.get("detail"), s.get("at"))
                elif (u["id"], inst) in queued and s["state"] not in ("RUNNING",):
                    s = _st("QUEUED", "czeka w kolejce Centrum Treningowego", s.get("at"))
                st[inst] = s
            rows.append({**u, "status": st})
        return {"schema": "PMW-TCP-1", "settings": self.settings(), "units": rows, "queue": [self._pub(q) for q in self.queue], "current": self._pub(cur) if cur else None,
                "history": self.history[-30:][::-1], "demo": bool(getattr(self.rt, "demo", False)), "instruments": list(INSTRUMENTS),
                "one_at_a_time": True, "pipeline_running": _lock_alive()}

    def _last_attempt(self, uid: str, inst: str, s: dict) -> dict:
        """1.42.10: nieudana / pominięta próba z Centrum nowsza niż stan modelu jest pokazana przy modelu (z przyczyną), a nie znika
        w historii – np. Granite „nie trenowany” po odrzuceniu zbioru danych."""
        if s["state"] in ("RUNNING", "QUEUED", "FAILED"):
            return s
        h = next((x for x in reversed(self.history) if x.get("unit") == uid and inst in (x.get("instruments") or [])), None)
        if not h or h.get("state") not in ("FAILED", "SKIPPED"):
            return s
        try:
            at = float(s.get("at") or 0) if not isinstance(s.get("at"), str) else 0.0
        except (TypeError, ValueError):
            at = 0.0
        if s["state"] == "DONE" and (not at or float(h.get("finished_at") or 0) <= at):
            return s
        return _st(h["state"], "ostatnia próba: " + (h.get("detail") or ""), h.get("finished_at"))

    def _covers(self, q: dict | None) -> list[str]:
        """Jednostki objęte zadaniem kolejki (przebieg głównego treningu obejmuje kilka modeli)."""
        if not q:
            return []
        if q["unit"] == "pipeline":
            return q.get("covers") or [k for k, _, _ in PIPELINE]
        return [q["unit"]]

    @staticmethod
    def _pub(q: dict | None) -> dict | None:
        if not q:
            return None
        return {k: q.get(k) for k in ("id", "unit", "name", "instruments", "tasks", "state", "detail", "started_at", "queued_at")}

    def _extra_status(self, uid: str, inst: str) -> dict:
        try:
            if uid == "trainhub":
                jobs = [j for j in self.rt.trainhub.list(100) if j.get("instrument") == inst and j.get("kind") in ("FULL", "TRAIN")]
                if not jobs:
                    return _st("NOT_TRAINED", "jeszcze nie trenowany")
                j = jobs[0]
                m = {"QUEUED": "QUEUED", "RUNNING": "RUNNING", "SUCCEEDED": "DONE", "FAILED": "FAILED", "CANCELLED": "CANCELLED", "INTERRUPTED": "FAILED"}
                state = m.get(j.get("status"), "NOT_TRAINED")
                det = j.get("error") if state == "FAILED" else (f"{j.get('stage') or ''} {round(100 * float(j.get('progress') or 0))}%" if state == "RUNNING"
                                                                  else ("zakończony – wersje w rejestrze Centrum TH" if state == "DONE" else j.get("stage") or ""))
                if state == "FAILED" and j.get("status") == "INTERRUPTED":
                    det = "przerwany przez restart bota – uruchom ponownie"
                return _st(state, det or "", j.get("finished_at") or j.get("started_at") or j.get("created_at"), job_id=j.get("id"))
            if uid == "families":
                cat = self.rt.families.catalog(inst)
                n = trained = running = queued = failed = 0
                fails = []
                for f in cat:
                    s = f.get("status") or {}
                    if s.get("implementation") != "AVAILABLE" or f.get("id") in ("TH_RF", "TH_XGB", "TH_SVM", "SEQ_GRU_EVENT") \
                            or f.get("family") in ("TH_RF", "TH_XGB", "TH_SVM", "SEQ_GRU_EVENT"):
                        continue
                    n += 1
                    js = (s.get("job") or {}).get("state")
                    if js == "RUNNING":
                        running += 1
                    elif js == "QUEUED":
                        queued += 1
                    elif s.get("artifact") in ("APPROVED", "CANDIDATE"):
                        trained += 1
                    elif js in ("FAILED", "BLOCKED"):
                        failed += 1
                        fails.append(f"{f.get('id') or f.get('family')}: {(s.get('job') or {}).get('reason') or ''}"[:120])
                if running or queued:
                    return _st("RUNNING", f"w toku {running}, w kolejce {queued}, wytrenowane {trained}/{n}")
                if trained:
                    return _st("DONE", f"wytrenowane {trained}/{n}" + (f"; bez danych / błąd: {failed}" if failed else ""), fails=fails[:6])
                if failed:
                    return _st("FAILED", f"żadna rodzina nie wytrenowana ({failed} zablokowanych): " + "; ".join(fails[:2]), fails=fails[:6])
                return _st("NOT_TRAINED", f"{n} rodzin gotowych do treningu")
            if uid == "granite":
                from ..tsfm import granite_train as GT
                j = self.rt.tsfm.job("granite_train") or {}
                mine = self._granite_inst in (None, inst)           # zadanie Granite jest jedno – należy do instrumentu, który je uruchomił
                if j.get("state") == "RUNNING" and mine:
                    return _st("RUNNING", j.get("message") or "trening Granite TTM")
                runs = [r for r in GT.runs() if (r.get("data") or {}).get("instrument") in (None, inst)]   # najnowsza pierwsza
                if j.get("state") == "FAILED" and mine:
                    return _st("FAILED", j.get("message") or j.get("code") or "błąd treningu")
                if runs:
                    return _st("DONE", f"{len(runs)} wersji dostrojonych; aktywacja ręczna po werdykcie IMPROVED_VS_BASE", runs[0].get("created_at"))
                return _st("NOT_TRAINED", "model bazowy (bez dostrojenia)")
            if uid == "sdformer":
                r = self.rt.research
                j = r.jobs.get("sdformer_last") or {}
                if j.get("state") == "RUNNING":
                    return _st("RUNNING", "trening SDformerFlow", j.get("started_at"))
                if j.get("state") == "FAILED":
                    return _st("FAILED", j.get("error") or "błąd treningu", j.get("finished_at"))
                if j.get("state") == "DONE" or r.settings()["sdformer"].get("active_run"):
                    return _st("DONE", "aktywna wersja: " + str(r.settings()["sdformer"].get("active_run") or "—"), j.get("finished_at"))
                return _st("NOT_TRAINED", "jeszcze nie trenowany")
        except Exception as exc:  # noqa: BLE001 - stan jednej jednostki nie psuje widoku
            return _st("NOT_TRAINED", f"stan nieznany: {type(exc).__name__}: {exc}"[:200])
        return _st("NOT_TRAINED")

    # ------------------------------------------------------------------ queue
    def enqueue(self, units: list[str] | str, instruments: list[str] | None = None) -> dict:
        valid = {u["id"]: u for u in self.units()}
        unavailable = self.availability()
        if units == "ALL":
            ids = list(valid)
        else:
            ids = [u for u in (units or []) if u in valid]
            if not ids:
                raise ValueError("UNKNOWN_UNIT")
        insts = [i for i in (instruments or INSTRUMENTS) if i in INSTRUMENTS] or list(INSTRUMENTS)
        added, skipped = [], []
        with self._lock:
            busy = {(u, i) for q in self.queue + ([self.current] if self.current else []) for u in self._covers(q) for i in q["instruments"]}
            pipe = [u for u in ids if valid[u]["via"] == "pipeline"]
            for u in ids:
                if u in unavailable:
                    skipped.append({"unit": u, "reason": unavailable[u]})
            pipe = [u for u in pipe if u not in unavailable]
            if pipe:
                pinsts = [i for i in insts if not all((u, i) in busy for u in pipe)]
                if pinsts:
                    q = self._item("pipeline", pinsts, tasks=None if units == "ALL" else pipe,
                                   name="Główny trening: " + ("wszystkie modele" if units == "ALL" else ", ".join(valid[u]["name"] for u in pipe)))
                    q["covers"] = pipe
                    self.queue.append(q)
                    added.append(self._pub(q))
            for u in ids:
                if valid[u]["via"] == "pipeline" or u in unavailable:
                    continue
                ui = ["*"] if valid[u]["instruments"] == ["*"] else [i for i in insts if (u, i) not in busy]
                for i in ui:
                    q = self._item(u, [i], name=valid[u]["name"] + ("" if i == "*" else f" · {i}"))
                    self.queue.append(q)
                    added.append(self._pub(q))
            self._ensure_thread()
        return {"ok": True, "added": added, "skipped": skipped, "queue_len": len(self.queue)}

    def _item(self, unit: str, insts: list[str], *, tasks=None, name: str = "") -> dict:
        return {"id": f"PTC-{int(self.clock() * 1000) % 10**10}-{len(self.queue)}", "unit": unit, "instruments": insts, "tasks": tasks,
                "name": name, "state": "QUEUED", "queued_at": self.clock(), "detail": ""}

    def remove(self, item_id: str) -> dict:
        with self._lock:
            n = len(self.queue)
            self.queue = [q for q in self.queue if q["id"] != item_id]
        return {"ok": n != len(self.queue)}

    def cancel(self) -> dict:
        """Czyści kolejkę i zatrzymuje bieżący trening (bez aktywacji niedokończonego modelu – reguły mechanizmów)."""
        with self._lock:
            dropped = len(self.queue)
            self.queue = []
            cur = self.current
        self._cancel.set()
        stopped = None
        if cur:
            stopped = self._stop(cur)
        return {"ok": True, "dropped": dropped, "stopped": stopped}

    def _stop(self, q: dict) -> str | None:
        try:
            u = q["unit"]
            if u == "pipeline":
                # 1.46: `training cancel` without a run id cancelled Run.latest() - a console training (00_TRENING_START.bat) this item was
                # only WAITING for. Only this item's own run / process is stopped.
                p = q.get("_proc")
                if p is None:                                    # own process not started yet: ending the wait (_cancel) is enough
                    return "główny trening – anulowany przed startem (inny trening w toku nie został zatrzymany)"
                rid = self._own_run_id(q)
                if rid:
                    (tc.runs_dir() / rid / "CANCEL").write_text(tc.now(), encoding="utf-8")     # = `training cancel <rid>`
                    return "główny trening – anulowanie zgłoszone (wznowienie: menu treningu → Wznów)"
                if p.poll() is None:                             # its run is not created yet - no training child exists: stop the process
                    p.terminate()
                return "główny trening – zatrzymany przed rozpoczęciem zadań"
            if u == "trainhub" and q.get("job_id"):
                self.rt.trainhub.cancel(q["job_id"])
                return "Centrum TH – anulowane"
            if u in ("families", "granite") and q.get("job_id") and getattr(self.rt, "trainhub", None) is not None:
                try:
                    self.rt.trainhub.cancel(q["job_id"])       # eksport historii przed treningiem (1.42.10)
                except Exception:  # noqa: BLE001 - eksport już zakończony
                    pass
            if u == "families":
                for i in q["instruments"]:
                    for f in self.rt.families.fams:
                        j = self.rt.families.job(f, i) or {}
                        if j.get("state") in ("RUNNING", "QUEUED"):
                            self.rt.families.cancel(f, i)
                return "rodziny modeli – anulowane"
            if u == "granite":
                from ..tsfm import granite_train as GT
                GT.cancel(self.rt.tsfm)
                return "Granite TTM – anulowane"
            if u == "sdformer":
                self.rt.research.cancel_training()
                return "SDformerFlow – zatrzyma się po bieżącej paczce"
        except Exception as exc:  # noqa: BLE001
            return f"anulowanie: {type(exc).__name__}: {exc}"[:200]
        return None

    def _ensure_thread(self) -> None:
        # 1.46: _loop clears self._thread under the lock before it exits - is_alive() alone was still True in that window and an item
        # enqueued then stayed "w kolejce" with no consumer
        if self._thread is not None and self._thread.is_alive():
            return
        self._cancel.clear()
        self._thread = threading.Thread(target=self._loop, name="pepe-training", daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while True:
            with self._lock:
                if not self.queue:
                    self.current = None
                    if self._thread is threading.current_thread():
                        self._thread = None                      # 1.46: see _ensure_thread
                    return
                q = self.queue.pop(0)
                q.update(state="RUNNING", started_at=self.clock())
                self.current = q
            self._cancel.clear()
            try:
                res = self._run(q)
            except Exception as exc:  # noqa: BLE001 - jedno zadanie nie zatrzymuje kolejki
                res = {"state": "FAILED", "detail": f"{type(exc).__name__}: {exc}"[:400]}
            if self._cancel.is_set():
                res = {"state": "CANCELLED", "detail": "anulowane przez użytkownika"}
            q.update(state=res["state"], detail=res.get("detail", ""), finished_at=self.clock())
            self._remember(q)
            dropped = []
            with self._lock:
                self.current = None
                if res.get("still_running"):                     # 1.46 (I0070): never a second training next to one still running
                    dropped, self.queue = self.queue, []
            for d in dropped:
                d.update(state="SKIPPED", detail=f"kolejka zatrzymana: {q.get('name') or q['unit']} nadal działa po anulowaniu (limit czasu)",
                         finished_at=self.clock())
                self._remember(d)

    # ------------------------------------------------------------------ runners (istniejące mechanizmy)
    def _wait(self, done, *, timeout: float, step: float = 3.0) -> bool:
        t0 = self.clock()
        while not self._cancel.is_set():
            if done():
                return True
            if self.clock() - t0 > timeout:
                return False
            self._cancel.wait(step)
        return False

    TIMEOUT_GRACE_S = 30 * 60.0

    def _timed_out(self, q: dict, what: str, hours: float, finished) -> dict:
        """1.46 (I0070): the wait limit passed while the unit still trains - its own job is cancelled (the same _stop as „Anuluj”) and the
        queue waits up to TIMEOUT_GRACE_S for it to end. If it still runs after that, the rest of the queue is dropped (_loop) instead of
        starting a second training next to it."""
        stopped = self._stop(q)
        q["detail"] = f"przekroczony limit {hours} h – anulowanie, czekam na zakończenie procesu"
        self._wait(finished, timeout=self.TIMEOUT_GRACE_S, step=5.0)
        if self._cancel.is_set():
            return {"state": "CANCELLED", "detail": "anulowane"}
        if not finished():
            return {"state": "FAILED", "still_running": True,
                    "detail": f"TIMEOUT: {what} – przekroczony limit {hours} h; anulowanie zgłoszone ({stopped or '-'}), ale proces nadal działa – "
                              "kolejka Centrum zatrzymana, żeby nie trenować dwóch modeli naraz"}
        return {"state": "FAILED", "detail": f"TIMEOUT: {what} – przekroczony limit {hours} h; zadanie anulowane ({stopped or '-'})"}

    def _run(self, q: dict) -> dict:
        u, insts = q["unit"], q["instruments"]
        if u == "pipeline":
            return self._run_pipeline(q)
        inst = insts[0]
        if u == "trainhub":
            j = self.rt.trainhub.submit("FULL", inst, dict(TH_DEFAULT))
            q["job_id"] = j.get("id")
            fin = lambda: (self.rt.trainhub.get(j["id"]) or {}).get("status") in ("SUCCEEDED", "FAILED", "CANCELLED", "INTERRUPTED")  # noqa: E731
            if not self._wait(fin, timeout=TIMEOUT_H["trainhub"] * 3600) and not self._cancel.is_set() and not fin():
                return self._timed_out(q, "Centrum TH", TIMEOUT_H["trainhub"], fin)
            jj = self.rt.trainhub.get(j["id"]) or {}
            st = {"SUCCEEDED": "DONE", "CANCELLED": "CANCELLED"}.get(jj.get("status"), "FAILED")
            return {"state": st, "detail": jj.get("error") or jj.get("stage") or ""}
        if u == "families":
            self._ensure_bars(q, inst, "M5", 5000)          # błąd eksportu nie blokuje: rodziny mają zapas świec z MT5 na żywo
            r = self.rt.families.train_all(inst, "research")
            q["detail"] = f"start {len(r['started'])}, w kolejce {len(r['queued'])}, zablokowane {len(r['blocked'])}"

            def fin():
                return not any((self.rt.families.job(f, inst) or {}).get("state") in ("RUNNING", "QUEUED") for f in self.rt.families.fams)
            if not self._wait(fin, timeout=TIMEOUT_H["families"] * 3600, step=5.0) and not self._cancel.is_set() and not fin():
                return self._timed_out(q, "rodziny modeli", TIMEOUT_H["families"], fin)
            s = self._extra_status("families", inst)
            if s["state"] in ("RUNNING", "QUEUED"):          # 1.46 (I0070): never DONE while a family still trains / waits
                return {"state": "FAILED", "detail": "rodziny modeli nadal w toku po zakończeniu oczekiwania: " + (s.get("detail") or "")}
            return {"state": s["state"] if s["state"] in TERMINAL else "DONE", "detail": s["detail"]}
        if u == "granite":
            from ..tsfm import granite_train as GT
            trading = getattr(getattr(self.rt, "modes", None), "mode", "SIGNALS") in ("AUTO_DEMO", "AUTO_LIVE")
            err = self._ensure_bars(q, inst, "M5", GT.MIN_BARS)
            if not err:
                self._wait_heavy_slot(q)
                mem = self._wait_memory(q)
                if mem and not self._cancel.is_set():
                    return {"state": "SKIPPED", "detail": mem}
            if self._cancel.is_set():
                return {"state": "CANCELLED", "detail": "anulowane"}
            if err:
                return {"state": "FAILED", "detail": err}
            r = GT.start(self.rt.tsfm, inst, "M5", epochs=6, trading_active=trading)
            self._granite_inst = inst if r.get("ok") else self._granite_inst
            if not r.get("ok"):
                return {"state": "SKIPPED", "detail": r.get("reason") or "nie uruchomiono"}
            def g_fin() -> bool:
                return (self.rt.tsfm.job("granite_train") or {}).get("state") != "RUNNING"
            if not self._wait(g_fin, timeout=TIMEOUT_H["granite"] * 3600) and not self._cancel.is_set() and not g_fin():
                return self._timed_out(q, "Granite TTM", TIMEOUT_H["granite"], g_fin)
            j = self.rt.tsfm.job("granite_train") or {}
            return {"state": "DONE" if j.get("state") in ("DONE", "SUCCEEDED") else "FAILED", "detail": j.get("message") or ""}
        if u == "sdformer":
            r = self.rt.research
            c = r.ensure_main_context()
            h1 = c.bars_fn("H1", 6000) if c else []
            if len(h1) < 600:
                return {"state": "SKIPPED", "detail": f"za mało zamkniętych świec H1 ({len(h1)} < 600)"}
            self._wait_heavy_slot(q)
            mem = self._wait_memory(q)
            if self._cancel.is_set():
                return {"state": "CANCELLED", "detail": "anulowane"}
            if mem:
                return {"state": "SKIPPED", "detail": mem}
            res = r.start_training(c, h1, op="from_scratch", reason="Centrum Treningowe (DIRECT_USER_REQUEST)")
            if not res.get("ok"):
                return {"state": "SKIPPED", "detail": res.get("reason") or ""}
            job = res["job"]
            self._wait(lambda: job.get("state") != "RUNNING", timeout=6 * 3600)
            return {"state": {"DONE": "DONE", "CANCELLED": "CANCELLED"}.get(job.get("state"), "FAILED"), "detail": job.get("error") or ""}
        return {"state": "FAILED", "detail": "nieznana jednostka"}

    def _wait_heavy_slot(self, q: dict, timeout: float = 6 * 3600) -> None:
        """1.42.10: Memory Governor dopuszcza jeden ciężki trening naraz (Granite, SDformerFlow – także auto-trening SDformerFlow przy
        starcie bota). Centrum czeka na jego koniec zamiast pomijać model z „trwa inny trening”."""
        gov = getattr(self.rt, "governor", None)
        busy = lambda: [n for n, k in dict(getattr(gov, "training", {}) or {}).items() if k == "heavy"]  # noqa: E731
        if gov is None or not busy():
            return
        q["detail"] = f"czeka na zakończenie innego treningu ({', '.join(busy())})"
        self._wait(lambda: not busy(), timeout=timeout, step=5.0)
        q["detail"] = ""

    def _wait_memory(self, q: dict, timeout: float = 15 * 60) -> str:
        """1.42.11: Memory Governor nie uruchamia ciężkiego treningu przy RAM ≥ progu LIMIT_HEAVY (domyślnie 80 %). Centrum najpierw zwalnia
        bezczynne ciężkie modele prognoz (Chronos-2, TiRex-2 …; Kronos zostaje), potem czeka do 15 min na wolną pamięć; inaczej zwraca
        czytelny powód z zajętością RAM (zamiast „za mało pamięci (LIMIT_HEAVY)”). Zwraca "" gdy można trenować."""
        gov = getattr(self.rt, "governor", None)
        if gov is None:
            return ""

        def bad() -> bool:
            try:
                return gov.level() in ("LIMIT_HEAVY", "PAUSE_OPTIONAL")
            except Exception:  # noqa: BLE001
                return False

        def used() -> str:
            try:
                return f"{float(gov.sample()['system']['used_pct']):.0f}"
            except Exception:  # noqa: BLE001
                return "?"
        if not bad():
            return ""
        try:
            gov._release_idle_heavy(except_model="", min_idle_s=10.0, why="Centrum Treningowe – pamięć dla treningu")
        except Exception:  # noqa: BLE001
            pass
        if not bad():
            return ""
        try:
            limit = f"{float(gov.profile()['limit_heavy_pct']):.0f}"
        except Exception:  # noqa: BLE001
            limit = "80"
        q["detail"] = f"czeka na wolną pamięć RAM – zajęte {used()} % (trening ciężkich modeli od {limit} % jest wstrzymany)"
        self._wait(lambda: not bad(), timeout=timeout, step=10.0)
        q["detail"] = ""
        if not bad():
            return ""
        return (f"za mało wolnej pamięci RAM: zajęte {used()} % – Memory Governor nie uruchamia ciężkiego treningu od {limit} %. "
                "Zamknij inne programy (np. przeglądarkę) i kliknij TRENUJ ponownie.")

    def _ensure_bars(self, q: dict, inst: str, tf: str, need: int) -> str:
        """1.42.10: Granite i rodziny modeli czytają archiwum świec (marketdata Store). Gdy jest za krótkie (np. przed pierwszym eksportem),
        Centrum samo pobiera historię z MT5 – eksport TrainHub (przyrostowy, M1/M5/M15/M30, zamknięte świece) – zamiast „za mało świec: 0”.
        Zwraca "" albo opis błędu eksportu."""
        def have() -> int:
            try:
                from ..marketdata.store import Store
                return len(Store().read(inst, tf)["time"])
            except Exception:  # noqa: BLE001 - brak archiwum = 0
                return 0
        n, th = have(), getattr(self.rt, "trainhub", None)
        if n >= need or th is None:
            return ""
        q["detail"] = f"pobieranie historii z MT5 – {inst} {tf}: {n} < {need} świec"
        try:
            j = th.submit("EXPORT", inst, {"mode": "incremental"})
        except Exception as exc:  # noqa: BLE001
            return f"eksport historii nie wystartował: {exc}"[:300]
        q["job_id"] = j.get("id")
        def e_fin() -> bool:
            return (th.get(j["id"]) or {}).get("status") in ("SUCCEEDED", "FAILED", "CANCELLED", "INTERRUPTED")
        if not self._wait(e_fin, timeout=TIMEOUT_H["export"] * 3600) and not self._cancel.is_set() and not e_fin():
            # 1.46 (I0070): the export job is cancelled and awaited - it no longer runs on next to the training that follows
            try:
                th.cancel(j["id"])
            except Exception as exc:  # noqa: BLE001 - already finished / unknown job
                q["detail"] = f"anulowanie eksportu: {type(exc).__name__}"
            self._wait(e_fin, timeout=self.TIMEOUT_GRACE_S, step=5.0)
            q["detail"] = ""
            return f"eksport historii z MT5 przekroczył limit {TIMEOUT_H['export']} h – anulowany"
        jj = th.get(j["id"]) or {}
        q["detail"] = ""
        if jj.get("status") == "SUCCEEDED":
            return ""
        return f"eksport historii z MT5 nieudany: {jj.get('error') or jj.get('status') or 'brak wyniku'}"[:300]

    def _run_pipeline(self, q: dict) -> dict:
        # inny trening (np. 00_TRENING_START.bat) w toku -> czekamy, nigdy dwa naraz
        if _lock_alive():
            q["detail"] = "czeka na zakończenie innego treningu"
            self._wait(lambda: not _lock_alive(), timeout=12 * 3600, step=5.0)
            if self._cancel.is_set():
                return {"state": "CANCELLED", "detail": "anulowane"}
        if self._cancel.is_set():                               # 1.46: cancelled before our own process started
            return {"state": "CANCELLED", "detail": "anulowane"}
        cmd = [sys.executable, "-m", "masterquo", "training", "run", "--instruments", ",".join(q["instruments"]), "--profile", "PELNY_TRENING",
               "--origin", "pepe-center"]
        if q.get("tasks"):
            cmd += ["--tasks", ",".join(q["tasks"])]
        st = self.settings()
        for inst in q["instruments"]:
            v = st.get(f"commission_{inst.lower()}")
            if v is not None:                                   # prowizja z Centrum (bez niej Scalp BTC jest pomijany – brak transakcji w historii)
                cmd += [f"--commission-{inst.lower()}", str(v)]
        if getattr(self.rt, "demo", False):
            cmd.append("--demo")
        log = open(tc.training_dir() / "pepe_center.log", "a", encoding="utf-8")
        kw = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)} if os.name == "nt" else {"start_new_session": True}
        before = {p.name for p in tc.runs_dir().iterdir()} if tc.runs_dir().exists() else set()
        q["_before"] = before                                   # 1.46: identifies the run created by THIS process (_own_run_id)
        try:
            self._proc = subprocess.Popen(cmd, cwd=str(paths.ROOT_DIR / "backend"), env=dict(os.environ, MQ_NO_BROWSER="1", PYTHONUTF8="1"),
                                          stdout=log, stderr=subprocess.STDOUT, **kw)
        except OSError as exc:
            log.close()
            return {"state": "FAILED", "detail": f"nie można uruchomić treningu: {exc}"[:300]}
        p = q["_proc"] = self._proc
        while p.poll() is None:
            if self._cancel.wait(3.0):
                for _ in range(12):                             # 1.46: repeated - a CANCEL written before execute() started is removed by it
                    self._stop(q)
                    try:
                        p.wait(10)
                        break
                    except subprocess.TimeoutExpired:
                        pass
                else:
                    p.kill()
                break
        log.close()
        rc = p.returncode
        new = sorted(({x.name for x in tc.runs_dir().iterdir()} - before) if tc.runs_dir().exists() else [])
        q["run_id"] = self._own_run_id(q) or (new[-1] if new else None)
        summ = self._run_summary(q["run_id"], q.get("covers") or [])
        if rc == 0:
            return {"state": "DONE", "detail": summ or "zakończony"}
        if rc == 4:
            return {"state": "DONE", "detail": "zakończony, część modeli pominięta: " + (summ or "")}
        if rc == 3:
            return {"state": "CANCELLED", "detail": "anulowany"}
        if rc == 2:
            return {"state": "FAILED", "detail": "zablokowany przed treningiem (MT5 / symbol / dane / inny trening) – " + (summ or self._log_tail())}
        return {"state": "FAILED", "detail": summ or self._log_tail()}

    @staticmethod
    def _own_run_id(q: dict) -> str | None:
        """1.46: the run created by THIS item's `training run` (a new folder in runs/ since its start with origin pepe-center) - never
        "the latest run", which may be a console training the item was waiting for."""
        if q.get("run_id"):
            return q["run_id"]
        before = q.get("_before")
        if before is None:
            return None
        try:
            new = sorted({x.name for x in tc.runs_dir().iterdir()} - before, reverse=True)
        except OSError:
            return None
        for rid in new:
            try:
                st = json.loads((tc.runs_dir() / rid / "state.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(st, dict) and (st.get("plan") or {}).get("origin") == "pepe-center":
                return rid
        return None

    @staticmethod
    def _run_summary(run_id: str | None, covers: list[str]) -> str:
        if not run_id:
            return ""
        try:
            st = json.loads((tc.runs_dir() / run_id / "state.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return ""
        c = {"UKONCZONE": 0, "POMINIETE": 0, "BLAD_TECHNICZNY": 0}
        errs = []
        exp = [f"{t.get('instrument')}: {_short(t.get('detail'))}" for t in st.get("tasks") or []      # 1.42.11: błąd eksportu na początku
               if t.get("kind") in ("export", "quality") and t.get("execution") == "BLAD_TECHNICZNY"]
        for t in st.get("tasks") or []:
            if t.get("kind") in ("export", "quality", "activate", "bot") or (t.get("detail") == "nie wybrano w planie"):
                continue
            ex = t.get("execution")
            if ex in c:
                c[ex] += 1
            if ex == "BLAD_TECHNICZNY":
                errs.append(f"{t.get('instrument')} {t.get('kind')}: {(t.get('detail') or '')[:120]}")
        s = f"wytrenowane {c['UKONCZONE']}, pominięte {c['POMINIETE']}, błędy {c['BLAD_TECHNICZNY']}"
        if exp:
            s = "EKSPORT HISTORII Z MT5 NIEUDANY – " + " ; ".join(exp[:2]) + ". " + s
        return s + ("; " + " | ".join(errs[:3]) if errs else "")

    @staticmethod
    def _log_tail() -> str:
        try:
            lines = [x for x in (tc.training_dir() / "pepe_center.log").read_text(encoding="utf-8", errors="replace").splitlines() if x.strip()]
        except OSError:
            return ""
        key = [x for x in lines[-60:] if "[BLAD]" in x or "Error" in x or "BLOCKED" in x]
        return (key[-1] if key else (lines[-1] if lines else ""))[:300]

    # ------------------------------------------------------------------ history
    def _load_history(self) -> list[dict]:
        try:
            return json.loads((center_dir() / "history.json").read_text(encoding="utf-8"))[-100:]
        except (OSError, ValueError):
            return []

    def _remember(self, q: dict) -> None:
        self.history.append({k: q.get(k) for k in ("id", "unit", "name", "instruments", "tasks", "state", "detail", "started_at", "finished_at", "run_id")}
                            | {"state_pl": STATE_PL.get(q.get("state"), q.get("state"))})
        self.history = self.history[-100:]
        try:
            tc.write_json_atomic(center_dir() / "history.json", self.history)
        except OSError:
            pass
