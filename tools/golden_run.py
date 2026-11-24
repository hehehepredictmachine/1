"""Golden run - przebieg referencyjny `serve --demo` na stałym zegarze, stałym ziarnie i stałych danych (refaktor 1.46+).

  python tools/golden_run.py run --out <folder> [--minutes 10] [--speed 1] [--start 2026-03-04T08:00:00] [--port 8861]
  python tools/golden_run.py replay --out <folder> [--days 20] [--m1-bars 6000]   (warstwa deterministyczna, ścisłe porównanie)
  python tools/golden_run.py compare <folder_A> <folder_B> [--report plik.md]

Jak to działa:
- zegar ścienny całego procesu silnika jest wirtualny (libfaketime: `faketime -f '@<start>'`, zegar monotoniczny prawdziwy) - start zawsze o tej samej chwili, potem płynie
  normalnie. Symulator MT5 (mt5/fake.py, ziarno 7) buduje historię od zegara, więc dane wejściowe są identyczne w każdym przebiegu;
- świeży, tymczasowy katalog danych (MASTERQUO_DATA_DIR) z tą samą konfiguracją: bez newsów, bez zegara z internetu, bez kreatora;
- PMW_BOOTSTRAP=0 (bez pobierania modeli w tle), bez klucza ANTHROPIC_API_KEY (agent nie odpowiada - deterministycznie);
- na końcu: migawka wybranych tras GET API, zatrzymanie przez `masterquo stop`, zrzut WSZYSTKICH tabel wszystkich baz SQLite
  z katalogu danych do JSONL (posortowane) + plików JSON stanu.
`compare` porównuje dwa przebiegi po normalizacji (bez kolumn zależnych od milisekund wykonania: czasy zapisu, opóźnienia, losowe id)
i wypisuje różnice tabela po tabeli. Dwa przebiegi NA TYM SAMYM KODZIE pokazują poziom szumu (kalibracja porównania).
Tryb wykonania nie jest zmieniany (domyślny z konfiguracji demo; LIVE zablokowany) - narzędzie niczego nie wysyła do MT5.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
GET_SNAPSHOTS = ["/api/v1/health", "/api/v1/state", "/api/v1/decision", "/api/v1/decision/status", "/api/v1/setups", "/api/v1/signals",
                 "/api/v1/bot-signals", "/api/v1/signal-history", "/api/v1/strategy/auto", "/api/v1/strategy/selection-log",
                 "/api/v1/sh/plans", "/api/v1/sh/signals", "/api/v1/sh/strategies", "/api/v1/baskets/signals", "/api/v1/eval/status",
                 "/api/v1/eval/assessments", "/api/v1/eval/report", "/api/v1/quant/status", "/api/v1/quant/assessment",
                 "/api/v1/quant/predictions", "/api/v1/models/predictions", "/api/v1/models/evidence", "/api/v1/ml/status",
                 "/api/v1/scalp/shadow", "/api/v1/forecast/shadow", "/api/v1/kronos", "/api/v1/models/foundation", "/api/v1/stats"]
# columns whose values depend on wall-clock jitter of the run (write time, latency) or are random - excluded from the comparison
VOLATILE_COL = re.compile(r"(^|_)(created|updated|written|received|inserted|saved|started|finished|ended|seen|checked|polled|sent|"
                          r"run|heartbeat|latency|elapsed|duration|took|ms|uuid|nonce|token|pid|rowid)(_at|_ts|_ms|_s|_utc)?$|"
                          r"^(id|ts|at|now|wall_ts|wall_time|computed_at|generated_at|as_of_wall)$", re.IGNORECASE)
UUIDISH = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b|\b(?:MTI|ATT|RUN|JOB)-[0-9a-f]{8,}\b", re.IGNORECASE)
ISO_MS = re.compile(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})\.\d+")


def _health(port: int):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/v1/health", timeout=3) as r:
            return json.loads(r.read())
    except Exception:  # noqa: BLE001
        return None


_OPENER = None


def _get(port: int, path: str):
    """GET with the panel session (1.46: the API answers 401 without the cookie issued by GET /)."""
    global _OPENER
    if _OPENER is None:
        import http.cookiejar
        _OPENER = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        _OPENER.open(f"http://127.0.0.1:{port}/", timeout=20).read()
    try:
        with _OPENER.open(f"http://127.0.0.1:{port}{path}", timeout=30) as r:
            return {"status": r.status, "body": json.loads(r.read() or b"null")}
    except urllib.error.HTTPError as e:
        return {"status": e.code, "body": None}
    except Exception as e:  # noqa: BLE001
        return {"status": None, "error": type(e).__name__}


def dump_sqlite(data_dir: Path, out: Path) -> dict:
    """Every table of every *.sqlite under the data dir -> <out>/db/<relpath>__<table>.jsonl (rows sorted, JSON-serialisable)."""
    summary = {}
    for db in sorted(data_dir.rglob("*.sqlite")):
        rel = db.relative_to(data_dir).as_posix().replace("/", "__")
        try:
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
            for t in tables:
                cols = [r[1] for r in con.execute(f'PRAGMA table_info("{t}")')]
                rows = [dict(zip(cols, [(v.hex() if isinstance(v, bytes) else v) for v in r])) for r in con.execute(f'SELECT * FROM "{t}"')]
                rows.sort(key=lambda d: json.dumps(d, sort_keys=True, default=str))
                p = out / "db" / f"{rel}__{t}.jsonl"
                p.parent.mkdir(parents=True, exist_ok=True)
                with p.open("w", encoding="utf-8") as f:
                    for r in rows:
                        f.write(json.dumps(r, sort_keys=True, default=str, ensure_ascii=False) + "\n")
                summary[f"{rel}::{t}"] = len(rows)
            con.close()
        except sqlite3.Error as e:
            summary[f"{rel}::<error>"] = str(e)
    return summary


def cmd_run(a) -> int:
    out = Path(a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    if not shutil.which("faketime"):
        print("[golden] brak programu faketime (apt-get install faketime) - zegar nie byłby stały", file=sys.stderr)
        return 2
    td = Path(tempfile.mkdtemp(prefix="pmw_golden_"))
    (td / "config.json").write_text(json.dumps({"server": {"port": a.port, "open_browser": False}, "news": {"enabled": False},
                                                "clock": {"reference_url": None}, "first_run_completed": True}), encoding="utf-8")
    env = dict(os.environ, MASTERQUO_DATA_DIR=str(td), PYTHONPATH=str(ROOT / "backend"), PMW_BOOTSTRAP="0", TZ="UTC",
               PYTHONHASHSEED="0", FAKETIME_DONT_FAKE_MONOTONIC="1")
    # FAKETIME_DONT_FAKE_MONOTONIC: with a faked CLOCK_MONOTONIC threading.Event.wait(timeout) computes its deadline from the fake
    # clock and the kernel waits ~forever (the MT5 bridge loop never polled: no quote, clock UNKNOWN) - only the wall clock is virtual
    for k in ("ANTHROPIC_API_KEY", "TELEGRAM_BOT_TOKEN", "MQ_FAKE_MARKET_ALWAYS_OPEN"):
        env.pop(k, None)
    start = a.start.replace("T", " ").rstrip("Z")
    spec = f"@{start}" + (f" x{a.speed:g}" if a.speed != 1 else "")      # faketime: start + optional clock rate (sleeps scale too)
    log = (out / "engine_console.log").open("w", encoding="utf-8")
    t0 = time.time()
    proc = subprocess.Popen(["faketime", "-f", spec, PY, "-m", "masterquo", "serve", "--demo", "--no-browser"], cwd=str(ROOT / "backend"),
                            env=env, stdout=log, stderr=subprocess.STDOUT)
    meta = {"start_virtual": a.start, "speed": a.speed, "minutes_real": a.minutes, "minutes_virtual": a.minutes * a.speed, "port": a.port, "seed": 7, "data_dir": str(td)}
    try:
        for _ in range(240):
            if _health(a.port):
                break
            if proc.poll() is not None:
                break
            time.sleep(0.5)
        meta["startup_s"] = round(time.time() - t0, 1)
        meta["health"] = _health(a.port)
        if not meta["health"]:
            print("[golden] serwer nie wystartował - patrz engine_console.log", file=sys.stderr)
            return 3
        end = time.time() + a.minutes * 60          # real minutes (virtual = minutes x speed)
        while time.time() < end and proc.poll() is None:
            time.sleep(5)
        snaps = {p: _get(a.port, p) for p in GET_SNAPSHOTS}
        (out / "api_snapshots.json").write_text(json.dumps(snaps, indent=1, sort_keys=True, default=str, ensure_ascii=False), encoding="utf-8")
    finally:
        subprocess.run([PY, "-m", "masterquo", "stop"], cwd=str(ROOT / "backend"), env=env, timeout=120, capture_output=True, check=False)
        try:
            proc.wait(timeout=60)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()
    meta["exit_code"] = proc.returncode
    meta["tables"] = dump_sqlite(td, out)
    for j in sorted(td.rglob("*.json")):
        if j.name == "config.json" or j.stat().st_size > 2_000_000:
            continue
        dst = out / "state" / j.relative_to(td)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(j, dst)
    (out / "meta.json").write_text(json.dumps(meta, indent=1, sort_keys=True, default=str), encoding="utf-8")
    shutil.rmtree(td, ignore_errors=True)
    print(f"[golden] gotowe: {out} ({sum(v for v in meta['tables'].values() if isinstance(v, int))} wierszy w "
          f"{len(meta['tables'])} tabelach)")
    return 0


REPLAY_VOLATILE = re.compile(r"^(elapsed_s|ms_per_step|seconds|duration_s|generated_at|started_at|finished_at|report|out|run_dir|path|"
                             r"created_at|computed_at|written_at)$")


def _replay_env(td: Path, sub: str) -> dict:
    env = dict(os.environ, MASTERQUO_DATA_DIR=str(td / sub), PYTHONPATH=str(ROOT / "backend"), PMW_BOOTSTRAP="0", TZ="UTC",
               PYTHONHASHSEED="0", FAKETIME_DONT_FAKE_MONOTONIC="1")
    for k in ("ANTHROPIC_API_KEY", "TELEGRAM_BOT_TOKEN", "MQ_FAKE_MARKET_ALWAYS_OPEN"):
        env.pop(k, None)
    return env


def cmd_replay(a) -> int:
    """Deterministic layer: path A (S01-S12, tools/replay_strategies.py --synthetic) and path B (SH pack-replay of the 20 variants
    PMW_SC01..HG10 on a SYNTHETIC_TEST dataset) on the simulator, under the fixed virtual clock. Same code -> byte-identical decisions
    (only run-time fields differ), so any difference after a refactor step is a real change of a decision."""
    out = Path(a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    if not shutil.which("faketime"):
        print("[golden] brak programu faketime (apt-get install faketime)", file=sys.stderr)
        return 2
    td = Path(tempfile.mkdtemp(prefix="pmw_golden_replay_"))
    spec = "@" + a.start.replace("T", " ").rstrip("Z")
    meta = {"start_virtual": a.start, "seed": 7, "days_A": a.days, "m1_bars_B": a.m1_bars}
    try:
        t0 = time.time()
        pa = subprocess.run(["faketime", "-f", spec, PY, str(ROOT / "tools" / "replay_strategies.py"), "--synthetic", str(a.days), "--seed", "7",
                             "--out", str(td / "A")], cwd=str(ROOT), env=_replay_env(td, "dA"), capture_output=True, text=True, timeout=3600, check=False)
        meta["A"] = {"rc": pa.returncode, "s": round(time.time() - t0, 1), "tail": pa.stdout[-400:] + pa.stderr[-400:]}
        for j in sorted((td / "A").glob("*.json")):
            shutil.copy2(j, out / "replay_A_strategies.json")
        t0 = time.time()
        build = (f"import sys; sys.path[:0]=[{str(ROOT / 'tests')!r}, {str(ROOT / 'backend')!r}]; import _sh_dataset as d; "
                 f"from pathlib import Path; d.build(Path({str(td / 'ds')!r}), m1_bars={a.m1_bars}, seed=7)")
        pb0 = subprocess.run(["faketime", "-f", spec, PY, "-c", build], cwd=str(ROOT), env=_replay_env(td, "dB"), capture_output=True, text=True,
                             timeout=600, check=False)
        pb = subprocess.run(["faketime", "-f", spec, PY, "-m", "masterquo", "sh", "pack-replay", "--dataset", str(td / "ds"), "--allow-synthetic",
                             "--no-live-write", "--out", str(td / "pack.json")], cwd=str(ROOT / "backend"), env=_replay_env(td, "dB"),
                            capture_output=True, text=True, timeout=3600, check=False)
        meta["B"] = {"rc": pb.returncode, "dataset_rc": pb0.returncode, "s": round(time.time() - t0, 1), "tail": pb.stderr[-400:]}
        if (td / "pack.json").exists():
            shutil.copy2(td / "pack.json", out / "replay_B_pack_summary.json")
        for j in sorted((td / "dB").rglob("pack_validation/runs/*.json")):
            shutil.copy2(j, out / "replay_B_pack_report.json")
    finally:
        shutil.rmtree(td, ignore_errors=True)
    (out / "replay_meta.json").write_text(json.dumps(meta, indent=1, sort_keys=True), encoding="utf-8")
    ok = meta.get("A", {}).get("rc") == 0 and meta.get("B", {}).get("rc") == 0
    print(f"[golden] replay {'OK' if ok else 'BŁĄD'}: {out}")
    return 0 if ok else 1


def _norm_replay(v):
    if isinstance(v, dict):
        return {k: _norm_replay(x) for k, x in v.items() if not REPLAY_VOLATILE.search(str(k))}
    if isinstance(v, list):
        return [_norm_replay(x) for x in v]
    if isinstance(v, str):
        return re.sub(r"/tmp/[^\s\"']+", "<tmp>", UUIDISH.sub("<id>", v))
    return v


def _diff_paths(x, y, p="", out=None, limit=20):
    out = [] if out is None else out
    if len(out) >= limit:
        return out
    if type(x) is not type(y):
        out.append(f"{p}: {repr(x)[:120]} != {repr(y)[:120]}")
    elif isinstance(x, dict):
        for k in sorted(set(x) | set(y), key=str):
            if x.get(k) != y.get(k):
                _diff_paths(x.get(k), y.get(k), f"{p}/{k}", out, limit)
    elif isinstance(x, list):
        if len(x) != len(y):
            out.append(f"{p}: długość {len(x)} != {len(y)}")
        else:
            for i, (u, w) in enumerate(zip(x, y)):
                if u != w:
                    _diff_paths(u, w, f"{p}[{i}]", out, limit)
    elif x != y:
        out.append(f"{p}: {repr(x)[:120]} != {repr(y)[:120]}")
    return out


def _norm(v):
    if isinstance(v, str):
        v = UUIDISH.sub("<id>", v)
        v = ISO_MS.sub(r"\1", v)
        if v[:1] in "{[":
            try:
                return _norm(json.loads(v))
            except ValueError:
                return v
        return v
    if isinstance(v, dict):
        return {k: _norm(x) for k, x in v.items() if not VOLATILE_COL.search(str(k))}
    if isinstance(v, list):
        return [_norm(x) for x in v]
    if isinstance(v, float):
        return round(v, 9)
    return v


def _rows(p: Path) -> list[str]:
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.dumps(_norm(json.loads(line)), sort_keys=True, default=str, ensure_ascii=False))
    return sorted(out)


def cmd_compare(a) -> int:
    """Strict comparison of the deterministic layer (replay A/B: decisions must be identical) + informative comparison of the live
    layer (serve --demo tables: two runs of the SAME code also differ - ticks depend on the second they are read, microstructure
    features, thread order; compare_A_B.md of etap0 is the noise level)."""
    from collections import Counter
    A, B = Path(a.a), Path(a.b)
    out = [f"# Porównanie golden run\n\nA = `{A}`\nB = `{B}`\n"]
    replay_diff = 0
    rep = []
    for f in ("replay_A_strategies.json", "replay_B_pack_summary.json", "replay_B_pack_report.json"):
        fa, fb = A / f, B / f
        if not fa.exists() and not fb.exists():
            continue
        if not (fa.exists() and fb.exists()):
            replay_diff += 1
            rep.append(f"- `{f}`: brak w {'A' if not fa.exists() else 'B'}")
            continue
        da = _norm_replay(json.loads(fa.read_text(encoding="utf-8")))
        db = _norm_replay(json.loads(fb.read_text(encoding="utf-8")))
        if da == db:
            rep.append(f"- `{f}`: **identyczne**")
        else:
            replay_diff += 1
            rep.append(f"- `{f}`: **RÓŻNICE** (zmienione decyzje)")
            rep += [f"  - `{d}`" for d in _diff_paths(da, db)]
    if rep:
        out += ["## Warstwa deterministyczna (replay ścieżki A i B) - porównanie ścisłe\n"] + rep + [""]
    ta = {p.name: p for p in (A / "db").glob("*.jsonl")}
    tb = {p.name: p for p in (B / "db").glob("*.jsonl")}
    if ta or tb:
        rows, details, diff_tables = [], [], 0
        for name in sorted(set(ta) | set(tb)):
            ra = _rows(ta[name]) if name in ta else []
            rb = _rows(tb[name]) if name in tb else []
            ca, cb = Counter(ra), Counter(rb)
            only_a, only_b = list((ca - cb).elements()), list((cb - ca).elements())
            if only_a or only_b or name not in ta or name not in tb:
                diff_tables += 1
                rows.append(f"| `{name[:-6]}` | {len(ra)} | {len(rb)} | {len(only_a)} | {len(only_b)} |")
                details.append(f"\n### {name[:-6]}\n")
                details += [f"- tylko A: `{r[:400]}`" for r in only_a[:5]] + [f"- tylko B: `{r[:400]}`" for r in only_b[:5]]
        same = len(set(ta) | set(tb)) - diff_tables
        out += ["## Warstwa na żywo (serve --demo) - informacyjnie\n",
                (f"Tabele identyczne po normalizacji: {same}; z różnicami: {diff_tables}. Dwa przebiegi NA TYM SAMYM KODZIE też się różnią "
                 "(tiki zależą od sekundy odczytu, cechy mikrostruktury, kolejność wątków) - poziom szumu: docs/arch146/etap0/golden/compare_A_B.md.\n"),
                "| tabela | wiersze A | wiersze B | tylko w A | tylko w B |", "|---|---|---|---|---|"] + rows + details
    text = "\n".join(out) + "\n"
    if a.report:
        Path(a.report).write_text(text, encoding="utf-8")
    print(text[:4000])
    return 0 if replay_diff == 0 else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--out", required=True)
    r.add_argument("--minutes", type=float, default=10.0)
    r.add_argument("--start", default="2026-03-04T08:00:00")
    r.add_argument("--port", type=int, default=8861)
    r.add_argument("--speed", type=float, default=1.0, help="tempo zegara wirtualnego (1 = czas rzeczywisty, 6 = godzina w 10 min)")
    rp = sub.add_parser("replay", help="warstwa deterministyczna: replay ścieżki A i B na symulatorze pod stałym zegarem")
    rp.add_argument("--out", required=True)
    rp.add_argument("--start", default="2026-03-04T08:00:00")
    rp.add_argument("--days", type=int, default=20)
    rp.add_argument("--m1-bars", type=int, default=6000)
    c = sub.add_parser("compare")
    c.add_argument("a")
    c.add_argument("b")
    c.add_argument("--report")
    a = ap.parse_args(argv)
    return {"run": cmd_run, "replay": cmd_replay, "compare": cmd_compare}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
