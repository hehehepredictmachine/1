"""Upgrade from the previous release and rollback, checked on COPIES of the data (never the user's own folder).

  python tools/migration_check.py [--old-ref 5298ec2] [--keep]          (default: 1.29.0 -> this repository, 1.30.x)
  (1.33: on a weekend set MQ_FAKE_MARKET_ALWAYS_OPEN=1 - the simulator is closed Fri 23:00 .. Mon 00:00 and computes no zones)

Everything in a temporary folder, terminal simulator = SYNTHETIC data, no MT5, no orders:
  1. the old version (git worktree of --old-ref) starts on a fresh data folder, computes market zones and - when it still has the
     License Manager (1.27-1.29) - saves a license-server address, so the folder holds leftovers of the removed license system;
  2. a copy is kept as the backup made before the upgrade (the desktop app does this itself in <home>/backups);
  3. this version starts on a second copy: version, configuration kept, database migrations kept, zones restored (marked stale),
     no license API / state any more, leftover license files are not touched (the user may delete them);
  4. rollback: the old version starts on the backup copy; for information also directly on the folder used by the new version.
Prints one line per check (PASS / FAIL) and exits 1 when anything failed. Requires git (worktree) and the Python of the bot.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((name, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}{' – ' + detail if detail else ''}", flush=True)
    return bool(ok)


class Http:
    """The panel's own way in: page "/" sets the session cookie, /api/v1/session gives the CSRF token for writes."""
    def __init__(self, port: int):
        import http.cookiejar
        self.port = port
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.op.open(f"http://127.0.0.1:{port}/", timeout=10).read()
        self.csrf = json.loads(self.op.open(f"http://127.0.0.1:{port}/api/v1/session", timeout=10).read()).get("csrf") or ""

    def get(self, path: str, timeout: float = 15):
        return json.loads(self.op.open(f"http://127.0.0.1:{self.port}{path}", timeout=timeout).read())

    def post(self, path: str, body: dict, timeout: float = 30):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "X-MQ-CSRF": self.csrf, "Origin": f"http://127.0.0.1:{self.port}"})
        return json.loads(self.op.open(req, timeout=timeout).read())


def health(port: int) -> bool:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/v1/health", timeout=3) as r:
        return r.status == 200


class Bot:
    def __init__(self, tree: Path, data: Path, port: int):
        self.tree, self.data, self.port = tree, data, port
        self.env = dict(os.environ, MASTERQUO_DATA_DIR=str(data), PYTHONPATH=str(tree / "backend"))
        for k in ("ANTHROPIC_API_KEY", "MASTERQUO_EDITION_FILE"):
            self.env.pop(k, None)
        self.proc = None

    def __enter__(self):
        self.proc = subprocess.Popen([sys.executable, "-m", "masterquo", "serve", "--demo", "--no-browser"], env=self.env,
                                     cwd=str(self.tree / "backend"), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        t0 = time.time()
        while time.time() - t0 < 120:
            try:
                if health(self.port):
                    self.http = Http(self.port)
                    return self
            except Exception:
                time.sleep(0.5)
        raise RuntimeError(f"bot {self.tree.name} did not start on {self.port}")

    def __exit__(self, *exc):
        subprocess.run([sys.executable, "-m", "masterquo", "stop"], env=self.env, cwd=str(self.tree / "backend"), timeout=90,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            self.proc.wait(timeout=40)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def wait(fn, timeout: float, step: float = 0.5):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            v = fn()
            if v:
                return v
        except Exception:
            pass
        time.sleep(step)
    return None


def version_of(tree: Path) -> str:
    import re
    return re.search(r'APP_VERSION = "([^"]+)"', (tree / "backend" / "masterquo" / "version.py").read_text(encoding="utf-8")).group(1)


def bot_part(old: Path, tmp: Path) -> None:
    ov, nv = version_of(old), version_of(ROOT)
    d_old = tmp / "data_old"
    d_old.mkdir()
    cfg = {"server": {"port": 8811, "open_browser": False}, "news": {"enabled": False}, "clock": {"reference_url": None}, "first_run_completed": True,
           "assets": {"active": "XAUUSD", "mappings": {"XAUUSD": {"broker_symbol": "XAUUSD-", "status": "USER_SPECIFIED"}}}}
    (d_old / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    with Bot(old, d_old, 8811) as b:
        h = b.http
        v = h.get("/api/v1/state")
        check(f"{ov} startuje na świeżych danych", v.get("app_version") == ov, v.get("app_version", "?"))
        wait(lambda: h.get("/api/v1/market-zones/bars?instrument=XAUUSD&tf=M5&count=40")["bars"], 60)
        h.post("/api/v1/market-zones/compute", {"instrument": "XAUUSD", "timeframes": ["M5", "M15"]})
        z = wait(lambda: h.get("/api/v1/market-zones?instrument=XAUUSD")["timeframes"]["M5"].get("computed"), 60)
        check(f"{ov} wyznaczył strefy M5 (dane do migracji)", bool(z))
        try:                       # 1.27-1.29 OWNER: License Manager address + device key -> leftovers of the license system in data/
            h.post("/api/v1/owner/license-server", {"server_url": "https://licencje.example.invalid"})
        except Exception:  # noqa: BLE001 - the example address does not exist; the address is saved anyway
            pass
        mig_old = sorted(r[0] for r in sqlite3.connect(str(d_old / "masterquo.sqlite")).execute("SELECT version FROM schema_migrations"))
    leftovers = sorted(p.name for p in d_old.glob("license*"))
    print(f"  pozostałości licencji w danych {ov}: {leftovers or 'brak'}")
    backup = tmp / "backup_before_upgrade"
    shutil.copytree(d_old, backup)
    d_new = tmp / "data_upgraded"
    shutil.copytree(d_old, d_new)
    cfg_new = json.loads((d_new / "config.json").read_text(encoding="utf-8"))
    cfg_new["server"]["port"] = 8812
    (d_new / "config.json").write_text(json.dumps(cfg_new), encoding="utf-8")
    with Bot(ROOT, d_new, 8812) as b:
        h = b.http
        v = h.get("/api/v1/state")
        check(f"{nv} startuje na kopii danych {ov}", v.get("app_version") == nv, v.get("app_version", "?"))
        check("stan bez sekcji licencji", "license" not in v)
        c = h.get("/api/v1/config")["config"]
        check("konfiguracja zachowana (aktywa, mapowanie, port)", c.get("assets", {}).get("mappings", {}).get("XAUUSD", {}).get("broker_symbol") == "XAUUSD-"
              and c.get("server", {}).get("port") == 8812 and c.get("first_run_completed") is True)
        mz = h.get("/api/v1/market-zones?instrument=XAUUSD")["timeframes"]["M5"]
        check(f"strefy z {ov} odtworzone po aktualizacji (oznaczone jako nieaktualne do przeliczenia)",
              bool(mz.get("computed")) and bool(mz.get("restored") or mz.get("stale")), f"computed={mz.get('computed')} restored={mz.get('restored')}")
        codes = []
        for path in ("/api/v1/license", "/api/v1/owner/license-server"):
            try:
                h.get(path)
                codes.append(200)
            except urllib.error.HTTPError as e:
                codes.append(e.code)
        check("API licencji usunięte (404)", codes == [404, 404], str(codes))
        db = d_new / "masterquo.sqlite"
        mig_new = sorted(r[0] for r in sqlite3.connect(str(db)).execute("SELECT version FROM schema_migrations"))
        check(f"migracje bazy: wszystkie z {ov} zachowane", set(mig_old) <= set(mig_new), f"{len(mig_old)} -> {len(mig_new)}")
    check("pozostałe pliki licencji nietknięte (użytkownik może je usunąć)", sorted(p.name for p in d_new.glob("license*")) == leftovers, str(leftovers))
    # rollback = restore the backup folder, then start the old version
    cfg_b = json.loads((backup / "config.json").read_text(encoding="utf-8"))
    cfg_b["server"]["port"] = 8813
    (backup / "config.json").write_text(json.dumps(cfg_b), encoding="utf-8")
    with Bot(old, backup, 8813) as b:
        v = b.http.get("/api/v1/state")
        check(f"powrót: {ov} działa na kopii zapasowej sprzed aktualizacji", v.get("app_version") == ov)
    cfg_n = json.loads((d_new / "config.json").read_text(encoding="utf-8"))
    cfg_n["server"]["port"] = 8814
    (d_new / "config.json").write_text(json.dumps(cfg_n), encoding="utf-8")
    try:
        with Bot(old, d_new, 8814) as b:
            v = b.http.get("/api/v1/state")
            check(f"(informacyjnie) {ov} uruchomiony wprost na danych po {nv}", v.get("app_version") == ov)
    except RuntimeError as e:
        check(f"(informacyjnie) {ov} uruchomiony wprost na danych po {nv}", False, f"{e} – użyj kopii zapasowej")
    # 1.33: config v13 - the first start keeps the untouched previous file; restoring it is the documented rollback of the settings
    baks = sorted(d_new.glob("config.v*.bak.json"))
    check(f"kopia konfiguracji sprzed {nv} zachowana przy pierwszym starcie", bool(baks), ", ".join(p.name for p in baks) or "brak")
    if baks:
        cfg_r = json.loads(baks[-1].read_text(encoding="utf-8"))
        cfg_r.setdefault("server", {})["port"] = 8815
        (d_new / "config.json").write_text(json.dumps(cfg_r), encoding="utf-8")
        try:
            with Bot(old, d_new, 8815) as b:
                v = b.http.get("/api/v1/state")
                check(f"powrót: {ov} działa na danych po {nv} z przywróconą {baks[-1].name}", v.get("app_version") == ov)
        except RuntimeError as e:
            check(f"powrót: {ov} działa na danych po {nv} z przywróconą {baks[-1].name}", False, str(e))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--old-ref", default="5298ec2", help="commit / tag of the previous release (default: 1.29.0)")
    ap.add_argument("--keep", action="store_true", help="keep the temporary folder")
    a = ap.parse_args()
    tmp = Path(tempfile.mkdtemp(prefix="pmw_migration_"))
    old = tmp / "pmw_old"
    try:
        subprocess.run(["git", "worktree", "add", "-f", "--detach", str(old), a.old_ref], cwd=str(ROOT), check=True, capture_output=True)
        bot_part(old, tmp)
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(old)], cwd=str(ROOT), capture_output=True)
        if not a.keep:
            shutil.rmtree(tmp, ignore_errors=True)
    failed = [n for n, ok, _ in RESULTS if not ok and not n.startswith("(informacyjnie)")]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} PASS" + (f"; FAIL: {failed}" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
