"""Smoke checks of the pretrained time-series models (Kronos-small, Chronos-2, Granite TTM, TiRex-2) and the 1.41 research modules.

Official weights are looked up READ ONLY, the way the bot and the installers find them - an explicit variable first (MQ_KRONOS_WEIGHTS_DIR,
MQ_TSFM_WEIGHTS_ROOT), then the bot's own folder in the PROGRAM's data folder (weights_dir / weights_root of <data>/kronos|tsfm/settings.json,
else <data>/kronos/models, <data>/tsfm/models); the area process itself runs on a temporary MASTERQUO_DATA_DIR. Nothing is downloaded and
nothing is written outside ctx.data_dir.

Kronos: the real chain KronosService -> `python -m kronos_runtime.worker` (.venv_kronos) on the FakeMT5 bridge. With the official pinned pair
installed (bot manifest, sha256 = pins of kronos_runtime/lock.py): the installer's own check (`kronos_runtime.install verify --reference`),
a READY record on those weights and a new worker process -> the same path. Without them: the project's TEST fixture of RANDOM weights in the
pinned layout (tests/kronos_fixture.py) - plumbing only, the artifact step stays NIEZWERYFIKOWANY. Chronos-2 / Granite TTM / TiRex-2: with
the model environment and the official weights the real TsfmService -> tsfm_runtime.worker on those weights (sha256 + git blob of every
pinned file, READY record, selftest / parity, a new process -> the same forecast); without them the NOT_INSTALLED / NO_WEIGHTS state. Both
end with the failure path (a damaged installation -> CHECKSUM must reach the event log). Research modules: the real ResearchModulesService
cycle on closed FakeMT5 bars (graph50 online learning + state roundtrip, G7 radar, SDformerFlow bootstrap training in an environment with
torch).
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import UTC
from typing import ClassVar

from . import check, fail, ok, unverified

INST = "XAUUSD"
OFFICIAL_NOTE = "losowe wagi testowe (fixture) – to nie jest oficjalny model"
KRONOS_WEIGHTS_ENV = "MQ_KRONOS_WEIGHTS_DIR"          # the same variable as tests/test_kronos_runtime.TestOfficialWeights
TSFM_WEIGHTS_ENV = "MQ_TSFM_WEIGHTS_ROOT"             # --weights-root of tools/tsfm_setup.py (Chronos-2 / Granite TTM / TiRex-2 / TabICLv2)


# ------------------------------------------------------------------------------------------------------------------- helpers
# 1.46 arch (Etap 4, martwy kod): the unused helper _exc (no caller anywhere - AST + grep) was removed.
@contextmanager
def _env(**kw):
    """Temporarily set (value) / remove (None) environment variables of THIS area process; restored afterwards."""
    old = {k: os.environ.get(k) for k in kw}
    try:
        for k, v in kw.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = str(v)
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _core(ctx) -> dict:
    """The composition of `serve --demo` for the data path: ConfigStore + Database + AppLog + MT5Worker(FakeMT5) + MarketBridge (cached)."""
    core = getattr(ctx, "_kt_core", None)
    if core is not None:
        return core
    import atexit
    import time

    from ...config import ConfigStore
    from ...db.database import Database
    from ...events import AppLog, EventBus
    from ...mt5.bridge import MarketBridge
    from ...mt5.worker import MT5Worker
    fake = ctx.fake()
    cfg = ConfigStore()
    db = Database()
    db.migrate()
    bus = EventBus()
    log = AppLog(db, bus)
    worker = MT5Worker(lambda: fake)
    worker.start()
    atexit.register(worker.stop)
    bridge = MarketBridge(cfg, worker, db, bus, log)
    bridge.connect()
    t0 = time.monotonic()
    while time.monotonic() - t0 < 30:                     # the server offset is measured from quotes (a few polls)
        bridge.poll(time.monotonic())
        if bridge.clock.offset is not None and any(b.get("open_utc") for b in bridge.bars("M5", 5, include_forming=False)):
            break
        time.sleep(0.2)
    if bridge.clock.offset is None:
        raise RuntimeError("MarketBridge na FakeMT5: brak zmierzonego przesunięcia czasu serwera po 30 s")
    core = {"cfg": cfg, "db": db, "bus": bus, "log": log, "bridge": bridge, "symbol": cfg.get().mt5.symbol}
    ctx._kt_core = core
    return core


def _adapter_records(cid_prefix: str, **services) -> list[dict]:
    """PMW-PRED-2 records of one producer through modelhub.adapters.all_predictions (the adapter of the bot / `models check --live`)."""
    from types import SimpleNamespace

    from ...quant import ids as I
    from .. import adapters as MA
    rt = SimpleNamespace(**services)
    return [p for p in MA.all_predictions(rt, INST) if I.canonical(p) == cid_prefix or I.canonical(p).startswith(cid_prefix + ":")]


# ------------------------------------------------------------------------------------------------------------------- official weights (read only)
def _program_settings(ctx, area: str) -> tuple:
    """(data folder of the PROGRAM, its <area>/settings.json as a dict). Read only. The area process runs on a temporary MASTERQUO_DATA_DIR,
    so the folder the bot and the installers use is resolved the way paths.data_dir() does without that override."""
    import json

    from mq_instruments import default_data_dir
    data = default_data_dir(ctx.root)
    try:
        raw = json.loads((data / area / "settings.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = None
    return data, (raw if isinstance(raw, dict) else {})


def tsfm_weights_candidates(ctx) -> list[tuple[str, str]]:
    """Weights roots of the TSFM / TabICL installer (tools/tsfm_setup.py --weights-root auto) as (root, source), in order: MQ_TSFM_WEIGHTS_ROOT,
    then the bot's folder in the program's data folder (weights_root of <data>/tsfm/settings.json, else <data>/tsfm/models). Also used by
    smoke/quant.py for TabICLv2 (<root>/tabicl_v2). Read only."""
    data, s = _program_settings(ctx, "tsfm")
    out = [(os.environ[TSFM_WEIGHTS_ENV], TSFM_WEIGHTS_ENV)] if os.environ.get(TSFM_WEIGHTS_ENV) else []
    if s.get("weights_root"):
        out.append((str(s["weights_root"]), "weights_root z <dane programu>/tsfm/settings.json"))
    out.append((str(data / "tsfm" / "models"), "<dane programu>/tsfm/models"))
    return out


# ------------------------------------------------------------------------------------------------------------------- Kronos
def _kronos_official(ctx) -> tuple[str | None, str, str | None]:
    """(weights folder, source, problem) of the first INSTALLED Kronos pair, or (None, why none, None). Candidates: MQ_KRONOS_WEIGHTS_DIR,
    then the bot's folder in the program's data folder (weights_dir of <data>/kronos/settings.json, else <data>/kronos/models). Read only.
    Installed = the bot's kronos_runtime.manifest.summary accepts it (pinned repo + revision of both components, never a test fixture) - the
    bot would load it. Then it must be exactly the pinned pair: the sha256 recorded in the manifest for every pinned file equals
    kronos_runtime/lock.py and manifest.verify (sha256 of every file on disk) passes; otherwise `problem` says why (a FAIL, not a skip)."""
    from kronos_runtime import lock as LK
    from kronos_runtime import manifest as KM
    data, s = _program_settings(ctx, "kronos")
    cands = [(os.environ[KRONOS_WEIGHTS_ENV], KRONOS_WEIGHTS_ENV)] if os.environ.get(KRONOS_WEIGHTS_ENV) else []
    if s.get("weights_dir"):
        cands.append((str(s["weights_dir"]), "weights_dir z <dane programu>/kronos/settings.json"))
    cands.append((str(data / "kronos" / "models"), "<dane programu>/kronos/models"))
    why = []
    with _env(MQ_KRONOS_ALLOW_FIXTURE=None):                 # test weights are never accepted as the official model
        for wd, src in cands:
            sm = KM.summary(wd)
            if not sm["installed"]:
                why.append(f"{src}: {str(sm['reason'])[:140]}")
                continue
            comps = {c.get("kind"): c for c in sm["manifest"].get("components") or []}
            bad = []
            for c in LK.COMPONENTS:
                got = {f.get("name"): f.get("sha256") for f in comps[c["kind"]].get("files") or []}
                bad += [f"{c['repo']}/{n} sha256 {str(got.get(n))[:12]}… ≠ pin lock.py {pin[:12]}…" for n, pin in c["sha256"].items() if got.get(n) != pin]
            if bad:
                return wd, src, f"{'; '.join(bad)} – to nie są przypięte wagi, a bot by je załadował"
            try:
                KM.verify(wd)
            except KM.ManifestError as exc:
                return wd, src, f"{exc.code}: {exc.detail}"
            return wd, src, None
    return None, "; ".join(why), None


def _kronos_fixture(ctx, kpy: str, steps: dict, why: str) -> dict:
    """No official installation: the project's fixture of RANDOM weights in the pinned layout -> the same bot path, artifact NIEZWERYFIKOWANY."""
    import json
    import math
    import subprocess

    from kronos_runtime import lock as LK
    pair = f"{LK.MODEL['repo']}@{LK.MODEL['revision'][:8]} + {LK.TOKENIZER['repo']}@{LK.TOKENIZER['revision'][:8]}"
    why = str(why)[:170]
    fx = ctx.root / "tests" / "kronos_fixture.py"
    if not fx.is_file():
        steps["artifact"] = unverified(f"oficjalne wagi {pair} niezainstalowane ({why}); brak tests/kronos_fixture.py (wagi testowe) – nie ma czego załadować")
        return steps

    # -- random-weight fixture in the pinned layout (the project's own test fixture), written only in the temporary data folder
    ctx.step = "artifact"
    wd = ctx.data_dir / "kronos_smoke" / "weights"
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", HF_HUB_OFFLINE="1", OMP_NUM_THREADS="1")
    r = subprocess.run([kpy, str(fx), str(wd)], cwd=str(ctx.data_dir), env=env, capture_output=True, text=True, timeout=180, check=False)
    if r.returncode != 0:
        steps["artifact"] = fail(f"tests/kronos_fixture.py (.venv_kronos) kod {r.returncode}: {(r.stderr or r.stdout).strip()[-300:]}")
        return steps
    fparams = json.loads(r.stdout.strip().splitlines()[-1])
    if any((wd / LK.component_dir_name(c)).exists() for c in LK.LEGACY):
        steps["artifact"] = fail("folder wag zawiera Kronos-base – auto-migracja pobrałaby wagi z sieci (smoke przerwany)")
        return steps

    # -- KronosService on the FakeMT5 bridge, settings in the temporary data folder
    ctx.step = "predict"
    from ...kronos.service import KronosService
    from ...kronos.settings import SettingsStore
    core = _core(ctx)
    st = SettingsStore(ctx.data_dir / "kronos_smoke" / "settings.json")
    st.update({"weights_dir": str(wd), "python_path": kpy, "instruments": [INST], "timeframes": ["M5"], "cpu_threads": 1, "device": "CPU"})
    H = int(st.get().horizon_bars["M5"])

    def service():
        return KronosService(core["cfg"], core["bridge"], core["db"], core["bus"], core["log"], settings=st)
    svc = service()
    svc2 = None
    try:
        # honesty gate: a fixture manifest is never accepted as the installed model outside the test suite
        with _env(MQ_KRONOS_ALLOW_FIXTURE=None, HF_HUB_OFFLINE="1"):
            svc.tick()
            gate_state, gate_reason = svc.state["status"], str(svc.state.get("reason") or "")
            gate_recs = _adapter_records("kronos:Kronos-small", kronos=svc)
        gate_ok = gate_state == "NO_WEIGHTS" and "testowy" in gate_reason and all(p["state"] == "DISABLED" for p in gate_recs) and not svc.queue
        if not gate_ok:
            steps["predict"] = fail(f"bramka fixture nie zadziałała: stan {gate_state} ({gate_reason[:120]}), "
                                    f"rekordy {[p['state'] for p in gate_recs]}, kolejka {len(svc.queue)}")
            return steps
        with _env(MQ_KRONOS_ALLOW_FIXTURE="1", HF_HUB_OFFLINE="1"):
            svc.tick()
            tv = svc.target_view((INST, "M5"))
            if not svc.queue:
                steps["predict"] = fail(f"brak zadania po nowej świecy: cel {tv['state']} ({tv.get('reason')}), serwis {svc.state['status']}")
                return steps
            _, job = svc.queue.popitem(last=False)
            fc = svc.run_job(job)
            if fc is None:
                tv = svc.target_view((INST, "M5"))
                steps["predict"] = fail(f"run_job bez prognozy: cel {tv['state']} ({tv.get('reason')}), serwis {svc.state['status']} "
                                        f"({svc.state.get('reason')})")
                return steps
            recs = _adapter_records("kronos:Kronos-small", kronos=svc)
            closes = [float(x["c"]) for x in fc["pred"]]
            ready = [p for p in recs if p["state"] == "READY"]
            good = (len(closes) == H and all(math.isfinite(v) for v in closes) and fc["mode"] == "SHADOW" and not fc["execution_permission"]
                    and fc["data_kind"] == "SYNTHETIC" and len(ready) == 1 and (svc.load_info or {}).get("params_model") == fparams["params_model"])
            steps["predict"] = check(
                good,
                f"KronosService → kronos_runtime.worker: READY, {fc['device']}, {len(closes)} kroków M5, close(H)={closes[-1]:.3f}, "
                f"{fc['direction']}, SHADOW, {fc['compute_ms']} ms, {fparams['params_model']} param.; {OFFICIAL_NOTE}; "
                f"bramka: manifest fixture odrzucony bez MQ_KRONOS_ALLOW_FIXTURE (NO_WEIGHTS)",
                f"prognoza niezgodna: kroki {len(closes)}/{H}, tryb {fc.get('mode')}, dane {fc.get('data_kind')}, rekordy {[p['state'] for p in recs]}, "
                f"param. {(svc.load_info or {}).get('params_model')} vs fixture {fparams['params_model']}")
            ctx.step = "contract"
            steps["contract"] = ctx.contract_step(recs + gate_recs)
            if steps["predict"]["status"] != "OK":
                return steps

            # -- roundtrip: a NEW service instance -> a NEW worker process loads the weights from disk (sha256 verified) -> same path
            ctx.step = "artifact"
            svc2 = service()
            fc2 = svc2.run_job(job)
            if fc2 is None:
                steps["artifact"] = fail(f"ponowne wczytanie wag w nowym procesie bez prognozy: {svc2.state['status']} ({svc2.state.get('reason')})")
                return steps
            diff = max(abs(a - float(b["c"])) for a, b in zip(closes, fc2["pred"]))
        if diff > 1e-9:
            steps["artifact"] = fail(f"ta sama świeca i ziarno, nowy proces: różnica ścieżki close {diff:.3g} (oczekiwano 0)")
        else:
            steps["artifact"] = unverified(
                f"oficjalne wagi {pair} niezainstalowane – technicznie tylko na fixture z losowymi wagami (sha256 przy load OK, nowy proces "
                f"workera → ta sama ścieżka, różnica {diff:.1g}); szukano: {why}")
        return steps
    finally:
        svc.stop()
        if svc2 is not None:
            svc2.stop()


def _kronos_with_official(ctx, kpy: str, wd: str, src: str, steps: dict) -> dict:
    """Official pinned pair (read only): the installer's own check (verify --reference: load + test forecast + parity with the official
    KronosPredictor) -> KronosService -> worker on FakeMT5 bars -> READY record -> a NEW worker process -> the same path."""
    import json
    import math
    import subprocess

    from kronos_runtime import lock as LK
    ctx.step = "artifact"
    env = dict(os.environ, PYTHONPATH=str(ctx.root / "backend"), PYTHONIOENCODING="utf-8", HF_HUB_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1",
               PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run([kpy, "-m", "kronos_runtime.install", "verify", "--weights-dir", wd, "--reference", "--device", "CPU"],
                       cwd=str(ctx.data_dir), env=env, capture_output=True, text=True, timeout=600, check=False)
    line = next((x for x in reversed(r.stdout.splitlines()) if x.startswith("RESULT ")), None)
    res = json.loads(line[7:]) if line else {}
    st = res.get("selftest") or {}
    par, ref = st.get("parity") or {}, st.get("reference") or {}
    rel = max((float(x.get("max_rel_diff") or 0.0) for x in ref.get("rows") or []), default=None)
    ver_txt = (f"verify --reference (instalator): prognoza testowa {(st.get('smoke') or {}).get('ms')} ms, parity {par.get('status')} "
               f"(max {par.get('max_abs_diff')}), dane autorów {ref.get('status')} (max rel {'-' if rel is None else f'{rel:.2g}'})")
    if r.returncode != 0 or not res.get("ok"):
        steps["artifact"] = fail(f"oficjalne wagi ({src}): kontrola instalatora nieudana: kod {r.returncode}, {res.get('code')}: "
                                 f"{str(res.get('error') or (r.stderr or r.stdout).strip()[-200:])[:220]}")
        return steps

    ctx.step = "predict"
    from ...kronos.service import KronosService
    from ...kronos.settings import SettingsStore
    core = _core(ctx)
    sts = SettingsStore(ctx.data_dir / "kronos_smoke" / "settings.json")
    sts.update({"weights_dir": wd, "python_path": kpy, "instruments": [INST], "timeframes": ["M5"], "cpu_threads": 1, "device": "CPU"})
    H = int(sts.get().horizon_bars["M5"])

    def service():
        s = KronosService(core["cfg"], core["bridge"], core["db"], core["bus"], core["log"], settings=sts)
        s._auto_migrate = lambda py: False             # never a download into the user's weights folder (read only; installed was verified)
        return s
    svc = service()
    svc2 = None
    try:
        with _env(MQ_KRONOS_ALLOW_FIXTURE=None, HF_HUB_OFFLINE="1"):
            svc.tick()
            tv = svc.target_view((INST, "M5"))
            if not svc.queue:
                steps["predict"] = fail(f"oficjalne wagi zainstalowane, a brak zadania po nowej świecy: cel {tv['state']} ({tv.get('reason')}), "
                                        f"serwis {svc.state['status']} ({svc.state.get('reason')})")
                return steps
            _, job = svc.queue.popitem(last=False)
            fc = svc.run_job(job)
            if fc is None:
                tv = svc.target_view((INST, "M5"))
                steps["predict"] = fail(f"run_job bez prognozy (oficjalne wagi): cel {tv['state']} ({tv.get('reason')}), serwis "
                                        f"{svc.state['status']} ({svc.state.get('reason')})")
                return steps
            recs = _adapter_records("kronos:Kronos-small", kronos=svc)
            closes = [float(x["c"]) for x in fc["pred"]]
            ready = [p for p in recs if p["state"] == "READY"]
            li = svc.load_info or {}
            pinned = ((fc.get("model") or {}).get("revision") == LK.MODEL["revision"]
                      and (fc.get("tokenizer") or {}).get("revision") == LK.TOKENIZER["revision"])
            good = (len(closes) == H and all(math.isfinite(v) for v in closes) and fc["mode"] == "SHADOW" and not fc["execution_permission"]
                    and fc["data_kind"] == "SYNTHETIC" and len(ready) == 1 and li.get("params_model") == LK.MODEL["params_measured"] and pinned
                    and ready[0].get("model_version") == LK.MODEL["revision"])
            steps["predict"] = check(
                good,
                f"KronosService → kronos_runtime.worker na OFICJALNYCH wagach {LK.MODEL_NAME}@{LK.MODEL['revision'][:8]}: READY, {fc['device']}, "
                f"{len(closes)} kroków M5, close(H)={closes[-1]:.3f}, {fc['direction']}, SHADOW, {fc['compute_ms']} ms, "
                f"{li.get('params_model')} param. = przypięte; dane SYNTHETIC (FakeMT5) – test techniczny, nie jakość",
                f"prognoza niezgodna: kroki {len(closes)}/{H}, tryb {fc.get('mode')}, dane {fc.get('data_kind')}, rekordy {[p['state'] for p in recs]}, "
                f"param. {li.get('params_model')} vs pin {LK.MODEL['params_measured']}, rewizje model/tokenizer zgodne z lock.py: {pinned}")
            ctx.step = "contract"
            steps["contract"] = ctx.contract_step(recs)
            if steps["predict"]["status"] != "OK":
                return steps

            # -- roundtrip: a NEW service instance -> a NEW worker process loads the official weights (sha256 at load) -> same path
            ctx.step = "artifact"
            svc2 = service()
            fc2 = svc2.run_job(job)
            if fc2 is None:
                steps["artifact"] = fail(f"oficjalne wagi w nowym procesie bez prognozy: {svc2.state['status']} ({svc2.state.get('reason')})")
                return steps
            diff = max(abs(a - float(b["c"])) for a, b in zip(closes, fc2["pred"]))
        steps["artifact"] = check(
            diff <= 1e-9,
            f"oficjalne wagi ({src}): {LK.MODEL['repo']}@{LK.MODEL['revision'][:8]} + {LK.TOKENIZER['repo']}@{LK.TOKENIZER['revision'][:8]}, "
            f"sha256 model.safetensors {LK.MODEL['sha256']['model.safetensors'][:12]}… = pin lock.py, pliki = manifest; {ver_txt}; "
            f"nowy proces workera → ta sama ścieżka (różnica {diff:.1g})",
            f"oficjalne wagi, ta sama świeca i ziarno, nowy proces: różnica ścieżki close {diff:.3g} (oczekiwano 0); {ver_txt}")
        return steps
    finally:
        svc.stop()
        if svc2 is not None:
            svc2.stop()


def _kronos(ctx) -> dict:
    """KronosService -> `python -m kronos_runtime.worker` (.venv_kronos) on the FakeMT5 bridge: on the OFFICIAL weights when they are installed
    (_kronos_official), else on the project's random-weight fixture (artifact NIEZWERYFIKOWANY)."""
    from kronos_runtime import lock as LK
    steps: dict = {}
    ctx.step = "env"
    kpy = ctx.env_python(".venv_kronos")
    if kpy is None:
        steps["env"] = unverified("brak .venv_kronos (MQ_KRONOS_PYTHON / <program>/.venv_kronos) – worker Kronos niesprawdzalny")
        steps["artifact"] = unverified(f"oficjalne wagi {LK.MODEL['repo']}@{LK.MODEL['revision'][:8]} + {LK.TOKENIZER['repo']}@"
                                       f"{LK.TOKENIZER['revision'][:8]} niesprawdzalne bez środowiska .venv_kronos (load / prognoza)")
        return steps
    steps["env"] = ok(f".venv_kronos: {kpy}")
    ctx.step = "artifact"
    wd, src, problem = _kronos_official(ctx)
    if wd is None:
        return _kronos_fixture(ctx, kpy, steps, src)
    if problem:
        steps["artifact"] = fail(f"instalacja Kronos ({src}: {wd}) odrzucona: {problem}")
        return steps
    return _kronos_with_official(ctx, kpy, wd, src, steps)


# ------------------------------------------------------------------------------------------------------------------- Chronos-2 / Granite TTM / TiRex-2
def _broken_install(TL, TM, weights_root, mid: str) -> None:
    """A damaged installation: a valid manifest of the PINNED revision, but placeholder files (wrong size / sha256) - the bot must
    refuse it at load (CHECKSUM) and report the failure. Written only in the temporary data folder."""
    from datetime import datetime
    pin = TL.model(mid)
    d = TM.model_dir(weights_root, mid)
    d.mkdir(parents=True, exist_ok=True)
    files = []
    for name in pin["required_files"]:
        p = d / name
        p.write_bytes(b"{}" if name.endswith(".json") else b"\0" * 64)
        files.append({"name": name, "size": p.stat().st_size, "sha256": TM.sha256_file(p)})
    TM.write(weights_root, mid, {"schema": TL.MANIFEST_SCHEMA, "model_id": mid, "repo": pin["repo"], "revision": pin["revision"],
                                 "installed_at": datetime.now(UTC).isoformat(timespec="seconds"), "files": files})


def _tsfm_official_root(ctx, TM, mid: str) -> tuple[str | None, str]:
    """Weights root with INSTALLED official weights of the pinned revision -> (root, source) or (None, why not). Candidates:
    tsfm_weights_candidates (read only). Taken when the bot's tsfm_runtime.manifest.summary says installed (pinned repo + revision, complete,
    never a test fixture); the sha256 check itself is the artifact step (manifest.verify)."""
    why = []
    with _env(MQ_TSFM_ALLOW_FIXTURE=None):
        for root, src in tsfm_weights_candidates(ctx):
            s = TM.summary(root, mid)
            if s["installed"]:
                return root, src
            why.append(f"{src}: {str(s['reason'])[:140]}")
    return None, "; ".join(why)


def _tsfm_official(ctx, mid: str, cid: str, steps: dict, st, base, root: str, src: str) -> dict:
    """Official weights: size + sha256 of every file (manifest + pin of lock.py, the bot's manifest.verify) and the git blob of the small
    pinned files -> TsfmService -> tsfm_runtime.worker on FakeMT5 bars -> READY record -> selftest / parity of the loaded worker -> a NEW
    worker process gives the same forecast -> the failure path (damaged installation in the temporary folder). One model process at a time."""
    import math

    from tsfm_runtime import lock as TL
    from tsfm_runtime import manifest as TM

    from ...tsfm import service as TS
    pin = TL.model(mid)
    ctx.step = "artifact"
    try:
        integ = TM.verify(root, mid)                 # offline: size + sha256 of every file vs the manifest AND the pin of lock.py
    except TM.ManifestError as exc:
        steps["artifact"] = fail(f"oficjalne wagi {pin['repo']}@{pin['revision'][:8]} ({src}: {root}) odrzucone: {exc.code} {exc.detail}")
        return steps
    # small files are pinned by their git blob sha1 (manifest.verify compares sha256 only) - the id the installer checked at download
    d = TM.model_dir(root, mid)
    blobs, bad = 0, []
    for f in pin["files"]:
        if f.get("git_blob_sha1") and (d / f["name"]).is_file():
            blobs += 1
            got = TM.git_blob_sha1(d / f["name"])
            if got != f["git_blob_sha1"]:
                bad.append(f"{f['name']}: git blob {got[:12]}… ≠ przypięty {f['git_blob_sha1'][:12]}…")
    if bad:
        steps["artifact"] = fail(f"oficjalne wagi {pin['repo']}@{pin['revision'][:8]} ({src}): {'; '.join(bad)} (plik zmieniony po instalacji)")
        return steps
    big = max(integ["files"], key=lambda f: f["size"])
    sha_txt = f"{len(integ['files'])} plików, {big['file']} sha256 {big['sha256'][:12]}… = przypięta" + (f", git blob {blobs} = przypięte" if blobs else "")

    ctx.step = "predict"
    st.update({"weights_root": root}, who="smoke")
    c = st.get().models[mid]
    core = _core(ctx)
    H = int(st.get().horizon_bars["M5"])
    k = (mid, INST, "M5")

    def service():
        return TS.TsfmService(core["cfg"], core["bridge"], core["db"], core["bus"], core["log"], settings=st)
    svc, svc2 = service(), None
    try:
        with _env(MQ_TSFM_ALLOW_FIXTURE=None, HF_HUB_OFFLINE="1"):
            svc.tick(force=(INST, "M5"))
            w = svc.workers[mid]
            if not svc.queue:
                tv = svc.target_view(k)
                steps["predict"] = fail(f"oficjalne wagi zainstalowane, a brak zadania po nowej świecy: model {w.state['status']} "
                                        f"({str(w.state.get('reason'))[:120]}), cel {tv['state']} ({tv.get('reason')})")
                return steps
            _, job = svc.queue.popitem(last=False)
            fc = svc.run_job(job)
            recs = _adapter_records(cid, tsfm=svc)
            ctx.step = "contract"
            steps["contract"] = ctx.contract_step(recs)
            ctx.step = "predict"
            if fc is None:
                tv = svc.target_view(k)
                steps["predict"] = fail(f"run_job bez prognozy na oficjalnych wagach: model {w.state['status']}/{w.state.get('code')} "
                                        f"({str(w.state.get('reason'))[:160]}), cel {tv['state']} ({tv.get('reason')})")
                return steps
            li = w.load_info or {}
            pts = [float(p["point"]) for p in fc["path"]]
            ready = [p for p in recs if p["state"] == "READY"]
            last = fc["path"][-1]
            native = [float(q) for q in pin.get("native_quantiles") or []]
            levels = [float(q) for q in fc.get("quantile_levels") or []]
            q_ok = (all(q in native for q in levels) and 0.5 in levels) if native else not levels
            qtxt = (f", q0.1–q0.9(H) {last['q0.1']:.3f}–{last['q0.9']:.3f}" if last.get("q0.1") is not None and last.get("q0.9") is not None
                    else ", bez kwantyli (model punktowy)")
            good = (len(pts) == H and all(math.isfinite(v) for v in pts) and li.get("params") == pin["params_measured"]
                    and li.get("revision") == fc["model_revision"] == pin["revision"] and fc["point_kind"] == pin["point"] and q_ok
                    and (li.get("checkpoint") or "BASE") == "BASE" and fc["mode"] == "SHADOW" and not fc["execution_permission"]
                    and fc["data_kind"] == "SYNTHETIC" and len(ready) == 1)
            steps["predict"] = check(
                good,
                f"TsfmService → tsfm_runtime.worker ({li.get('device')}, {li.get('params')} param. = przypięte, {pin['repo']}@{pin['revision'][:8]}): "
                f"READY, {len(pts)} kroków M5, {fc['point_kind']}(H)={fc['pred_close_h']:.3f}{qtxt}, {fc['direction']}, SHADOW, {fc['compute_ms']} ms, "
                f"ładowanie {li.get('load_ms')} ms; dane SYNTHETIC (FakeMT5) – test techniczny, nie jakość",
                f"prognoza niezgodna: kroki {len(pts)}/{H}, param. {li.get('params')} vs {pin['params_measured']}, rewizja {li.get('revision')}, "
                f"punkt {fc.get('point_kind')} vs {pin['point']}, kwantyle {levels} vs natywne {native}, tryb {fc.get('mode')}, "
                f"dane {fc.get('data_kind')}, rekordy {[p['state'] for p in recs]}")
            if steps["predict"]["status"] != "OK":
                return steps

            # -- selftest / parity of the LOADED worker (what the installer runs after an installation) + NEW process -> same forecast
            ctx.step = "artifact"
            stt = w.ask({"cmd": "selftest"}, c.request_timeout_s)
            par = (stt.get("parity") or {}) if stt.get("ok") else {}
            if not (stt.get("ok") and (stt.get("smoke") or {}).get("ok") and par.get("status") == "PASS"):
                steps["artifact"] = fail(f"{sha_txt}; selftest workera: {stt.get('code') or ''} {stt.get('error') or ''} parity {par.get('status')} "
                                         f"(max |Δ| {par.get('max_abs_diff')})")
                return steps
            p1 = (w.info or {}).get("pid")
            w.kill()                                     # one model process at a time (TiRex-2 ≈ 1 GB RSS per process)
            svc2 = service()
            fc2 = svc2.run_job(job)
            if fc2 is None:
                w2 = svc2.workers[mid]
                steps["artifact"] = fail(f"{sha_txt}; ponowne wczytanie w nowym procesie bez prognozy: {w2.state['status']} ({w2.state.get('reason')})")
                return steps
            diff = max(abs(a - float(b["point"])) for a, b in zip(pts, fc2["path"], strict=True))
            p2 = (svc2.workers[mid].info or {}).get("pid")
            steps["artifact"] = check(
                diff <= 1e-9 and p1 != p2,
                f"oficjalne wagi {pin['repo']}@{pin['revision'][:8]} ({src}): {sha_txt}; selftest parity PASS (max |Δ| {par['max_abs_diff']:.3g}); "
                f"nowy proces workera → ta sama prognoza (różnica {diff:.1g})",
                f"{sha_txt}; nowy proces workera (pid {p1} → {p2}): różnica ścieżki {diff:.3g} (model przypięty jako deterministyczny)")
            svc2.stop()
            svc2 = None

        # -- failure path: damaged installation (temporary folder) -> ERROR/CHECKSUM + an entry in the event log
        ctx.step = "predict"
        _broken_install(TL, TM, base / "models", mid)
        st.update({"weights_root": str(base / "models")}, who="smoke")
        n0 = len(core["db"].query("SELECT id FROM app_events WHERE category='TSFM'"))
        with _env(HF_HUB_OFFLINE="1"):
            svc.tick(force=(INST, "M5"))
            if svc.queue:
                _, job3 = svc.queue.popitem(last=False)
                svc.run_job(job3)
            else:
                w.ensure()
        ev = [e for e in core["db"].query("SELECT level, code FROM app_events WHERE category='TSFM'")[n0:] if e["code"] == "CHECKSUM"]
        recs3 = _adapter_records(cid, tsfm=svc)
        steps["contract"] = ctx.contract_step(recs + recs3)
        if not (w.state["status"] == "ERROR" and w.state.get("code") == "CHECKSUM" and ev):
            steps["predict"] = fail(f"{steps['predict']['detail'][:200]} | uszkodzone wagi: stan {w.state['status']}/{w.state.get('code')}, "
                                    f"wpisy CHECKSUM w dzienniku: {len(ev)}")
        else:
            steps["predict"] = ok(f"{steps['predict']['detail'][:300]}; uszkodzone wagi → ERROR/CHECKSUM + wpis {ev[0]['level']}, rekord "
                                  f"{recs3[0]['state'] if recs3 else '-'}")
        return steps
    finally:
        svc.stop()
        if svc2 is not None:
            svc2.stop()


def _tsfm(mid: str):
    cid = f"tsfm:{mid}"

    def run(ctx) -> dict:
        import inspect
        import sys
        steps: dict = {}
        ctx.step = "import"
        from tsfm_runtime import lock as TL
        from tsfm_runtime import manifest as TM

        from ...events import AppLog
        from ...tsfm import predictions as TP  # noqa: F401 - the bot-side adapter module must import (used via modelhub.adapters)
        from ...tsfm import service as TS
        from ...tsfm import settings as TSS
        pin = TL.model(mid)
        steps["import"] = ok(f"masterquo.tsfm.service, masterquo.tsfm.predictions, tsfm_runtime.lock: {TL.fingerprint(mid)}")

        ctx.step = "env"
        base = ctx.data_dir / "tsfm_smoke" / mid
        st = TSS.SettingsStore(base / "settings.json")
        st.update({"weights_root": str(base / "models"),
                   "models": {m: {"enabled": m == mid, "instruments": [INST], "timeframes": ["M5"], "cpu_threads": 1, "device": "CPU"}
                              for m in TSS.MODEL_IDS}}, who="smoke")
        c = st.get().models[mid]
        py = TSS.find_python(mid, c)
        venv = pin.get("venv") or f".venv_{mid}"
        code = pin.get("code") or {}
        if py is None:
            steps["env"] = unverified(f"brak {venv} (MQ_{mid.upper()}_PYTHON) – pakiet {code.get('package')}=={code.get('version')} niezainstalowany "
                                      f"(tools/tsfm_setup.py --model {mid}) – silnik niesprawdzalny w tym środowisku")
            steps["artifact"] = unverified(f"oficjalne wagi {pin['repo']}@{pin['revision'][:8]} ({pin.get('params_upstream')}) niesprawdzalne bez "
                                           f"środowiska modelu – load / parity selftest niesprawdzone")
        else:
            steps["env"] = ok(f"{venv}: {py}")
            official, src = _tsfm_official_root(ctx, TM, mid)
            if official is not None:
                return _tsfm_official(ctx, mid, cid, steps, st, base, official, src)
            steps["artifact"] = unverified(f"oficjalne wagi {pin['repo']}@{pin['revision'][:8]} ({pin.get('params_upstream')}) niezainstalowane "
                                           f"({src[:220]}) – ustaw MQ_TSFM_WEIGHTS_ROOT na folder wag instalatora (tools/tsfm_setup.py --weights-root)")

        # -- real TsfmService on the FakeMT5 bridge: state without an environment / weights + the contract record
        ctx.step = "predict"
        core = _core(ctx)
        svc = TS.TsfmService(core["cfg"], core["bridge"], core["db"], core["bus"], core["log"], settings=st)
        try:
            svc.tick(force=(INST, "M5"))
            w = svc.workers[mid]
            s1, reason1 = w.state["status"], str(w.state.get("reason") or "")
            ms1 = svc._ms((mid, INST, "M5"))["state"]
            recs = _adapter_records(cid, tsfm=svc)
            exp_status = "NOT_INSTALLED" if py is None else "NO_WEIGHTS"
            state_ok = s1 == exp_status and ms1 == "MODEL_UNAVAILABLE" and not svc.queue and len(recs) == 1 and recs[0]["state"] == "DISABLED"
            state_txt = f"{s1} → cel MODEL_UNAVAILABLE, rekord {recs[0]['state'] if recs else '-'} z powodem („{reason1[:40]}…”), bez zadania"
            if not state_ok:
                steps["predict"] = fail(f"stan bez środowiska/wag niezgodny: oczekiwano {exp_status}/MODEL_UNAVAILABLE/DISABLED, jest {s1}/{ms1}/"
                                        f"{[p['state'] for p in recs]}, kolejka {len(svc.queue)}")
                steps["contract"] = ctx.contract_step(recs)
                return steps

            # -- failure path of the model process: damaged installation -> CHECKSUM -> ERROR state AND an entry in the event log
            _broken_install(TL, TM, base / "models", mid)
            n0 = len(core["db"].query("SELECT id FROM app_events WHERE category='TSFM'"))
            with _env(**({f"MQ_{mid.upper()}_PYTHON": sys.executable} if py is None else {}), HF_HUB_OFFLINE="1"):
                svc.tick(force=(INST, "M5"))
                if svc.queue:
                    _, job = svc.queue.popitem(last=False)
                    svc.run_job(job)
                    via = "tick → run_job → ModelWorker.ensure"
                else:                                    # data state blocked the job: the same ensure() the job would call first
                    w.ensure()
                    via = f"ModelWorker.ensure (cel {svc._target((INST, 'M5'))['state']})"
            s2, code2 = w.state["status"], w.state.get("code")
            ev = core["db"].query("SELECT level, code, message FROM app_events WHERE category='TSFM'")[n0:]
            recs2 = _adapter_records(cid, tsfm=svc)
            steps["contract"] = ctx.contract_step(recs + recs2)
            if not (s2 == "ERROR" and code2 == "CHECKSUM"):
                steps["predict"] = fail(f"uszkodzone wagi nie dały ERROR/CHECKSUM ({via}): stan {s2}/{code2} ({str(w.state.get('reason'))[:150]})")
                return steps
            logged = [e for e in ev if e["code"] == "CHECKSUM"]
            if not logged:
                src_lines, first = inspect.getsourcelines(TS.ModelWorker.fail)
                ln = next((first + i for i, t in enumerate(src_lines) if "applog.warning" in t), first)
                wl = inspect.getsourcelines(AppLog.warn)[1]
                steps["predict"] = fail(
                    f"awaria {code2} (uszkodzone wagi; {via}) NIE trafiła do app_events: tsfm/service.py:{ln} woła applog.warning, a AppLog "
                    f"ma warn (events.py:{wl}), hasattr(AppLog,'warning')={hasattr(AppLog, 'warning')} – AttributeError połknięty (service.py:"
                    f"{ln + 1}-{ln + 2}). Poza tym poprawnie: ERROR/CHECKSUM, rekord {recs2[0]['state'] if recs2 else '-'}; {state_txt}")
                return steps
            steps["predict"] = ok(f"{state_txt}; uszkodzone wagi → ERROR/CHECKSUM + wpis {logged[0]['level']} w dzienniku, rekord "
                                  f"{recs2[0]['state'] if recs2 else '-'}")
            return steps
        finally:
            svc.stop()
    run.__name__ = f"_tsfm_{mid}"
    return run


# ------------------------------------------------------------------------------------------------------------------- research modules (1.41)
class _Feed:
    """Bar source of the research MAIN context (rt.bridge duck type: cfg.symbol + bars(tf, include_forming=False)): closed FakeMT5 bars
    (ctx.bars) revealed up to `cursor` (UTC), so new closed bars can be fed one by one instead of waiting for the real clock."""
    TF_S: ClassVar[dict[str, int]] = {"M5": 300, "M15": 900, "H1": 3600}

    def __init__(self, ctx, symbol: str, hold_m5: int = 16):
        from types import SimpleNamespace
        self.cfg = SimpleNamespace(symbol=symbol)
        self.rows = {tf: ctx.bars(tf, n) for tf, n in (("M5", 1700), ("M15", 420), ("H1", 760))}
        last = self.rows["M5"][-1]["t"] + 300
        self.cursor = last - hold_m5 * 300                 # the last `hold_m5` closed M5 bars are revealed later

    def bars(self, tf: str, limit: int | None = None, include_forming: bool = True) -> list[dict]:
        rows = self.rows.get(tf)
        if rows is None:
            raise KeyError(tf)                             # e.g. DXY_H1: no such series in this terminal
        out = [dict(r) for r in rows if r["t"] + self.TF_S[tf] <= self.cursor]
        return out[-limit:] if limit else out

    def advance(self, n_m5: int = 1) -> None:
        self.cursor += 300 * n_m5


def _research_service(ctx, name: str, patch: dict, feed=None):
    from types import SimpleNamespace

    from ...research.service import ResearchModulesService
    feed = feed or _Feed(ctx, ctx.fake().symbol)
    rt = SimpleNamespace(bridge=feed, demo=True, sh=None, modes=None)
    svc = ResearchModulesService(rt, data_dir=ctx.data_dir / "research_smoke" / name)
    if patch:
        svc.update_settings(patch, who="smoke")
    return svc, feed, rt


def _research_main(ctx) -> dict:
    """One research service (graph + ETC + G7; SDformerFlow and the optimiser off) shared by graph50 and G7 - like the bot's single owner."""
    b = getattr(ctx, "_kt_research", None)
    if b is None:
        svc, feed, rt = _research_service(ctx, "main", {"modules": {"sdformerflow": {"enabled": False}}, "optimizer": {"enabled": False}})
        r = svc.cycle()
        b = {"svc": svc, "feed": feed, "rt": rt, "first": r}
        ctx._kt_research = b
    return b


def _graph50(ctx) -> dict:
    import copy
    import math

    import numpy as np

    from ...research import graph_ca as GR
    from ...research.service import ResearchModulesService
    steps: dict = {}
    ctx.step = "train"
    b = _research_main(ctx)
    svc, feed = b["svc"], b["feed"]
    c = svc.ensure_main_context()
    if c is None or not any(s.pending for s in c.graph.values()):
        steps["train"] = fail(f"pierwszy cykl bez predykcji grafu: {b['first']}")
        return steps
    w0 = {t: s.W.copy() for t, s in c.graph.items()}
    v0 = {t: s.version for t, s in c.graph.items()}
    matured = 0
    for _ in range(12):                                     # BPC10 label = 10 bars later -> 12 new closed M5 bars
        feed.advance(1)
        r = svc.cycle()
        st = next(iter(r.values()))
        if st.get("state") != "UPDATED":
            steps["train"] = fail(f"cykl bez aktualizacji po nowej świecy: {st}")
            return steps
    for t, s in c.graph.items():
        matured += s.version - v0[t]
    dW = {t: float(np.abs(s.W - w0[t]).sum()) for t, s in c.graph.items()}
    vers = {t: s.version for t, s in c.graph.items()}
    steps["train"] = check(all(v > v0[t] for t, v in vers.items()) and all(x > 0 for x in dW.values()),
                           f"uczenie online (Hebb + PnL komórek) po dojrzeniu etykiet, 13 cykli ResearchModulesService: wersje {vers}, "
                           f"|ΔW| L1 {', '.join(f'{k}={v:.3g}' for k, v in dW.items())}",
                           f"brak aktualizacji grafu po 12 nowych świecach: wersje {v0} → {vers}, |ΔW| {dW}")
    if steps["train"]["status"] != "OK":
        return steps

    # -- artifact: state saved by stop() (ctx_<hash>.json) -> a NEW service instance loads it -> same state and same prediction
    ctx.step = "artifact"
    svc.stop()
    svc2 = ResearchModulesService(b["rt"], data_dir=svc.base)
    c2 = svc2.ensure_main_context()
    m5 = c.bars_fn("M5", 1500)
    raw, _ = GR.extract(m5)
    diffs, hashes_ok = [], True
    for t in GR.TARGETS:
        a, z = c.graph[t], c2.graph[t]
        hashes_ok &= GR.state_hash(a.to_dict()) == GR.state_hash(z.to_dict())
        pa = copy.deepcopy(a).predict("rt", m5[-1]["t"], m5[-1]["c"], raw)["raw_score"]
        pz = copy.deepcopy(z).predict("rt", m5[-1]["t"], m5[-1]["c"], raw)["raw_score"]
        diffs.append(abs(pa - pz))
    steps["artifact"] = check(hashes_ok and max(diffs) == 0.0,
                              f"zapis stanu kontekstu (graf 50×50 + {c.graph['BPC10'].cells.n} komórek, wersje {vers}) → nowa instancja "
                              f"serwisu: hash stanu zgodny, różnica predykcji {max(diffs):.1g}",
                              f"roundtrip stanu grafu: hash zgodny={hashes_ok}, różnica predykcji {max(diffs):.3g}")
    b["svc"] = svc2                                         # the reloaded service continues (as after a restart of the bot)

    # -- predict: next closed bar on the reloaded service -> PMW-PRED-2 records research:graph50:<target>
    ctx.step = "predict"
    feed.advance(1)
    svc2.cycle()
    recs = _adapter_records("research:graph50", research=svc2)
    ready = [p for p in recs if p["state"] == "READY"]
    vals = {p["task"]: p["result"]["raw_score"] for p in ready}
    good = len(ready) == len(GR.TARGETS) and all(math.isfinite(v) and -1.0 <= v <= 1.0 for v in vals.values())
    steps["predict"] = check(good, "ResearchModulesService.predictions: READY " + ", ".join(f"{k}={v:+.3f}" for k, v in vals.items())
                             + " (DIRECTION_SCORE_RAW, nieskalibrowany, dane SYNTHETIC)",
                             f"rekordy grafu: {[(p.get('task'), p['state'], p.get('unavailable_reason')) for p in recs]}")
    ctx.step = "contract"
    steps["contract"] = ctx.contract_step(recs)
    return steps


def _g7(ctx) -> dict:
    import math
    steps: dict = {}
    ctx.step = "predict"
    b = _research_main(ctx)
    svc, feed = b["svc"], b["feed"]
    feed.advance(1)
    svc.cycle()
    sn = svc.latest(INST) or {}
    g = (sn.get("modules") or {}).get("g7_smc_radar") or {}
    recs = _adapter_records("research:g7_smc_radar", research=svc)
    if not g or len(recs) != 1 or recs[0]["state"] != "READY":
        steps["predict"] = fail(f"brak wyniku G7 w snapshocie / rekordu READY: moduły {list(sn.get('modules') or {})}, "
                                f"rekordy {[(p['state'], p.get('unavailable_reason')) for p in recs]}")
        return steps
    comp = g["components"]
    # the source rule: netFVG +-30, OB(H1) +-40, DXY corr < -30 -> +30; opposite netFVG / OB -> x0.5 (int)
    exp = (30 if comp["net_fvg"] > 0 else -30 if comp["net_fvg"] < 0 else 0) + (40 if comp["ob_h1"] > 0 else -40 if comp["ob_h1"] < 0 else 0)
    exp += g["dxy_term"]
    if g["conflict"]:
        exp = int(exp * 0.5)
    score = recs[0]["result"]["raw_score"]
    no_dxy = comp["dxy_corr_h1_levels"] is None and g["coverage"] == 0.75 and bool(g.get("reason"))
    steps["predict"] = check(
        float(exp) == score and math.isfinite(score) and -100 <= score <= 100 and no_dxy,
        f"radar G7 (M5/M15/H1) w cyklu serwisu: wynik {score:+.0f} = reguła źródła z FVG M5 {comp['fvg_m5']:+d}, M15 {comp['fvg_m15']:+d}, "
        f"OB H1 {comp['ob_h1']:+d}, konflikt {g['conflict']}; DXY brak → składowa nieobecna, coverage {g['coverage']}",
        f"wynik {score} ≠ reguła źródła {exp} albo pokrycie bez DXY niepoprawne (coverage {g.get('coverage')}, corr {comp.get('dxy_corr_h1_levels')})")
    ctx.step = "contract"
    cs = ctx.contract_step(recs)
    if cs["status"] == "OK" and recs[0]["unit"] == "score_0_100":
        # the radar declares the scale -100..100 (research/g7.py); the record says score_0_100 - reported, the contract does not range-check it
        cs = ok(cs["detail"] + f"; uwaga: jednostka rekordu score_0_100, a skala radaru '{g.get('scale')}' (wartości ujemne możliwe)")
    steps["contract"] = cs
    return steps


def _line_of(path, needle: str) -> int | None:
    """First line number of `needle` in a source file (evidence file:line, computed - not hard-coded)."""
    try:
        return next((i for i, t in enumerate(path.read_text(encoding="utf-8").splitlines(), 1) if needle in t), None)
    except OSError:
        return None


def _sdf_diag(py: str, svc, run_id) -> str:
    """Re-run the service's activation test (sdformer_runtime.infer, same checkpoint, same bars, same environment flags) and keep its
    stderr - the service reads only stdout, so the cause of a failed activation is otherwise lost."""
    import re
    import subprocess

    from ... import paths
    d = svc._sdf_dir()
    data = d / "activation_test_h1.json" if (d / "activation_test_h1.json").is_file() else d / "bootstrap_h1.json"
    be = paths.ROOT_DIR / "backend"
    r = subprocess.run([py, "-m", "sdformer_runtime.infer", "--checkpoint", str(d / str(run_id)), "--bars", str(data)], cwd=str(be),
                       env=dict(os.environ, PYTHONPATH=str(be), PYTHONNOUSERSITE="1"), capture_output=True, text=True, timeout=120, check=False)
    err = r.stderr or ""
    m = re.search(r"Unsupported global: GLOBAL ([\w.]+)", err)
    if m:
        out = (f"sdformer_runtime/infer.py:{_line_of(be / 'sdformer_runtime' / 'infer.py', 'weights_only=True')} torch.load(weights_only=True)"
               f" → UnpicklingError: Unsupported global {m.group(1)}")
        if m.group(1).endswith("TorchVersion"):
            ln = _line_of(be / "sdformer_runtime" / "train.py", "torch.__version__")
            out += f" (checkpoint: deps.torch=torch.__version__, sdformer_runtime/train.py:{ln})"
    else:
        tail = [x for x in err.strip().splitlines() if x.strip()][-1:] or [r.stdout.strip()[-160:]]
        out = f"ponowny infer: kod {r.returncode}, {tail[0][:160]}"
    return out + f"; research/service.py:{_line_of(be / 'masterquo' / 'research' / 'service.py', 'line = (r.stdout')} czyta tylko stdout"


def _sdformer(ctx) -> dict:
    import math
    import time

    from ...research import service as RS
    steps: dict = {}
    ctx.step = "env"
    py = RS.torch_python()
    src = "research.service.torch_python"
    extra: dict = {}
    if py is None:
        # the bot looks for ANY model environment with torch 2.14.1 (.venv_deep, .venv_kronos, ...) under the program folder, then
        # MQ_SDF_PYTHON; the smoke maps the environments given to `models check` (MQ_DEEP_PYTHON / MQ_KRONOS_PYTHON) onto MQ_SDF_PYTHON
        for v in (".venv_deep", ".venv_kronos"):
            cand = ctx.env_python(v)
            if cand:
                py, src, extra = cand, f"MQ_SDF_PYTHON ← {v}", {"MQ_SDF_PYTHON": cand}
                break
    if py is None:
        steps["env"] = unverified("brak środowiska z torch 2.14.1 (.venv_tirex2 / .venv_deep / .venv_kronos ani MQ_SDF_PYTHON) – "
                                  "SDformerFlow niesprawdzalny (stan WAITING_DEPENDENCY)")
        return steps
    steps["env"] = ok(f"torch: {py} ({src})")
    with _env(**extra):
        # -- train: the bot's own bootstrap (no checkpoint -> ONE from_scratch job on the H1 history), smallest budget
        ctx.step = "train"
        patch = {"modules": {"cellular_feature_graph": {"enabled": False}, "g7_smc_radar": {"enabled": False}}, "optimizer": {"enabled": False},
                 "sdformer": {"epochs": 1, "minutes": 0.5, "batch": 64, "threads": 1}}
        svc, feed, _ = _research_service(ctx, "sdformer", patch)
        try:
            svc.cycle()
            c = svc.ensure_main_context()
            job = svc.jobs.get("sdformer_bootstrap")
            if not job:
                steps["train"] = fail(f"cykl nie uruchomił bootstrapu: stan SDformerFlow {(c.sdf or {}).get('state')} ({(c.sdf or {}).get('reason')})")
                return steps
            t0 = time.monotonic()
            while time.monotonic() - t0 < 150 and (job.get("state") == "RUNNING" or (job.get("state") == "DONE" and "activation" not in job)):
                time.sleep(0.5)
            res = job.get("result") or {}
            act = job.get("activation") or {}
            hist = res.get("history") or [{}]
            steps["train"] = check(
                job.get("state") == "DONE" and bool(res.get("weights_changed")) and (res.get("epochs_done") or 0) >= 1,
                f"bootstrap from_scratch (sdformer_runtime.train, profil direct_train, 1 epoka / 0,5 min): {res.get('samples')} próbek H1, "
                f"{res.get('params')} param., {res.get('steps')} kroków, strata {hist[-1].get('train_loss', float('nan')):.4f}"
                f"{' (epoka częściowa)' if hist[-1].get('partial_epoch') else ''}, {res.get('seconds')} s",
                f"trening: stan {job.get('state')}, błąd {job.get('error')}, wynik {str(res)[:200]}")
            if steps["train"]["status"] != "OK":
                return steps

            # -- artifact: technical check + atomic activation by the service (DIRECT_USER_REQUEST); then a NEW service instance infers
            # from the stored checkpoint on the same bars -> the same score
            ctx.step = "artifact"
            run = svc.settings()["sdformer"].get("active_run")
            ck = svc._sdf_dir() / str(run) / "last.pt"
            if act.get("state") != "ACTIVE" or not ck.is_file():
                steps["artifact"] = fail(f"aktywacja {res.get('run_id')}: {act.get('state')} ({str(act.get('reason'))[:40]}…, szczegół bota "
                                         f"'{str(act.get('detail'))[:40]}'); {_sdf_diag(py, svc, res.get('run_id'))}")
                # the live path after a failed activation: no active version -> ERROR state, no READY record
                ctx.step = "predict"
                feed.advance(12)
                svc.cycle()
                recs = _adapter_records("research:sdformerflow", research=svc)
                steps["predict"] = fail(f"następstwo błędu artefaktu: stan SDformerFlow {(c.sdf or {}).get('state')} "
                                        f"({str((c.sdf or {}).get('reason'))[:120]}), rekordy PMW-PRED-2: {[p['state'] for p in recs] or 'brak'}")
                return steps
            ctx.step = "predict"
            feed.advance(12)                                 # one more closed H1 bar -> the live inference of the active version
            svc.cycle()
            sd = c.sdf or {}
            recs = _adapter_records("research:sdformerflow", research=svc)
            r1 = sd.get("result") or {}
            v = r1.get("direction_score_raw")
            ready = [p for p in recs if p["state"] == "READY"]
            steps["predict"] = check(
                sd.get("state") == "PREDICTION_ACTIVE" and v is not None and math.isfinite(v) and -1 <= v <= 1 and len(ready) == 1,
                f"sdformer_runtime.infer (proces, aktywna wersja {run}): DIRECTION_SCORE_RAW {v:+.4f} (tanh, nieskalibrowany), "
                f"embedding8, {r1.get('ms')} ms; rekord READY H1/H6" if v is not None else "",
                f"inferencja: stan {sd.get('state')} ({sd.get('reason')}), rekordy {[(p['state'], p.get('unavailable_reason')) for p in recs]}")
            ctx.step = "contract"
            steps["contract"] = ctx.contract_step(recs)
            ctx.step = "artifact"
            svc.stop()
            svc2, _, _ = _research_service(ctx, "sdformer", {}, feed=feed)
            try:
                svc2.cycle()
                sd2 = svc2.ensure_main_context().sdf or {}
            finally:
                svc2.stop()
            r2 = sd2.get("result") or {}
            if r2.get("direction_score_raw") is None:
                steps["artifact"] = fail(f"nowa instancja serwisu nie policzyła wyniku z zapisanego checkpointu: {str(sd2)[:300]}")
                return steps
            d = max([abs(r2["direction_score_raw"] - v)] + [abs(a - z) for a, z in zip(r1.get("embedding8") or [], r2.get("embedding8") or [])])
            steps["artifact"] = check(
                d <= 1e-9 and r2.get("bar_t") == r1.get("bar_t") and r2.get("run_id") == run,
                f"checkpoint {run}/last.pt: test techniczny + aktywacja atomowa (ACTIVE), nowa instancja serwisu → ta sama ocena i embedding "
                f"(różnica {d:.1g})",
                f"roundtrip checkpointu: różnica {d:.3g}, świeca {r1.get('bar_t')} vs {r2.get('bar_t')}, wersja {r2.get('run_id')} vs {run}")
            return steps
        finally:
            svc.stop()


SMOKES = {
    "kronos:Kronos-small": _kronos,
    "tsfm:chronos2": _tsfm("chronos2"),
    "tsfm:granite_ttm": _tsfm("granite_ttm"),
    "tsfm:tirex2": _tsfm("tirex2"),
    "research:graph50": _graph50,
    "research:g7_smc_radar": _g7,
    "research:sdformerflow": _sdformer,
}
NOT_CHECKABLE: dict[str, str] = {}
