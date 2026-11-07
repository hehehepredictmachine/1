"""Integration matrix of release 1.33.0 - ONE source for docs/INTEGRATION_MATRIX.md and integration_manifest.json.

Every requirement of the four specifications (AUD / IND / STU / ARC) is listed with: the module(s) that implement it, where it is
wired into the Runtime, what it feeds (analysis / strategies / panel / training / agent) and the test module(s) that prove it.
The script CHECKS what it can (every path and test module exists, every listed API route is registered in the source) and
writes the result; a missing file is reported as MISSING, never silently dropped.

  python tools/integration_matrix.py                  # write both files
  python tools/integration_matrix.py --results DIR    # + test results parsed from unittest logs DIR/<module>.log
  python tools/integration_matrix.py --check          # only verify (exit 1 on a MISSING path / route)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
B = "backend/masterquo/"
F = "frontend/src/"

# id, spec, title, modules, runtime wiring, receivers (analysis / strategies / panel / training / agent), routes, tests
R = [
    # ------------------------------------------------------------------ AUD - audit, 15 model families, training
    ("AUD-01", "AUD", "Kontrakt predykcji PMW-PRED-2 (liczby skończone, schematy wyników per zadanie, horyzont, proweniencja)",
     [B + "modelhub/contract.py"], "każdy producent prognoz (modelhub.adapters, families, kronos, trainhub)", "panel / SH / agent / koordynator",
     [], ["test_integration_u1", "test_families_u4"]),
    ("AUD-02", "AUD", "Interwał M3 w całym łańcuchu (rejestr TF, most MT5, fallback M1→M3, eksport, TrainHub, Kronos)",
     [B + "timeutil.py", B + "mt5/bridge.py", B + "mt5/fake.py"], "bridge TF_POLL / rejestr TF", "analiza, wykresy, trening",
     [], ["test_integration_u1", "test_bridge_engine", "test_ui_pages", "test_ui_signal_card"]),
    ("AUD-03", "AUD", "dxy_missing = rzeczywista dostępność DXY (MQ-FEAT-1.2.0 + adapter starszych modeli)",
     [B + "ml/features.py"], "MLService", "bramka ML ścieżki ACTIVE", [], ["test_integration_u1"]),
    ("AUD-04", "AUD", "Kronos REQUIRED powiązany z odciskiem (symbol, horyzont, ustawienia, pasmo, rewizje) – nieaktualne dopuszczenie wstrzymuje",
     [B + "kronos/predictions.py", B + "kronos/service.py"], "runtime.kronos → sh.kronos", "SCALPING / HEDGING", [], ["test_kronos_bot", "test_integration_u1"]),
    ("AUD-05", "AUD", "Wspólny adapter rodzin PMW-FAM-1: 3 osie stanu, magazyn artefaktów (manifest, sumy, próbka), aktywacja, rollback, role OFF/SHADOW/ASSIST",
     [B + "modelhub/families/base.py", B + "modelhub/families/service.py"], "runtime.families (FamilyService)", "SH (kontekst + ASSIST), ACTIVE (węzeł MODELS), panel, agent",
     ["/api/v1/families", "/api/v1/families/{fid}/activate", "/api/v1/families/{fid}/rollback", "/api/v1/families/{fid}/use"], ["test_families_u4"]),
    ("AUD-06", "AUD", "Izolowane środowisko .venv_deep i proces roboczy (PyTorch / Gymnasium / SB3)",
     ["backend/deep_runtime/worker.py", B + "modelhub/families/deep.py", "tools/deep_setup.py", "requirements/requirements-deep-win.txt", "34_DEEP_INSTALUJ.bat"],
     "FamilyService → deep worker (MQ_DEEP_PYTHON)", "trening / inferencja LSTM, GRU, PPO", [], ["test_families_u4"]),
    ("AUD-07", "AUD", "TrainHub: TH_RF, TH_SVM (kalibrowane), XGB natywny JSON, profile smoke/research/full, unikalne wersje, test wyniku po kalibracji",
     [B + "trainhub/learn.py", B + "trainhub/pipeline.py", B + "trainhub/cli.py"], "runtime.trainhub / trainhub_inference", "Centrum treningu, SH", [], ["test_trainhub"]),
    ("AUD-08", "AUD", "Instrukcje i skrypty treningu (35_RODZINY_MODELI.bat, menu 32 opcje 7 i 8, CLI families)",
     ["35_RODZINY_MODELI.bat", "32_CENTRUM_TRENINGU.bat", B + "modelhub/families/cli.py", "docs/INSTRUKCJA_TRENINGU_PL.md"], "–", "użytkownik", [], ["test_families_u4"]),
    ("AUD-09", "AUD", "Sekcja „Rodziny modeli 1.33” w Centrum treningu (stan, trening, aktywacja, rollback, użycie)",
     [F + "features/pmw133/FamiliesSection.tsx"], "panel → /api/v1/families/*", "panel", ["/api/v1/families/train-all", "/api/v1/families/predictions"],
     ["test_ui_pmw133", "test_ui_training_center"]),
    # ------------------------------------------------------------------ IND - indicators, DXY, plans, SVP
    ("IND-01", "IND", "Kontrakt wskaźników PMW-IND-1 (wartości, jednostki, czas źródła/dostępności, hash konfiguracji)",
     [B + "indicators/contract.py"], "IndicatorService", "kontekst analizy / SH / agent", [], ["test_indicators_u2"]),
    ("IND-02", "IND", "AVWAP SESSION / EVENT / MANUAL z pasmami σ, zdarzenia CROSS/RETEST, wersje kotwic",
     [B + "indicators/avwap.py"], "IndicatorService.compute", "kontekst ACTIVE (view.context), SH OBSERVE, wykres", ["/api/v1/indicators/chart", "/api/v1/indicators/anchors"],
     ["test_indicators_u2", "test_ui_pmw133"]),
    ("IND-03", "IND", "Spread względem tych samych slotów wcześniejszych sesji (próbkowanie stałym zegarem, percentyl)",
     [B + "indicators/spread.py"], "IndicatorService (próbki spread_samples)", "kontekst / panel", ["/api/v1/indicators/snapshot"], ["test_indicators_u2"]),
    ("IND-04", "IND", "Semiwariancja 20/60 M1 z obsługą luk", [B + "indicators/semivar.py"], "IndicatorService", "kontekst / panel", [], ["test_indicators_u2"]),
    ("IND-05", "IND", "Relacja XAUUSD × DXY na zwrotach H1 bez forward-fill (korelacja, beta bez bieżącej obserwacji, reszta z)",
     [B + "indicators/dxy.py"], "IndicatorService (dxy_bars)", "kontekst, agent get_dxy_relation, panel #/dxy", ["/api/v1/indicators/dxy"], ["test_indicators_u2", "test_ui_pmw133"]),
    ("IND-06", "IND", "Mikrostruktura: OFI, nierównowaga, microprice z arkusza MT5 (market_book_* przez kolejkę MT5) + archiwum",
     [B + "indicators/ofi.py", B + "mt5/fake.py"], "IndicatorService BookAdapter", "rodzina MICROSTRUCTURE, panel", [], ["test_indicators_u2", "test_families_u4"]),
    ("IND-07", "IND", "Cechy profilu sesji z DSVIE + RVOL z kontrolą historii i pokrycia",
     [B + "indicators/profile.py", B + "zones/dsvie.py"], "IndicatorService / ZonesService", "kontekst / strefy", [], ["test_indicators_u2", "test_zones"]),
    ("IND-08", "IND", "Plany Pepe Scalp Plan / Pepe Hedge Plan (PMW-PLAN-1): plan vs fill, SL v2 po BE, noga HEDGE, NETTING = niedostępne",
     [B + "plans/contract.py", B + "plans/service.py"], "SHService → plans.collect", "panel (warstwy wykresu)", ["/api/v1/plans/chart"], ["test_plans_svp_u3", "test_ui_pmw133"]),
    ("IND-09", "IND", "SVP PMW-SVP-1: profile SESSION/RANGE/VISIBLE/LIVE/FROZEN, strefy MANUAL/ALGORITHM/AI z wersjami, AI z walidacją snapshotu",
     [B + "svp/engine.py", B + "svp/zones.py", B + "svp/service.py", B + "agent/service.py"], "runtime.svp (SVPService)", "agent get_svp_profiles, panel #/svp, warstwa SVP",
     ["/api/v1/svp/profiles", "/api/v1/svp/zones", "/api/v1/svp/profiles/{pid}/ai-propose"], ["test_plans_svp_u3", "test_ui_pmw133"]),
    ("IND-10", "IND", "Narzędzia agenta: get_pmw_indicators, get_dxy_relation, get_svp_profiles (zamrożony snapshot)",
     [B + "agent/tools.py"], "engine.indicators_provider / svp_provider", "agent Claude", [], ["test_indicators_u2", "test_plans_svp_u3"]),
    ("IND-11", "IND", "Panel: #/dxy (XAUUSD × DXY i wskaźniki), #/svp (narzędzie SVP), warstwy Scalp Plan / Hedge Plan / AVWAP / SVP w każdym wykresie",
     [F + "features/pmw133/DxyPage.tsx", F + "features/pmw133/SvpPage.tsx", F + "features/pmw133/overlays.tsx", F + "components/ChartPanel.tsx"],
     "panel", "użytkownik", [], ["test_ui_pmw133", "test_ui_chart_prefs"]),
    # ------------------------------------------------------------------ STU - Data & Training Studio
    ("STU-01", "STU", "Osobna aplikacja Studio (proces, port 8780, własny katalog danych), bez Runtime bota i bez zleceń",
     [B + "studio/app.py", B + "studio/settings.py", B + "__main__.py", "36_STUDIO.bat"], "`python -m masterquo studio`", "trening / dane",
     ["/api/studio/health"], ["test_studio_u5"]),
    ("STU-02", "STU", "Blokada międzyprocesowa (O_EXCL + heartbeat) i wspólna blokada eksportu bota i Studio",
     [B + "studio/lock.py", B + "marketdata/export.py"], "Studio + eksport bota", "dane", [], ["test_studio_u5", "test_export_mt5"]),
    ("STU-03", "STU", "Rejestr 72 zadań (TRAINHUB / FAMILY / RUNNER_GROUP / DETERMINISTIC / PRETRAINED) + MODEL_DATA_MATRIX.json",
     [B + "studio/registry.py", "docs/MODEL_DATA_MATRIX.json"], "Studio", "trening", ["/api/studio/matrix"], ["test_studio_u5"]),
    ("STU-04", "STU", "Kolejka zadań (pauza, anulowanie, wznowienie, przesunięcie, przeniesienie) z trwałym stanem",
     [B + "studio/queue.py", B + "studio/jobrun.py"], "Studio", "trening", ["/api/studio/jobs"], ["test_studio_u5"]),
    ("STU-05", "STU", "Paczka per model: etapy RAW → walidacja → dataset → trening → ocena → test ładowania, atomowe zatwierdzenia i sumy",
     [B + "studio/package.py", B + "studio/pipeline.py", B + "studio/verify.py"], "Studio", "trening", [], ["test_studio_u5"]),
    ("STU-06", "STU", "Import paczki do bota (kandydat, nigdy auto-aktywacja), rollback, inbox przy starcie",
     [B + "studio/importer.py", B + "api/app.py", B + "runtime.py"], "Runtime: process_inbox() przy starcie", "modele bota",
     ["/api/v1/studio/import", "/api/v1/studio/imports"], ["test_studio_u5"]),
    ("STU-07", "STU", "PepeTrainingStudio.exe (tryb studio launchera Go) w paczce DESKTOP",
     ["desktop/main.go", "desktop/engine.go", "desktop/layout.go", "tools/build_desktop.py"], "launcher Go", "użytkownik", [], ["go test ./desktop"]),
    ("STU-08", "STU", "Przycisk „Studio” ze stanem w menu bota (pasek górny, menu CULT), uruchomienie jako osobny proces",
     [F + "features/pmw133/StudioButton.tsx", B + "api/app.py"], "API bota", "panel", ["/api/v1/studio/status", "/api/v1/studio/launch"], ["test_ui_pmw133"]),
    ("STU-09", "STU", "Frontend Studio (studio.html, 6 obszarów)", ["frontend/studio.html", F + "studio/main.tsx"], "Studio", "użytkownik", [], ["test_studio_u5"]),
    # ------------------------------------------------------------------ ARC - analysis / decision architecture
    ("ARC-01", "ARC", "10 kontraktów typowanych (InstrumentSpec … ExecutionOutcome)", [B + "decision/contracts.py"], "decision/*", "koordynator / ledger", [],
     ["test_decision_arc_u6"]),
    ("ARC-02", "ARC", "Role modeli OBSERVE / ASSIST / REQUIRED dla obu ścieżek (węzeł MODELS w drzewie ACTIVE, REQUIRED w SH)",
     [B + "decision/coordinator.py", B + "engine/decision.py", B + "engine/service.py", B + "sh/service.py"], "engine.arc / sh.arc", "strategie ACTIVE i SH",
     [], ["test_decision_arc_u6"]),
    ("ARC-03", "ARC", "Jeden Decision Coordinator i DecisionRecord obu ścieżek", [B + "decision/coordinator.py", B + "db/migrations/0025_decision_arc.sql", B + "runtime.py"],
     "runtime.arc (wspólny dla engine/gateway/SH/manager)", "audyt, panel #/decyzje", ["/api/v1/decision/status", "/api/v1/decision/records/{record_id}"],
     ["test_decision_arc_u6", "test_risk_execution"]),
    ("ARC-04", "ARC", "Wspólny portfel/ryzyko z atomową rezerwacją (BEGIN IMMEDIATE) obu ścieżek",
     [B + "decision/ledger.py", B + "execution/gateway.py", B + "sh/service.py"], "gateway.arc / sh.arc", "wykonanie nowych wejść", [], ["test_decision_arc_u6"]),
    ("ARC-05", "ARC", "Intencje wykonania: deduplikacja, UNKNOWN liczony do rekonsyliacji, rozliczanie z adapterów (bez ponownej wysyłki)",
     [B + "decision/ledger.py", B + "execution/manager.py"], "manager.tick → arc.sync()", "wykonanie", [], ["test_decision_arc_u6", "test_risk_execution", "test_sh_service"]),
    ("ARC-06", "ARC", "Replay stary (1.32) vs nowy (1.33): zapisane decyzje + scenariusz wyścigu", [B + "decision/replay.py"], "`python -m masterquo.decision.replay`",
     "walidacja", [], ["test_decision_arc_u6"]),
    ("ARC-07", "ARC", "Panel #/decyzje: ostatnie decyzje, rezerwacje, intencje, rekordy z rolami modeli", [F + "features/pmw133/DecisionPage.tsx"], "panel", "użytkownik", [],
     ["test_ui_pmw133"]),
    ("ARC-08", "ARC", "Execution Lock NIE przywrócony; tryby SIGNALS/PAPER/AUTO DEMO/AUTO LIVE, STOP i limity bez zmian",
     [B + "execution/modes.py"], "ModeManager", "wykonanie", [], ["test_execution_lock_withdrawn"]),
]

FAMILIES = ["TS_ARIMA", "TS_SARIMAX", "VOL_GARCH", "MICROSTRUCTURE", "PAIR_COINT", "STATARB", "KALMAN_LS", "BREAKOUT", "TH_RF", "TH_SVM", "TH_XGB",
            "SEQ_LSTM", "SEQ_GRU", "RL_PPO", "NLP_SENTIMENT"]


def _routes() -> set[str]:
    out = set()
    for p in (ROOT / B / "api/app.py", ROOT / B / "studio/app.py"):
        out |= set(re.findall(r'@app\.(?:get|post|put|patch|delete)\("([^"]+)"', p.read_text(encoding="utf-8")))
    return out


def _results(d: Path | None) -> dict:
    if not d:
        return {}
    out = {}
    for log in sorted(d.glob("*.log")):
        t = log.read_text(encoding="utf-8", errors="replace")
        ran = re.search(r"^Ran (\d+) tests? in", t, re.M)
        last = [x for x in t.strip().splitlines() if x.strip()][-1:] or [""]
        out[log.stem] = {"ran": int(ran.group(1)) if ran else None, "result": last[0][:80]}
    return out


def build(results_dir: Path | None) -> dict:
    routes = _routes()
    res = _results(results_dir)
    reqs, missing = [], []
    for rid, spec, title, mods, wiring, recv, rts, tests in R:
        m = [{"path": p, "exists": (ROOT / p).exists()} for p in mods]
        r = [{"route": x, "registered": x in routes} for x in rts]
        t = [{"test": x, "exists": x.startswith("go ") or (ROOT / "tests" / f"{x}.py").exists(), **({"run": res[x]} if x in res else {})} for x in tests]
        bad = [x["path"] for x in m if not x["exists"]] + [x["route"] for x in r if not x["registered"]] + [x["test"] for x in t if not x["exists"]]
        missing += [f"{rid}:{b}" for b in bad]
        reqs.append({"id": rid, "spec": spec, "title": title, "modules": m, "runtime": wiring, "receivers": recv, "routes": r, "tests": t,
                     "status": "MISSING:" + ",".join(bad) if bad else "IMPLEMENTED"})
    fam_dir = ROOT / B / "modelhub/families"
    reg = (fam_dir / "__init__.py").read_text(encoding="utf-8")
    fams = [{"family": f, "registered": f'"{f}"' in reg} for f in FAMILIES]
    missing += [f"FAMILY:{f['family']}" for f in fams if not f["registered"]]
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    except Exception:  # noqa: BLE001
        commit = None
    ver = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', (ROOT / B / "version.py").read_text(encoding="utf-8")).group(1)
    migs = sorted(p.name for p in (ROOT / B / "db/migrations").glob("*.sql"))
    new_files = sorted({p for _, _, _, mods, *_ in R for p in mods if (ROOT / p).exists()})
    return {"manifest": "PMW-INTEGRATION-1.33", "version": ver, "base": {"version": "1.32.0", "commit": "5e5d82a"}, "commit_at_generation": commit,
            "specs": {"AUD": "audyt modeli, 15 rodzin, trening", "IND": "wskaźniki, DXY, plany Scalp/Hedge, SVP", "STU": "Data & Training Studio",
                      "ARC": "architektura analizy i decyzji"},
            "requirements": reqs, "families": fams, "migrations": migs, "new_migration": "0025_decision_arc.sql",
            "config_sections_new": ["indicators", "families", "decision"],
            "files": [{"path": p, "sha256": hashlib.sha256((ROOT / p).read_bytes()).hexdigest()} for p in new_files],
            "summary": {"requirements": len(reqs), "implemented": sum(r["status"] == "IMPLEMENTED" for r in reqs), "missing": missing,
                        "by_spec": {s: sum(r["spec"] == s for r in reqs) for s in ("AUD", "IND", "STU", "ARC")}}}


def markdown(m: dict) -> str:
    L = [f"# Macierz integracji – PepeMarketWizard {m['version']}", "",
         "Wygenerowane przez `tools/integration_matrix.py` (jedno źródło z `integration_manifest.json`). Każdy wiersz: wymaganie specyfikacji → moduł → "
         "podłączenie w Runtime → odbiorcy (analiza / strategie / panel / trening / agent) → testy. Ścieżki, trasy API i pliki testów są sprawdzane "
         "przy generowaniu.", "",
         f"Wymagania: **{m['summary']['implemented']}/{m['summary']['requirements']}** zaimplementowane i podłączone; brakujące: "
         f"{', '.join(m['summary']['missing']) or 'brak'}. Rodziny modeli zarejestrowane: {sum(f['registered'] for f in m['families'])}/15.", ""]
    for spec, name in m["specs"].items():
        L += [f"## {spec} – {name}", "", "| ID | Wymaganie | Moduły | Runtime | Odbiorcy | API | Testy | Stan |", "|---|---|---|---|---|---|---|---|"]
        for r in (x for x in m["requirements"] if x["spec"] == spec):
            mods = "<br>".join(f"`{x['path'].replace('backend/masterquo/', '').replace('frontend/src/', 'fe/')}`" for x in r["modules"])
            rts = "<br>".join(f"`{x['route']}`" for x in r["routes"]) or "–"
            tests = "<br>".join(f"`{t['test']}`" + (f" ({t['run']['ran']}: {t['run']['result']})" if t.get("run") else "") for t in r["tests"])
            L.append(f"| {r['id']} | {r['title']} | {mods} | {r['runtime']} | {r['receivers']} | {rts} | {tests} | {r['status']} |")
        L.append("")
    L += ["## Rodziny modeli (AUD)", "", "| Rodzina | Zarejestrowana |", "|---|---|"] + [f"| {f['family']} | {'tak' if f['registered'] else 'NIE'} |" for f in m["families"]]
    L += ["", f"Migracje bazy: {len(m['migrations'])} (nowa: `{m['new_migration']}`, addytywna). Nowe sekcje konfiguracji: "
          + ", ".join(f"`{x}`" for x in m["config_sections_new"]) + " – wersja 1.32 ich nie zna (patrz instrukcja rollbacku)."]
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", type=Path, default=None)
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    m = build(a.results)
    if not a.check:
        (ROOT / "integration_manifest.json").write_text(json.dumps(m, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        (ROOT / "docs" / "INTEGRATION_MATRIX.md").write_text(markdown(m), encoding="utf-8")
    print(f"requirements {m['summary']['implemented']}/{m['summary']['requirements']}, missing: {m['summary']['missing'] or 'none'}")
    return 1 if m["summary"]["missing"] else 0


if __name__ == "__main__":
    sys.exit(main())
