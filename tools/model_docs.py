"""Model documentation of release 1.33 generated from the code (one source, no hand-copied tables):

  docs/MODEL_DATA_MATRIX.json        Studio task registry (studio/registry.matrix) - every trainable task, its data and adapter
  docs/MAPA_INTEGRACJI_MODELI.md     15 families: runtime, receivers (SH / ACTIVE / panel / agent), role rules
  docs/MODEL_DATA_REQUIREMENTS.md    data each family / Studio task needs (kind, TF, minimum, source)
  MODEL_CARDS/families/<ID>.md       model card per family
  docs/RAPORT_WALIDACJI_MODELI.md    from docs/RAPORT_WALIDACJI_MODELI.json (tools/validate_families_synthetic.py)

  python tools/model_docs.py      (needs the bot's Python environment; uses a temporary data folder, touches no artifact)
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

ROLE_RULES = ("OFF = nie liczy; SHADOW = liczy i zapisuje, rola OBSERVE (bez wpływu); ASSIST = tylko po walidacji APPROVED na danych REAL – "
              "może wyłącznie wstrzymać wejście (SH: READY→WAIT, ACTIVE: węzeł MODELS); REQUIRED = `config.decision.required_models` – brak / "
              "nieświeża / przeciwna prognoza blokuje nowe wejście. Żadna rola nie tworzy wejścia ani nie podnosi WAIT.")


def _catalog():
    os.environ.setdefault("MASTERQUO_DATA_DIR", tempfile.mkdtemp(prefix="pmw_docs_"))
    os.environ.setdefault("PMW_FAMILIES_DIR", tempfile.mkdtemp(prefix="pmw_docs_fam_"))
    from masterquo.config import ConfigStore
    from masterquo.modelhub.families.service import FamilyService
    return FamilyService(ConfigStore()).catalog("XAUUSD")


def _req(d: dict | None) -> str:
    d = d or {}
    parts = [d.get("kind") or "–"]
    if d.get("tf"):
        parts.append(d["tf"])
    if d.get("min_bars"):
        parts.append(f"≥ {d['min_bars']} świec")
    for k in ("schema", "exog", "source", "note"):
        if d.get(k):
            parts.append(str(d[k]))
    return ", ".join(parts)


def main() -> int:
    from masterquo.studio import registry as REG
    mat = REG.matrix()
    (ROOT / "docs" / "MODEL_DATA_MATRIX.json").write_text(json.dumps(mat, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    cat = _catalog()
    # ---------------------------------------------------------------- integration map
    L = ["# Mapa integracji modeli – 1.33.0 (PMW-FAM-1)", "", "Wygenerowane przez `tools/model_docs.py` z katalogu `FamilyService.catalog()`.", "",
         f"Role: {ROLE_RULES}", "", "| Rodzina | Nazwa | Zadanie / jednostka | TF / horyzonty | Środowisko | Zależności | Odbiorcy |", "|---|---|---|---|---|---|---|"]
    for f in cat:
        L.append(f"| `{f['id']}` | {f['name']} | {f['task_type']} / {f['unit']} | {f.get('tf') or '–'} / {', '.join(map(str, f.get('horizons') or [])) or '–'} | "
                 f"{f['runtime']} | {', '.join(f.get('deps') or []) or '–'} | {'<br>'.join(f.get('receivers') or [])} |")
    L += ["", "## Gdzie prognozy trafiają w działającym bocie", "",
          "* **SCALPING / HEDGING** – `SHService.evaluate` → `FamilyService.setup_context` (kontekst w setupie, `family_context`) i "
          "`apply_to_setup` (ASSIST: READY→WAIT z powodem w checklistcie); koordynator PMW-ARC-1 zapisuje DecisionRecord i stosuje REQUIRED.",
          "* **ACTIVE (S01–S12)** – `engine.light_cycle` → `DecisionCoordinator.model_gate_active` → węzeł `MODELS` drzewa decyzji (przed hashem "
          "decyzji), więc karta sygnału i bramka wykonania widzą ten sam werdykt.",
          "* **Panel** – Centrum treningu → „Rodziny modeli 1.33” (`/api/v1/families`, `/api/v1/families/predictions`); Koordynator decyzji (`#/decyzje`).",
          "* **Agent** – `modelhub.adapters.all_predictions` (kontekst rozmowy, zamrożony snapshot).",
          "* **TH_RF / TH_SVM / TH_XGB** – przez trainhub (Centrum treningu, paczki aktywowane ręcznie); **SEQ_GRU_EVENT** – adapter modelu zdarzeń MM.", ""]
    (ROOT / "docs" / "MAPA_INTEGRACJI_MODELI.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    # ---------------------------------------------------------------- data requirements
    L = ["# Wymagania danych modeli – 1.33.0", "", "Wygenerowane przez `tools/model_docs.py`. Za mało danych = trening odmawia z powodem (BLOCKED_DATA) – "
         "nic nie jest uzupełniane ani interpolowane. Dane syntetyczne nigdy nie dopuszczają roli ASSIST.", "",
         "## Rodziny modeli", "", "| Rodzina | Wymagane dane |", "|---|---|"]
    L += [f"| `{f['id']}` | {_req(f.get('data_requirements'))} |" for f in cat]
    L += ["", f"## Zadania Pepe Data & Training Studio ({mat['count']} – `docs/MODEL_DATA_MATRIX.json`)", "",
          "| Model | Zadanie | TF | H | Adapter | Źródła | Stan |", "|---|---|---|---|---|---|---|"]
    for r in mat["rows"]:
        src = "; ".join(f"{s.get('kind')} {s.get('tf') or ''}{'' if s.get('mandatory', True) else ' (opc.)'}".strip() for s in r.get("sources") or [])
        L.append(f"| `{r['model_id']}` | {r.get('task_id')} | {r.get('base_tf') or '–'} | {r.get('horizon') or '–'} | {r['adapter']} | {src or '–'} | "
                 f"{r['state']}{(': ' + r['reason']) if r.get('reason') else ''} |")
    (ROOT / "docs" / "MODEL_DATA_REQUIREMENTS.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    # ---------------------------------------------------------------- model cards
    val = {}
    vp = ROOT / "docs" / "RAPORT_WALIDACJI_MODELI.json"
    if vp.exists():
        val = {x["family"]: x for x in json.loads(vp.read_text(encoding="utf-8"))["families"]}
    cd = ROOT / "MODEL_CARDS" / "families"
    cd.mkdir(parents=True, exist_ok=True)
    for f in cat:
        v = val.get(f["id"]) or {}
        crit = (v.get("validation") or {}).get("criteria") or []
        L = [f"# Karta modelu – {f['id']}", "", f"**{f['name']}**", "",
             "| Pole | Wartość |", "|---|---|",
             f"| Rodzaj | {f['kind']} ({f.get('fit_label')}) |", f"| Zadanie | {f['task']} – typ PMW-PRED-2 `{f['task_type']}`, jednostka `{f['unit']}` |",
             f"| Interwał / horyzonty | {f.get('tf') or '–'} / {', '.join(map(str, f.get('horizons') or [])) or 'brak (pomiar stanu)'} |",
             f"| Środowisko | {f['runtime']} ({', '.join(f.get('deps') or []) or 'bez dodatkowych bibliotek'}) |",
             f"| Dane | {_req(f.get('data_requirements'))} |", f"| Odbiorcy | {', '.join(f.get('receivers') or [])} |",
             f"| Role | {ROLE_RULES} |", "",
             "## Walidacja", "",
             "Bramka promocji liczona wyłącznie na części rozwojowej (walidacja), holdout raportowany osobno; kryteria muszą być spełnione, "
             "inaczej artefakt ma stan VALIDATION_FAILED i nie może dostać roli ASSIST.", ""]
        if crit:
            L += [f"Kontrola potoku na danych SYNTETYCZNYCH (`tools/validate_families_synthetic.py`, profil {json.loads(vp.read_text())['profile']}): "
                  f"**{(v.get('validation') or {}).get('status')}**", "", "| Kryterium | Próg | Wartość | Spełnione |", "|---|---|---|---|"]
            L += [f"| {c['metric']} | {c['op']} {c['threshold']} | {c['value']:.6g} | {'tak' if c['passed'] else 'nie'} |" for c in crit]
        elif v.get("state") == "DELEGATED":
            L += [f"Trenowany poza magazynem rodzin: {v.get('reason')}."]
        L += ["", "## Ograniczenia", "", "* Ocena na danych historycznych nie jest obietnicą wyniku; READY oznacza zdolność zwrócenia wyniku, nie zgodę na handel.",
              "* Model nie składa zleceń; wynik niedostępny (BLOCKED_DATA / STALE / ERROR) nie ma wartości i nie jest traktowany jak neutralny.",
              "* Dane syntetyczne służą wyłącznie do sprawdzenia potoku – rola ASSIST wymaga walidacji na Twoich danych REAL z MT5.", ""]
        (cd / f"{f['id']}.md").write_text("\n".join(L), encoding="utf-8")
    # ---------------------------------------------------------------- validation report (md)
    if vp.exists():
        rep = json.loads(vp.read_text(encoding="utf-8"))
        L = ["# Raport walidacji modeli – 1.33.0", "", f"Źródło: `docs/RAPORT_WALIDACJI_MODELI.json` – `tools/validate_families_synthetic.py` "
             f"(profil **{rep['profile']}**, dane **{rep['data_kind']}**, {rep['generated_at']}, Python {rep['python']}, {rep['platform']}).", "",
             f"**Co to sprawdza:** {rep['note']}. Każda rodzina: trening → zapis (manifest + sumy) → ładowanie → predykcja zgodna z PMW-PRED-2 → "
             "bramka walidacji. Dane mają znaną strukturę (AR(1)+GARCH, para kointegrowana, koszyk 3 serii, arkusz z nierównowagą wyprzedzającą "
             "mid, oznaczony korpus nagłówków).", "",
             "**Czego nie sprawdza:** rentowności ani jakości na rzeczywistym XAUUSD/BTC – tego nie da się zrobić bez Twoich danych MT5. "
             "Przed rolą ASSIST każdą rodzinę trzeba wytrenować i zwalidować na danych REAL (Centrum treningu lub Studio).", "",
             "| Rodzina | Wynik treningu | Bramka | Kluczowe kryteria (walidacja) | Predykcja PMW-PRED-2 | Czas |", "|---|---|---|---|---|---|"]
        for x in rep["families"]:
            crit = (x.get("validation") or {}).get("criteria") or []
            cs = "; ".join(f"{c['metric']} {c['value']:.3g} {c['op']} {c['threshold']}" for c in crit) or (x.get("reason") or "–")
            pr = x.get("prediction") or {}
            ps = pr.get("state") or (("błąd: " + pr["error"]) if pr.get("error") else "–")
            L.append(f"| `{x['family']}` | {x['state']} | {(x.get('validation') or {}).get('status') or '–'} | {cs} | {ps} | {x.get('seconds')} s |")
        L += ["", "## Wnioski", "",
              "* Rodziny statystyczne i regułowe (ARIMA, SARIMAX, GARCH, Kalman, breakout, para, koszyk, mikrostruktura, NLP) przechodzą bramkę na danych "
              "o znanej strukturze – potok i kryteria działają.",
              "* **SEQ_LSTM, SEQ_GRU, RL_PPO przy profilu smoke nie przechodzą bramki** (ujemny zysk walidacyjny względem odniesienia). To zamierzone "
              "zachowanie bramki: budżet smoke (kilka epok / kroków) sprawdza tylko, że trening naprawdę zmienia parametry i że artefakt się ładuje; "
              "do oceny służą profile research / full na danych REAL. Artefakt VALIDATION_FAILED nie może dostać roli ASSIST.",
              "* **Naprawione w trakcie (audyt 1.33):** SARIMAX na H1 z grupowaniem zmienności nie zbiegał w żadnym dopasowaniu (stan BLOCKED). Przyczyna: "
              "surowe log-zwroty rzędu 1e-3 psuły skalowanie optymalizatora MLE. Poprawka: dopasowanie na zwrotach skalowanych do wariancji 1, skala "
              "zapisana w artefakcie, prognozy i błędy w jednostkach log-zwrotu; stare artefakty bez skali działają jak dotąd (skala 1). Test: "
              "`test_families_u4.test_sarimax_converges_on_h1_with_volatility_clustering`.",
              "* TH_RF / TH_SVM / TH_XGB – walidowane w `tests/test_trainhub.py` (22 testy); SEQ_GRU_EVENT – centrum MM (`test_mm_*`).", ""]
        (ROOT / "docs" / "RAPORT_WALIDACJI_MODELI.md").write_text("\n".join(L), encoding="utf-8")
    print(f"matrix {mat['count']} rows, {len(cat)} families, cards in {cd}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
